"""console/serve_bridge.py —— 执行桥（设计文档 §7/§8，SOP 第五章 M3）。

纯标准库 http.server；仅绑 127.0.0.1；端口被占直接报错退出（不重试不换口，
防"僵尸占用 + 重复绑定"陷阱——Windows SO_REUSEADDR 允许重复绑定，必须关掉）。

端点：
  GET  /health          → {"ok": true, "tool_version": "..."}（页面据此点亮执行按钮）
  GET  /catalog         → 实况内省 + 与入库 nodes.json 的 diff 报告（在线通道 §9.4）
  POST /run             → 白名单 + 二次校验 → 数组 argv subprocess（永不 shell=True）
  GET  /history?limit=N → console/history.jsonl 尾部 N 条执行审计

二次校验（不信任页面）：node 必须在桥实况目录内；args 逐项按 schema 校验
（未知参数 / 类型错 / 范围越界 / 违反 compose_rules → 400 附违规说明）。

安全边界：白名单 + 数组参数 + 仅本机回环 + 超时强杀 + cwd 必须是已存在目录；
桥不做任何文件写操作（写留痕是 skillverify 自己的事），唯一例外是自己的
执行审计 console/history.jsonl（滚动上限 1000 条）。

零侵入：本进程永不 import skillverify；内省与 trace 根探测一律子进程。

用法：
  <python> console/serve_bridge.py [--tool-cmd "python -m skillverify"]
                                   [--python <内省解释器>] [--port 8742]
                                   [--import <模块>] [--factory <函数>]
                                   [--extra-path <目录>]...
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SCHEMA = "skillverify.console-nodes/1"
HISTORY_LIMIT = 1000          # 审计滚动上限（设计文档 §8）
MAX_BODY = 1 << 20            # 请求体上限 1 MiB
MAX_OUTPUT = 400_000          # /run 回传 stdout/stderr 截断（字符）
DEFAULT_PORT = 8742
TRACE_PROBE_TIMEOUT = 30      # trace 根探测子进程超时（秒）

import build_nodes  # noqa: E402  同目录自有模块（不含 skillverify 依赖）


class BridgeError(Exception):
    """可安全回给页面的错误（400/404/409 级）。"""


# ---------------------------------------------------------------- 内省缓存

class CatalogCache:
    """实况目录缓存：键 = 内省结果内容本身（introspect 很快，键算 mtime 反而易漏）。"""

    def __init__(self, python_exe: str, tool_cmd: list[str], introspect_args: list[str],
                 extra_paths: list[str]):
        self._lock = threading.Lock()
        self._python = python_exe
        self._tool_cmd = tool_cmd
        self._introspect_args = introspect_args
        self._extra_paths = extra_paths
        self._cached: dict | None = None   # {"mech":..., "catalog":..., "key":...}

    def _run_introspect(self) -> dict:
        env = dict(os.environ)
        py_paths = [str(REPO_ROOT), *self._extra_paths]
        if env.get("PYTHONPATH"):
            py_paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(py_paths)
        cmd = [self._python, str(HERE / "introspect.py"), *self._introspect_args]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  encoding="utf-8", timeout=120, env=env,
                                  cwd=str(REPO_ROOT))
        except subprocess.TimeoutExpired as exc:
            raise BridgeError(f"内省子进程超时（120s）：{exc}") from exc
        if proc.returncode != 0:
            raise BridgeError(f"内省子进程失败（exit {proc.returncode}）：{proc.stderr}")
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise BridgeError(f"内省输出不是合法 JSON：{exc}") from exc

    def get(self) -> dict:
        with self._lock:
            mech = self._run_introspect()
            key = json.dumps(mech, sort_keys=True, ensure_ascii=False)
            if self._cached is not None and self._cached["key"] == key:
                return self._cached["catalog"]
            catalog = self._build_catalog(mech)
            self._cached = {"key": key, "catalog": catalog}
            return catalog

    # ---------------- 实况目录（宽容合并：漂移进 diff 报告，不 fatal） ----------------

    def _build_catalog(self, mech: dict) -> dict:
        commands: dict = mech.get("commands", {})
        tool_version = mech.get("tool_version", "")
        paths = [p for p in commands if p]
        leaves = {p for p in paths if not any(q != p and q.startswith(p + " ")
                                              for q in paths)}

        domains_decl, node_semantics, manual_nodes = build_nodes.load_manual(
            HERE / "manual")

        domain_nodes: dict[str, str] = {}
        domains: list[dict] = []
        pipelines: list[dict] = []
        for d in domains_decl:
            dom = d.get("domain")
            if not isinstance(dom, dict) or "id" not in dom:
                continue
            domains.append(dom)
            for nid in d.get("nodes", []):
                domain_nodes[nid] = dom["id"]
            pipelines.extend(d.get("pipelines", []))

        nodes: dict[str, dict] = {}
        notes: list[str] = []

        # 已声明的 CLI 节点：实况内省为准重建机械层 + 语义层合并
        for nid, sem in node_semantics.items():
            command_path = nid.replace(".", " ")
            domain = domain_nodes.get(nid)
            if domain is None:
                notes.append(f"manual/{nid}.json 未被任何 _domain.<域>.json 声明（跳过）")
                continue
            if command_path not in leaves:
                notes.append(f"命令 {command_path!r} 已不在实况内省中（已移除或更名）")
                continue
            node = build_nodes._build_cli_node(command_path, commands[command_path],
                                               self._tool_cmd, domain, [])
            errs: list[str] = []
            build_nodes._merge_manual_node(node, sem, errs)
            if errs:
                notes.append(f"{nid}: 语义层合并告警（按机械层降级）——" + "；".join(errs))
            nodes[nid] = node

        # manual 型节点
        for nid, mn in manual_nodes.items():
            domain = domain_nodes.get(nid)
            if domain is None:
                continue
            node = {"id": nid, "domain": domain, "title": nid,
                    "summary": None, "node_type": "manual",
                    "params": [], "inputs": [], "outputs": [], "consumers": [],
                    "compose_rules": [], "pitfalls": [],
                    "execution": {"class": "manual", "history": "central"},
                    "source": {"params": "none", "semantics": "manual"}}
            node.update({k: v for k, v in mn.items()
                         if k in ("title", "summary", "inputs", "outputs",
                                  "consumers", "pitfalls", "execution", "actions",
                                  "ref", "effects", "rules", "rules_note")})
            nodes[nid] = node

        # 实况有、语义层未覆盖的叶子命令 → 新节点（manual_missing，设计文档 §9.4）
        for command_path in sorted(leaves):
            nid = command_path.replace(" ", ".")
            if nid in nodes:
                continue
            node = build_nodes._build_cli_node(command_path, commands[command_path],
                                               self._tool_cmd, "__new__", [])
            node["manual_missing"] = True
            nodes[nid] = node

        diff = self._diff_against_committed(nodes)

        # hosts.toml 档位实时快照（M4-03）：与构建同形状，页面 hosts 面板
        # 桥模式下自动切换为实时数据；失败静默（面板降级为隐藏/静态）
        hosts_panel = None
        try:
            proc = subprocess.run(list(self._tool_cmd) + ["discover", "--show-config"],
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=30,
                                  cwd=str(REPO_ROOT))
            if proc.returncode == 0 and proc.stdout.strip():
                hosts_panel = {"source": "执行桥实时捕获（discover --show-config）",
                               "text": proc.stdout}
        except (OSError, subprocess.SubprocessError):
            pass

        return {
            "schema": SCHEMA,
            "tool_version": tool_version,
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "domains": domains,
            "pipelines": pipelines,
            "nodes": nodes,
            "diff": diff,
            "notes": notes,
            "hosts_panel": hosts_panel,
        }

    @staticmethod
    def _diff_against_committed(live_nodes: dict) -> dict:
        """与入库 nodes.json 逐字段对账（设计文档 §9.4 差异报告）。"""
        committed_path = HERE / "nodes.json"
        try:
            committed = json.loads(committed_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"available": False, "reason": "入库 nodes.json 不可读",
                    "new_nodes": [], "removed_nodes": [], "param_changes": [],
                    "summary": ""}
        old_nodes = committed.get("nodes", {})
        new_nodes = sorted(nid for nid, n in live_nodes.items()
                           if nid not in old_nodes and n["node_type"] == "cli")
        removed = sorted(nid for nid, n in old_nodes.items()
                         if nid not in live_nodes and n["node_type"] == "cli")
        changes: list[dict] = []
        for nid, node in sorted(live_nodes.items()):
            if node["node_type"] != "cli" or nid not in old_nodes:
                continue
            old_params = {p["id"]: p for p in old_nodes[nid].get("params", [])}
            new_params = {p["id"]: p for p in node.get("params", [])}
            for pid in sorted(set(new_params) - set(old_params)):
                changes.append({"node": nid, "param": pid, "field": "param",
                                "change": "新增",
                                "new": new_params[pid].get("help")})
            for pid in sorted(set(old_params) - set(new_params)):
                changes.append({"node": nid, "param": pid, "field": "param",
                                "change": "移除", "old": None})
            for pid in set(old_params) & set(new_params):
                for field in ("default", "required", "nargs"):
                    old_v, new_v = old_params[pid].get(field), new_params[pid].get(field)
                    if old_v != new_v:
                        changes.append({"node": nid, "param": pid, "field": field,
                                        "change": "变更", "old": old_v, "new": new_v})
                old_ch = (old_params[pid].get("type") or {}).get("choices")
                new_ch = (new_params[pid].get("type") or {}).get("choices")
                if old_ch != new_ch:
                    changes.append({"node": nid, "param": pid, "field": "choices",
                                    "change": "变更", "old": old_ch, "new": new_ch})
        parts = []
        if new_nodes:
            parts.append(f"新增节点 {len(new_nodes)}")
        if removed:
            parts.append(f"移除节点 {len(removed)}")
        if changes:
            parts.append(f"参数变更 {len(changes)}")
        return {"available": True, "new_nodes": new_nodes, "removed_nodes": removed,
                "param_changes": changes,
                "summary": "；".join(parts) if parts else "与入库快照一致"}


# ---------------------------------------------------------------- trace 根与审计

def _probe_trace_root(python_exe: str, cwd: Path) -> Path:
    """经 skillverify 的 hosts.toml 发现机制定位 trace 根（子进程，不 import）。"""
    probe = (
        "import json,sys;"
        "from pathlib import Path;"
        "from skillverify.discover import load_config,discover_skills;"
        "p=Path(sys.argv[1]).expanduser();"
        "c=load_config(p,Path.home(),[],use_discovered_files=True);"
        "d=discover_skills(c.profile(None),p,Path.home(),roots=None);"
        "print(json.dumps({'trace_dir':str(d.trace_dir) if d.trace_dir else None}))"
    )
    try:
        proc = subprocess.run([python_exe, "-c", probe, str(cwd)], capture_output=True,
                              text=True, encoding="utf-8", timeout=TRACE_PROBE_TIMEOUT,
                              cwd=str(cwd))
        if proc.returncode == 0:
            data = json.loads(proc.stdout.strip().splitlines()[-1])
            td = data.get("trace_dir")
            if td:
                p = Path(td)
                return p if p.is_absolute() else (cwd / p).resolve()
    except Exception:  # noqa: BLE001 —— 探测失败走兜底，不阻断执行
        pass
    return (cwd / ".agents" / "skillverify").resolve()


def _history_path(python_exe: str, cwd: Path) -> Path:
    return _probe_trace_root(python_exe, cwd) / "console" / "history.jsonl"


def _append_history(path: Path, record: dict) -> None:
    """仅追加 + 滚动上限 1000（读改写只在越限时发生一次）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line)
    with path.open("r", encoding="utf-8") as fh:
        lines = fh.readlines()
    if len(lines) > HISTORY_LIMIT:
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.writelines(lines[-HISTORY_LIMIT:])


