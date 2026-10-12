"""console/build_nodes.py —— 生成器（设计文档 §4/§9.1，SOP 第三章 S2）。

职责：
1. 子进程跑 introspect.py 得机械层（子命令树 + 逐参数机械属性）；
2. 读 console/manual/*.json 得语义层，按节点 id 合并；
3. 输出 console/nodes.json（schema `skillverify.console-nodes/1`，含 domains/pipelines/nodes）。

合并规则（机械层为准，冲突即失败）：
- manual 节点级允许键：summary / inputs / outputs / consumers / effects / pitfalls /
  execution / compose_rules / params（params 为逐参数语义子对象容器）；
- manual 参数级允许键：effects / pitfall / form(required|placeholder|widget) / type(数值细化)；
- 参数级禁止触碰机械已声明字段：id / flag / flags / action / nargs / default /
  choices / required(CLI 层) / help —— 出现即逐条列出并 exit 1；
- type 细化只允许补 min / max / must_exist / must_be_dir，kind/choices 必须与机械层一致；
- params.<id> 必须存在于机械层（语义不得凭空造参数）。

域/流程线声明：manual 目录下 `_domain.<域>.json`（下划线前缀 = 非节点配置），声明
domain 元数据、该域包含的节点 id、pipelines（节点链/条件节点/变体槽）与 manual 型
节点（会话评/人工评等非 CLI 节点）的完整定义。生成器按 manual 目录内容决定域范围。

用法：
    <python> console/build_nodes.py [--python <解释器>] [--tool-cmd "skillverify"]
                                    [--out console/nodes.json] [--manual-dir console/manual]
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path

SCHEMA = "skillverify.console-nodes/1"

# form.widget 枚举（设计文档 §4）
WIDGETS = ("text", "path", "number", "choice", "multi-choice", "flag", "runner",
           "dir-picker")
# compose_rules 四原语（设计文档 §6）
RULES = ("requires", "excludes", "suggest", "confirm")
# manual 节点级允许键（ref = 条目溯源出处，铁律 §五.1；condition = 条件节点声明，设计文档 §3；
# rules/rules_note = 规则目录快照（如 lint 47 条），守卫测试负责与源码对账）
NODE_MANUAL_KEYS = {"summary", "inputs", "outputs", "consumers", "effects",
                    "pitfalls", "execution", "compose_rules", "params",
                    "ref", "condition", "rules", "rules_note"}
# manual 参数级允许键
PARAM_MANUAL_KEYS = {"effects", "pitfall", "form", "type", "ref", "note"}
PARAM_FORM_KEYS = {"required", "placeholder", "widget"}
PARAM_TYPE_REFINE_KEYS = {"min", "max", "must_exist", "must_be_dir"}
# 机械层已声明、语义层禁触的参数字段
PARAM_MECHANICAL_KEYS = {"id", "flag", "flags", "action", "nargs", "default",
                         "choices", "required", "help"}

FLAG_ACTIONS = ("_StoreTrueAction", "_StoreFalseAction", "_CountAction")


class BuildError(Exception):
    """生成失败（冲突/自检不过）；收集全部问题后一次性报出。"""


# ---------------------------------------------------------------- 机械层映射

def _type_name(opt: dict) -> str | None:
    t = opt.get("type")
    return t if isinstance(t, str) else None


def _widget_for(opt: dict) -> str:
    """从机械属性推导表单控件（通用启发式，不针对特定工具）。"""
    if opt.get("action") in FLAG_ACTIONS:
        return "flag"
    if opt.get("choices") and opt.get("action") != "_AppendAction":
        return "choice"
    if opt.get("action") == "_AppendAction":
        return "multi-choice"
    kind = _type_name(opt)
    if kind in ("int", "float"):
        return "number"
    metavar = opt.get("metavar") or ""
    if metavar == "命令":
        return "runner"
    if metavar in ("目录", "文件", "路径"):
        return "path"
    flag = opt.get("flag") or ""
    if any(part in flag for part in ("dir", "file", "path")):
        return "path"
    return "text"


def _mech_param_from_option(opt: dict) -> dict:
    widget = _widget_for(opt)
    if opt.get("action") in FLAG_ACTIONS:
        mtype = {"kind": "flag"}
    elif opt.get("choices"):
        mtype = {"kind": "choice", "choices": opt["choices"]}
    elif _type_name(opt) in ("int", "float"):
        mtype = {"kind": _type_name(opt)}
    elif widget in ("path", "dir-picker"):
        mtype = {"kind": "path"}
    else:
        mtype = {"kind": "string"}
    return {
        "id": opt["id"],
        "flag": opt["flag"],
        "form": {"widget": widget, "required": bool(opt.get("required")),
                 "placeholder": ""},
        "type": mtype,
        "default": opt.get("default"),
        "composes": [],
        "effects": None,
        "pitfall": None,
        "help": opt.get("help"),
        "nargs": opt.get("nargs"),
    }


def _mech_param_from_positional(pos: dict) -> dict:
    return {
        "id": pos["id"],
        "flag": None,
        "form": {"widget": "path", "required": pos.get("nargs") not in ("*", "?"),
                 "placeholder": ""},
        "type": {"kind": "path"},
        "default": None,
        "composes": [],
        "effects": None,
        "pitfall": None,
        "help": pos.get("help"),
        "nargs": pos.get("nargs"),
    }


# ---------------------------------------------------------------- 语义层合并

def _merge_manual_param(param: dict, sem: dict, node_id: str, errors: list) -> None:
    unknown = set(sem) - PARAM_MANUAL_KEYS
    if unknown:
        errors.append(f"{node_id}.params.{param['id']}: 未知键 {sorted(unknown)}；"
                      f"允许键 {sorted(PARAM_MANUAL_KEYS)}")
    mech_conflict = unknown & PARAM_MECHANICAL_KEYS
    if mech_conflict:
        errors.append(f"{node_id}.params.{param['id']}: 语义层禁止覆盖机械层字段 "
                      f"{sorted(mech_conflict)}")
    if "effects" in sem and isinstance(sem["effects"], str):
        param["effects"] = sem["effects"]
    if "pitfall" in sem and isinstance(sem["pitfall"], str):
        param["pitfall"] = sem["pitfall"]

    form = sem.get("form")
    if isinstance(form, dict):
        fbad = set(form) - PARAM_FORM_KEYS
        if fbad:
            errors.append(f"{node_id}.params.{param['id']}.form: 未知键 {sorted(fbad)}")
        if "widget" in form:
            if form["widget"] not in WIDGETS:
                errors.append(f"{node_id}.params.{param['id']}.form.widget: "
                              f"非法枚举 {form['widget']!r}（允许 {list(WIDGETS)}）")
            else:
                param["form"]["widget"] = form["widget"]
        if "required" in form:
            if not isinstance(form["required"], bool):
                errors.append(f"{node_id}.params.{param['id']}.form.required: 须为 bool")
            else:
                param["form"]["required"] = form["required"]
        if "placeholder" in form:
            param["form"]["placeholder"] = str(form["placeholder"])

    refine = sem.get("type")
    if isinstance(refine, dict):
        tbad = set(refine) - PARAM_TYPE_REFINE_KEYS
        if tbad:
            errors.append(f"{node_id}.params.{param['id']}.type: 细化仅允许 "
                          f"{sorted(PARAM_TYPE_REFINE_KEYS)}，不得改 {sorted(tbad)}")
        if "kind" in refine and refine["kind"] != param["type"]["kind"]:
            errors.append(f"{node_id}.params.{param['id']}.type.kind: 语义层 "
                          f"{refine['kind']!r} 与机械层 {param['type']['kind']!r} 冲突")
        if "choices" in refine and refine["choices"] != param["type"].get("choices"):
            errors.append(f"{node_id}.params.{param['id']}.type.choices: "
                          "语义层不得改 choices（机械层为准）")
        for key in ("min", "max"):
            if key in refine and not isinstance(refine[key], (int, float)):
                errors.append(f"{node_id}.params.{param['id']}.type.{key}: 数值约束必须显式写数值")
            elif key in refine:
                param["type"][key] = refine[key]
        for key in ("must_exist", "must_be_dir"):
            if key in refine:
                if not isinstance(refine[key], bool):
                    errors.append(f"{node_id}.params.{param['id']}.type.{key}: 须为 bool")
                else:
                    param["type"][key] = refine[key]

    if param["type"]["kind"] in ("int", "float") and "min" in param["type"] \
            and "max" in param["type"] and param["type"]["min"] > param["type"]["max"]:
        errors.append(f"{node_id}.params.{param['id']}.type: min > max")


def _merge_manual_node(node: dict, sem: dict, errors: list) -> None:
    unknown = set(sem) - NODE_MANUAL_KEYS
    if unknown:
        errors.append(f"{node['id']}: manual 未知键 {sorted(unknown)}；"
                      f"允许键 {sorted(NODE_MANUAL_KEYS)}")
    for key in ("summary", "inputs", "outputs", "consumers", "pitfalls",
                "execution", "compose_rules", "effects", "ref", "condition",
                "rules", "rules_note"):
        if key in sem:
            node[key] = sem[key]
    node["source"]["semantics"] = "manual"

    params_sem = sem.get("params")
    if params_sem is not None:
        if not isinstance(params_sem, dict):
            errors.append(f"{node['id']}.params: 语义参数表须为对象（param id → 语义）")
        else:
            by_id = {p["id"]: p for p in node["params"]}
            for pid, psem in params_sem.items():
                if pid not in by_id:
                    errors.append(f"{node['id']}.params.{pid}: 机械层无此参数"
                                  f"（语义层不得凭空造参数）")
                    continue
                if not isinstance(psem, dict):
                    errors.append(f"{node['id']}.params.{pid}: 语义条目须为对象")
                    continue
                _merge_manual_param(by_id[pid], psem, node["id"], errors)

    # compose_rules 引用检查
    for rule in node.get("compose_rules") or []:
        if not isinstance(rule, dict) or rule.get("rule") not in RULES:
            errors.append(f"{node['id']}.compose_rules: 规则须为对象且 rule ∈ {list(RULES)}")


# ---------------------------------------------------------------- 节点装配

def _split_command(command_path: str) -> list[str]:
    return command_path.split() if command_path else []


def _build_cli_node(command_path: str, mech: dict, tool_cmd: list[str],
                    domain: str, errors: list) -> dict:
    tokens = _split_command(command_path)
    params = [_mech_param_from_positional(p) for p in mech.get("positionals", [])]
    params += [_mech_param_from_option(o) for o in mech.get("options", [])]
    return {
        "id": command_path.replace(" ", "."),
        "domain": domain,
        "title": command_path,
        "summary": None,
        "node_type": "cli",
        "cli": {"argv": [*tool_cmd, *tokens],
                "positional": [p["id"] for p in mech.get("positionals", [])]},
        "params": params,
        "inputs": [],
        "outputs": [],
        "consumers": [],
        "compose_rules": [],
        "execution": {"timeout_s": 600, "class": "read-only", "history": "audit"},
        "pitfalls": [],
        "source": {"params": "argparse", "semantics": "none"},
    }


def _validate_manual_node(manual_node: dict, where: str, errors: list) -> None:
    if manual_node.get("node_type") != "manual":
        errors.append(f"{where}: manual 型节点 node_type 必须为 \"manual\"")
        return
    unknown = set(manual_node) - (NODE_MANUAL_KEYS | {"id", "domain", "title",
                                                       "node_type", "source",
                                                       "actions"})
    if unknown:
        errors.append(f"{where}: manual 型节点未知键 {sorted(unknown)}")


def _check_presets(pipelines: list, nodes: dict, errors: list) -> None:
    """套餐预填引用检查（M2 套餐）：values/variants 必须指向已知节点与参数。"""
    for pl in pipelines:
        presets = pl.get("presets")
        if presets is None:
            continue
        where = f"pipelines[{pl.get('id', '?')}]"
        if not isinstance(presets, list):
            errors.append(f"{where}.presets: 须为数组")
            continue
        for i, ps in enumerate(presets):
            w = f"{where}.presets[{i}]"
            if not isinstance(ps, dict) or not ps.get("id") or not ps.get("title"):
                errors.append(f"{w}: 须为含 id/title 的对象")
                continue
            values = ps.get("values") or {}
            if not isinstance(values, dict):
                errors.append(f"{w}.values: 须为对象（nodeId → paramId → 值）")
                values = {}
            for nid, vals in values.items():
                if nid not in nodes:
                    errors.append(f"{w}.values: 引用未知节点 {nid!r}")
                    continue
                if nodes[nid]["node_type"] != "cli":
                    errors.append(f"{w}.values: {nid} 不是 cli 节点（manual 节点无表单）")
                    continue
                ids = {p["id"] for p in nodes[nid]["params"]}
                for pid, v in (vals if isinstance(vals, dict) else {}).items():
                    if pid not in ids:
                        errors.append(f"{w}.values.{nid}: 引用未知参数 {pid!r}")
                    elif not isinstance(v, (str, int, float, bool)):
                        errors.append(f"{w}.values.{nid}.{pid}: 值须为 JSON 标量")
            variants = ps.get("variants") or {}
            if not isinstance(variants, dict):
                errors.append(f"{w}.variants: 须为对象（slot → nodeId）")
                variants = {}
            for slot, vid in variants.items():
                if vid not in nodes:
                    errors.append(f"{w}.variants[{slot!r}]: 引用未知节点 {vid!r}")


# ---------------------------------------------------------------- 自检

def _check_node(node: dict, errors: list) -> None:
    nid = node.get("id", "<no-id>")
    if not isinstance(nid, str) or not nid:
        errors.append("node.id 非空字符串")
        return
    if node.get("node_type") == "manual":
        return
    rules = node.get("rules")
    if rules is not None:
        if not isinstance(rules, list) or not rules:
            errors.append(f"{nid}: rules 须为非空数组（规则目录快照）")
        else:
            for i, r in enumerate(rules):
                if not isinstance(r, dict) or not all(
                        isinstance(r.get(k), str) and r.get(k)
                        for k in ("rid", "level", "title")):
                    errors.append(f"{nid}.rules[{i}]: 每条须含非空 rid/level/title 字符串")
    if not node.get("cli", {}).get("argv"):
        errors.append(f"{nid}: cli 节点缺 cli.argv")
    params = node.get("params")
    if not isinstance(params, list) or not params:
        errors.append(f"{nid}: params 须为非空数组")
        return
    for p in params:
        pid = p.get("id", "<no-id>")
        if not isinstance(p.get("id"), str) or not p["id"]:
            errors.append(f"{nid}: 参数缺 id")
        w = p.get("form", {}).get("widget")
        if w not in WIDGETS:
            errors.append(f"{nid}.params.{pid}: form.widget 非法 {w!r}")
        if not isinstance(p.get("form", {}).get("required"), bool):
            errors.append(f"{nid}.params.{pid}: form.required 须为 bool")
        t = p.get("type")
        if not isinstance(t, dict) or not isinstance(t.get("kind"), str):
            errors.append(f"{nid}.params.{pid}: type 须为含 kind 的对象")
        else:
            if t["kind"] in ("int", "float"):
                for k in ("min", "max"):
                    if k in t and not isinstance(t[k], (int, float)) or isinstance(t.get(k), bool):
                        errors.append(f"{nid}.params.{pid}: type.{k} 数值约束必须显式写数值")
            if t["kind"] == "choice" and not isinstance(t.get("choices"), list):
                errors.append(f"{nid}.params.{pid}: kind=choice 须带 choices 数组")
        if p.get("default") is not None and not isinstance(
                p["default"], (str, int, float, bool, list)):
            errors.append(f"{nid}.params.{pid}: default 须为 JSON 标量/数组")
    for rule in node.get("compose_rules") or []:
        if not isinstance(rule, dict) or rule.get("rule") not in RULES:
            errors.append(f"{nid}: compose_rules 规则非法（须 rule ∈ {list(RULES)}）")
            continue
        if not rule.get("message"):
            errors.append(f"{nid}: compose_rules 每条须带 message")
        refs = []
        if rule["rule"] in ("requires", "confirm", "suggest"):
            refs = [rule.get("require") or rule.get("param")]
        elif rule["rule"] == "excludes":
            refs = rule.get("params") or []
        ids = {p["id"] for p in params}
        for ref in refs:
            if ref not in ids:
                errors.append(f"{nid}: compose_rules 引用未知参数 {ref!r}")


# ---------------------------------------------------------------- 主流程

def run_introspection(python_exe: str, introspect_path: Path) -> dict:
    proc = subprocess.run(
        [python_exe, str(introspect_path)],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    if proc.returncode != 0:
        raise BuildError(f"内省子进程失败（exit {proc.returncode}）：\n{proc.stderr}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise BuildError(f"内省输出不是合法 JSON：{exc}") from exc


def load_manual(manual_dir: Path) -> tuple[list[dict], dict[str, dict], dict[str, dict]]:
    """返回 (domain 声明列表, 节点语义表, manual 型节点表)。"""
    domains: list[dict] = []
    node_semantics: dict[str, dict] = {}
    manual_nodes: dict[str, dict] = {}
    for path in sorted(manual_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if path.name.startswith("_domain."):
            data["_source_file"] = path.name
            domains.append(data)
            for mn in data.get("manual_nodes", {}):
                manual_nodes[mn] = data["manual_nodes"][mn]
        else:
            node_semantics[path.stem] = data
    return domains, node_semantics, manual_nodes


def build(repo_root: Path, python_exe: str, tool_cmd: list[str], out_path: Path,
          manual_dir: Path) -> dict:
    errors: list[str] = []
    mech = run_introspection(python_exe, repo_root / "console" / "introspect.py")
    commands: dict = mech.get("commands", {})
    tool_version = mech.get("tool_version", "")

    # 叶子命令 = 不是其他命令路径前缀的命令
    paths = [p for p in commands if p]
    leaves = {p for p in paths if not any(q != p and q.startswith(p + " ")
                                          for q in paths)}

    domains_decl, node_semantics, manual_nodes = load_manual(manual_dir)

    # 域内节点 id 集合（域文件显式声明成员，M1 只生成 manual 覆盖到的域）
    domain_nodes: dict[str, str] = {}
    pipelines: list[dict] = []
    domains: list[dict] = []
    for d in domains_decl:
        dom = d.get("domain")
        if not isinstance(dom, dict) or "id" not in dom:
            errors.append(f"{d.get('_source_file')}: 缺 domain.id")
            continue
        domains.append(dom)
        for nid in d.get("nodes", []):
            domain_nodes[nid] = dom["id"]
        for pl in d.get("pipelines", []):
            pipelines.append(pl)

    nodes: dict[str, dict] = {}
    # CLI 节点：仅生成"域声明 + manual 语义存在"的命令（manual 缺失的叶子命令
    # 在 M1 不生成；M2+ 桥模式由 /catalog 补齐——设计文档 §9.4）
    for nid, sem in node_semantics.items():
        command_path = nid.replace(".", " ")
        domain = domain_nodes.get(nid)
        if domain is None:
            errors.append(f"manual/{nid}.json: 未被任何 _domain.<域>.json 声明")
            continue
        if command_path not in leaves:
            errors.append(f"manual/{nid}.json: 命令 {command_path!r} 不在内省结果中"
                          f"（参数漂移？请核对 tool --help）")
            continue
        node = _build_cli_node(command_path, commands[command_path], tool_cmd,
                               domain, errors)
        _merge_manual_node(node, sem, errors)
        nodes[nid] = node

    # manual 型节点（会话评/人工评等）
    for nid, mn in manual_nodes.items():
        domain = domain_nodes.get(nid)
        if domain is None:
            errors.append(f"_domain 声明的 manual 节点 {nid} 未列入 nodes 成员")
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
        _validate_manual_node({**node, **mn}, f"manual_nodes.{nid}", errors)
        nodes[nid] = node

    # 自检
    for node in nodes.values():
        _check_node(node, errors)
    _check_presets(pipelines, nodes, errors)
    if tool_version and not isinstance(tool_version, str):
        errors.append("tool_version 须为字符串")

    if errors:
        raise BuildError("nodes.json 生成失败，共 %d 个问题：\n  - %s"
                         % (len(errors), "\n  - ".join(errors)))

    # hosts.toml 档位快照（M4-03）：跑 discover --show-config 捕获原样文本；
    # 用 --python -m skillverify（与内省同源，不依赖 PATH）；失败不算构建
    # 失败（页面隐藏面板），但打 warning 到 stderr
    hosts_panel: dict | None = None
    try:
        cmd = [python_exe, "-m", "skillverify"]
        proc = subprocess.run(cmd + ["discover", "--show-config"], cwd=str(repo_root),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60)
        if proc.returncode == 0 and proc.stdout.strip():
            hosts_panel = {
                "captured_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "source": "skillverify discover --show-config（构建时原样捕获）",
                # 仓库绝对路径就地归一化为 <ROOT>：nodes.json 是进 git 的产物，
                # 必须跨机器字节一致——烘着构建机的盘符路径，任何其他机器上
                # 重新生成都会对不上守卫（跨机器确定性缺陷，2026-10-12 实测抓出）
                "text": proc.stdout.replace(str(repo_root), "<ROOT>"),
            }
        else:
            print(f"warning: discover --show-config 退出 {proc.returncode}，"
                  f"hosts 档位面板将隐藏；stderr: {proc.stderr[:200]}", file=sys.stderr)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"warning: 捕获 hosts 档位失败（面板隐藏）: {exc}", file=sys.stderr)

    return {
        "schema": SCHEMA,
        "tool_version": tool_version,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "domains": domains,
        "pipelines": pipelines,
        "nodes": nodes,
        "hosts_panel": hosts_panel,
    }


def write_json(payload: dict, out_path: Path) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Windows 上显式 LF（格式纪律：UTF-8 + LF）
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve()
    repo_root_default = here.parent.parent
    ap = argparse.ArgumentParser(
        prog="build_nodes.py",
        description="生成 console/nodes.json：内省机械层 + manual 语义层合并（冲突即失败）",
    )
    ap.add_argument("--python", default=sys.executable,
                    help="内省用解释器（默认当前解释器）")
    ap.add_argument("--tool-cmd", default="skillverify",
                    help="skillverify 调用链（存入 nodes.json 的 cli.argv 前缀；"
                         "默认 skillverify）")
    ap.add_argument("--out", default=str(repo_root_default / "console" / "nodes.json"),
                    help="输出路径（默认 console/nodes.json）")
    ap.add_argument("--manual-dir", default=str(repo_root_default / "console" / "manual"),
                    help="语义层目录（默认 console/manual）")
    args = ap.parse_args(argv)

    repo_root = here.parent.parent
    import shlex
    tool_cmd = shlex.split(args.tool_cmd)

    try:
        payload = build(repo_root, args.python, tool_cmd,
                        Path(args.out), Path(args.manual_dir))
    except BuildError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"build_nodes: 未预期错误：{exc}", file=sys.stderr)
        return 1

    write_json(payload, Path(args.out))
    n_cli = sum(1 for n in payload["nodes"].values() if n["node_type"] == "cli")
    n_manual = len(payload["nodes"]) - n_cli
    print(f"nodes.json 已生成：{args.out}（cli 节点 {n_cli}，manual 节点 {n_manual}，"
          f"工具版本 {payload['tool_version']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