def _read_history(path: Path, limit: int) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        lines = fh.readlines()
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ---------------------------------------------------------------- /run 二次校验

def _check_value(node_id: str, p: dict, value, issues: list) -> None:
    label = p.get("flag") or f"<{p['id']}>"
    t = p.get("type") or {}
    kind = t.get("kind")
    if p["form"]["widget"] == "flag":
        if not isinstance(value, bool):
            issues.append(f"{node_id}.{p['id']}: flag 参数须为布尔，收到 {value!r}")
        return
    if not isinstance(value, (str, int, float)):
        issues.append(f"{node_id}.{p['id']}: {label} 值须为字符串/数值，收到 {type(value).__name__}")
        return
    s = str(value).strip()
    if not s:
        issues.append(f"{node_id}.{p['id']}: {label} 值为空")
        return
    if p["form"]["widget"] == "number":
        try:
            n = float(s)
        except ValueError:
            issues.append(f"{node_id}.{p['id']}: {label} 须为数值，收到 {s!r}")
            return
        if kind == "int" and not n.is_integer():
            issues.append(f"{node_id}.{p['id']}: {label} 须为整数")
            return
        if t.get("min") is not None and n < t["min"] or t.get("max") is not None and n > t["max"]:
            issues.append(f"{node_id}.{p['id']}: {label} 超出范围 "
                          f"{t.get('min')}..{t.get('max')}")
        return
    if kind == "choice" and t.get("choices") and s not in t["choices"]:
        issues.append(f"{node_id}.{p['id']}: {label} 取值须为 {' / '.join(t['choices'])}，"
                      f"收到 {s!r}")
        return
    if kind == "path" and (t.get("must_exist") or t.get("must_be_dir")):
        path = Path(s).expanduser()
        if not path.exists():
            issues.append(f"{node_id}.{p['id']}: {label} 路径不存在：{s}")
        elif t.get("must_be_dir") and not path.is_dir():
            issues.append(f"{node_id}.{p['id']}: {label} 须为目录：{s}")


def _apply_compose_rules(node: dict, args: dict, confirmed: set,
                         issues: list) -> None:
    by_id = {p["id"]: p for p in node["params"]}

    def val(pid):
        p = by_id.get(pid)
        if p is None:
            return None
        v = args.get(pid)
        if p["form"]["widget"] == "flag":
            return v if isinstance(v, bool) and v else None
        if isinstance(v, str) and v.strip():
            return v.strip()
        return v if isinstance(v, (int, float)) else None

    for rule in node.get("compose_rules") or []:
        r = rule.get("rule")
        if r == "requires":
            when_ok = not rule.get("when") or val(rule["when"]) is not None
            if when_ok and val(rule.get("require", "")) is None:
                issues.append(rule.get("message") or
                              f"{node['id']}: 违反 requires 规则")
        elif r == "excludes":
            active = [pid for pid in (rule.get("params") or []) if val(pid) is not None]
            if len(active) > 1:
                issues.append(rule.get("message") or
                              f"{node['id']}: 违反互斥规则（{', '.join(active)}）")
        elif r == "confirm":
            target = by_id.get(rule.get("param", ""))
            active = (target and target["form"]["widget"] == "flag"
                      and val(rule["param"]) is not None) or \
                     (target and target["form"]["widget"] != "flag"
                      and val(rule["param"]) is not None)
            if active and rule.get("param") not in confirmed:
                issues.append(rule.get("message") or
                              f"{node['id']}: {rule.get('param')} 需显式确认")


def build_argv(node: dict, args: dict) -> list[str]:
    """桥端 argv 组装：与页面 buildTokens 同源同序（机械字段为准）。

    实况目录里 cli.argv 已带桥的 tool-cmd 前缀（_build_catalog 重建时注入），
    直接使用，不再剥离/重拼。"""
    argv = list(node["cli"]["argv"])
    for p in node["params"]:
        pid = p["id"]
        if pid not in args:
            continue
        raw = args[pid]
        if p["form"]["widget"] == "flag":
            if raw is True:
                argv.append(p["flag"])
            continue
        if p.get("flag") is None:  # 位置参数
            parts = str(raw).split() if p.get("nargs") == "*" else [str(raw)]
            argv.extend(parts)
            continue
        if p["form"]["widget"] == "multi-choice":
            items = [x for x in str(raw).replace(",", " ").split() if x]
            for item in items:
                argv.extend([p["flag"], item])
            continue
        if p.get("nargs") == 2:
            vals = str(raw).split()
            if len(vals) != 2:
                raise BridgeError(f"{node['id']}.{pid}: 该参数需要恰好两个值（空格分隔）")
            argv.extend([p["flag"], *vals])
            continue
        argv.extend([p["flag"], str(raw)])
    return argv


# ---------------------------------------------------------------- HTTP 服务

class BridgeState:
    def __init__(self, python_exe: str, tool_cmd: list[str], introspect_args: list[str],
                 extra_paths: list[str]):
        self.python = python_exe
        self.tool_cmd = tool_cmd
        self.cache = CatalogCache(python_exe, tool_cmd, introspect_args, extra_paths)
        self._history_file: Path | None = None

    def history_file(self) -> Path:
        """桥级审计单点：启动后按首个请求惰性探测一次（hosts.toml 发现 trace 根）。

        审计层归属桥自身（trace 根取桥启动目录的发现结果），不随每次 /run 的
        cwd 漂移——否则 GET /history 无从聚合。"""
        if self._history_file is None:
            self._history_file = _history_path(self.python, REPO_ROOT)
        return self._history_file


BRIDGE: BridgeState | None = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ---- 基础 ----
    def _send(self, code: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # 静默访问日志
        pass

    def do_OPTIONS(self):  # file:// 跨源预检
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path == "/health":
                catalog = BRIDGE.cache.get()
                self._send(200, {"ok": True, "tool_version": catalog["tool_version"]})
            elif url.path == "/catalog":
                self._send(200, BRIDGE.cache.get())
            elif url.path == "/history":
                qs = parse_qs(url.query)
                try:
                    limit = min(int(qs.get("limit", ["50"])[0]), 1000)
                except ValueError:
                    limit = 50
                path = BRIDGE.history_file()
                self._send(200, {"records": _read_history(path, limit),
                                 "path": str(path)})
            else:
                self._send(404, {"error": f"未知端点 {url.path}"})
        except BridgeError as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"error": f"桥内部错误：{exc}"})

    def do_POST(self):
        if urlparse(self.path).path != "/run":
            self._send(404, {"error": "未知端点（POST 仅支持 /run）"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                raise BridgeError(f"请求体须在 1..{MAX_BODY} 字节")
            req = json.loads(self.rfile.read(length).decode("utf-8"))
            self._send(200, self._handle_run(req))
        except BridgeError as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"error": f"桥内部错误：{exc}"})

    def _handle_run(self, req: dict) -> dict:
        node_id = req.get("node")
        args = req.get("args") or {}
        confirmed = set(req.get("confirmed") or [])
        if not isinstance(node_id, str) or not node_id:
            raise BridgeError("缺少 node 字段")
        if not isinstance(args, dict):
            raise BridgeError("args 须为对象（paramId → 值）")

        catalog = BRIDGE.cache.get()
        node = catalog["nodes"].get(node_id)
        if node is None:
            raise BridgeError(f"未知节点 {node_id!r}（不在桥实况目录白名单内）")
        if node["node_type"] != "cli":
            raise BridgeError(f"节点 {node_id} 是行动卡（manual 型），没有可执行命令")

        cwd = Path(str(req.get("cwd") or REPO_ROOT)).expanduser()
        if not cwd.exists() or not cwd.is_dir():
            raise BridgeError(f"cwd 必须是已存在目录：{cwd}")

        # 逐参数校验
        issues: list[str] = []
        known = {p["id"] for p in node["params"]}
        for pid in args:
            if pid not in known:
                issues.append(f"未知参数 {pid!r}（{node_id} 无此参数）")
        for p in node["params"]:
            if p["id"] in args:
                _check_value(node_id, p, args[p["id"]], issues)
        for p in node["params"]:
            if p["form"]["required"] and p["id"] not in args and p.get("flag") is None:
                issues.append(f"{p['flag'] or p['id']} 为必填项")
        _apply_compose_rules(node, args, confirmed, issues)
        if issues:
            raise BridgeError("参数校验未通过：\n  - " + "\n  - ".join(issues))

        argv = build_argv(node, args)
        timeout = node.get("execution", {}).get("timeout_s") or 600
        try:
            req_timeout = req.get("timeout_s")
            if req_timeout is not None:
                timeout = max(1, min(float(req_timeout), float(timeout)))
        except (TypeError, ValueError):
            pass

        started = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(argv, cwd=str(cwd), capture_output=True,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=timeout, shell=False)
            exit_code = proc.returncode
            stdout, stderr = proc.stdout or "", proc.stderr or ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = None
            stdout = (exc.stdout or b"").decode("utf-8", "replace") \
                if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = ((exc.stderr or b"").decode("utf-8", "replace")
                      if isinstance(exc.stderr, bytes) else (exc.stderr or "")) \
                + f"\n[桥] 超时 {timeout}s，进程已被强杀"
        duration_ms = int((time.monotonic() - started) * 1000)

        _append_history(BRIDGE.history_file(), {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "node": node_id,
            "argv": argv,
            "cwd": str(cwd),
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "timed_out": timed_out,
        })

        return {
            "ok": not timed_out and exit_code == 0,
            "node": node_id,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "timed_out": timed_out,
            "timeout_s": timeout,
            "stdout": stdout[-MAX_OUTPUT:],
            "stderr": stderr[-MAX_OUTPUT:],
        }


class BridgeServer(ThreadingHTTPServer):
    # Windows 上 SO_REUSEADDR 允许重复绑定成功（请求全打到旧进程）——必须关
    allow_reuse_address = False
    daemon_threads = True


def main(argv: list[str] | None = None) -> int:
    global BRIDGE
    ap = argparse.ArgumentParser(
        prog="serve_bridge.py",
        description="skillverify 操作台执行桥（仅 127.0.0.1；端口被占直接退出）",
    )
    ap.add_argument("--tool-cmd", default="skillverify",
                    help="skillverify 调用链（/run 的 argv 前缀；默认 skillverify，"
                         "开发仓库用 --tool-cmd \"python -m skillverify\"）")
    ap.add_argument("--python", default=sys.executable,
                    help="内省与 trace 探测用解释器（默认当前解释器）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"监听端口（默认 {DEFAULT_PORT}）")
    ap.add_argument("--import", dest="module", default=None,
                    help="转发给 introspect.py：parser 工厂所在模块（默认 skillverify.cli）")
    ap.add_argument("--factory", default=None,
                    help="转发给 introspect.py：工厂函数名（默认 build_parser）")
    ap.add_argument("--extra-path", action="append", default=[],
                    help="追加到内省子进程 PYTHONPATH（可重复；用于 --import 自定义模块）")
    args = ap.parse_args(argv)

    tool_cmd = shlex.split(args.tool_cmd)
    introspect_args = []
    if args.module:
        introspect_args += ["--import", args.module]
    if args.factory:
        introspect_args += ["--factory", args.factory]

    BRIDGE = BridgeState(args.python, tool_cmd, introspect_args, args.extra_path)

    # 先试内省（起服前失败快）；再绑端口（被占 exit 非零，不重试不换口）
    try:
        catalog = BRIDGE.cache.get()
    except BridgeError as exc:
        print(f"serve_bridge: 启动失败——内省不可用：\n{exc}", file=sys.stderr)
        return 1

    try:
        server = BridgeServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        print(f"serve_bridge: 端口 {args.port} 绑定失败（被占或无权限）：{exc}\n"
              f"按设计不重试不换口，直接退出。", file=sys.stderr)
        return 1

    print(f"执行桥已就绪：http://127.0.0.1:{args.port}"
          f"（tool_version={catalog['tool_version'] or '未知'}，"
          f"节点 {len(catalog['nodes'])} 个）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n执行桥已停止")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
