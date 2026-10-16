"""console/nodes.json 防漂移守卫（操作台；维护流程见 console/README.md）。

重新跑 console/build_nodes.py 生成一份 nodes.json 到临时目录，
与仓库内提交的 console/nodes.json 做「归一化对比」（剔除 generated_at
时间戳）。不一致 → FAIL 并逐字段打印差异路径——防「改了 manual/ 语义层
或 skillverify 参数面、忘了重建产物」的漂移。

独立可跑（与仓库其他套件同构：_passed/_failed + main()，可挂 run_all.py）：

    python tests/test_console_consistency.py
    python -m tests.test_console_consistency

退出码：0 = 一致；1 = 有差异或生成失败。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skillverify.tmpdir import temp_dir  # 仓库约定：临时目录一律走 tmpdir.py

ROOT = Path(__file__).resolve().parent.parent
CONSOLE = ROOT / "console"
COMMITTED = CONSOLE / "nodes.json"

_passed: list[str] = []
_failed: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        _passed.append(name)
        print(f"PASS {name}")
    else:
        _failed.append(name)
        print(f"FAIL {name}" + (f"：{detail}" if detail else ""))


def _norm(payload: dict) -> dict:
    """归一化：剔除构建时间戳与 hosts_panel 的机器特定路径（每次构建必然
    不同或不跨机器稳定，不参与对比）。"""
    data = json.loads(json.dumps(payload, ensure_ascii=False))
    data.pop("generated_at", None)
    hp = data.get("hosts_panel")
    if isinstance(hp, dict):
        hp.pop("captured_at", None)
        if isinstance(hp.get("text"), str):
            # 分隔符也归一：判据不该依赖"在哪台机器上重生成"（Windows 出 `\`，
            # Linux 出 `/`；不归一就会变成"只有 CI 会红、本地永远绿"）。
            hp["text"] = hp["text"].replace(str(ROOT), "<ROOT>").replace("\\", "/")
    return data


def _diff(a, b, path: str = "$") -> list[str]:
    """递归差异：a = 重新生成结果（期望），b = 仓库产物（实际）。"""
    out: list[str] = []
    if type(a) is not type(b):
        out.append(f"{path}: 期望 {type(a).__name__}，实际 {type(b).__name__}")
    elif isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a:
                out.append(f"{path}.{key}: 仓库产物多出的键")
            elif key not in b:
                out.append(f"{path}.{key}: 仓库产物缺失的键（重新生成结果有）")
            else:
                out.extend(_diff(a[key], b[key], f"{path}.{key}"))
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{path}: 期望长度 {len(a)}，实际 {len(b)}")
        for i in range(min(len(a), len(b))):
            out.extend(_diff(a[i], b[i], f"{path}[{i}]"))
    elif a != b:
        out.append(f"{path}: 期望 {a!r}，实际 {b!r}")
    return out


# --------------------------------------------------------------------------- #
# 执行桥的来源闸（2026-10-14 全库检查开出的缺陷）
# --------------------------------------------------------------------------- #
def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _http(url: str, headers: dict | None = None, data: bytes | None = None,
          timeout: float = 5.0) -> tuple[int, dict, bytes]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def run_bridge_origin_guard() -> None:
    """桥的来源/Host 闸：**真实起桥 + 真实发请求**。

    为什么必须端到端：桥会替人执行命令（白名单里就有 `evals --run-with` /
    `review run --runner` 这类命令串参数），不设闸时"浏览器里任意一个网页"都能让它跑东西。
    只测白名单函数的返回值证明不了这件事（那是"测夹具"）。
    """
    import time

    print("[test_bridge_origin_guard]")
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, str(CONSOLE / "serve_bridge.py"),
         "--tool-cmd", f'"{sys.executable}" -m skillverify',
         "--python", sys.executable, "--port", str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        cwd=str(ROOT))
    try:
        ready = False
        deadline = time.time() + 60
        while time.time() < deadline and proc.poll() is None:
            try:
                if _http(base + "/health", timeout=2.0)[0] == 200:
                    ready = True
                    break
            except Exception:
                time.sleep(0.5)
        detail = ""
        if not ready:
            detail = (proc.stderr.read() if proc.poll() is not None else "60s 未就绪")[:300]
        _check("执行桥能起来（端到端前提）", ready, detail)
        if not ready:
            return

        code, _h, _b = _http(base + "/health")
        _check("无 Origin 的请求放行（curl / 脚本）", code == 200, f"实得 {code}")

        code, hdr, _b = _http(base + "/health", {"Origin": "null"})
        _check("Origin: null（file:// 打开的操作台）放行且回显 ACAO",
               code == 200 and hdr.get("Access-Control-Allow-Origin") == "null",
               f"实得 code={code} ACAO={hdr.get('Access-Control-Allow-Origin')!r}")

        code, hdr, _b = _http(base + "/health", {"Origin": "https://evil.example"})
        _check("陌生来源 403 且不回显 ACAO（浏览器读不到响应）",
               code == 403 and not hdr.get("Access-Control-Allow-Origin"),
               f"实得 code={code} ACAO={hdr.get('Access-Control-Allow-Origin')!r}")

        code, _h, _b = _http(base + "/health", {"Host": "evil.example"})
        _check("Host 非回环 403（挡 DNS rebinding）", code == 403, f"实得 {code}")

        code, _h, _b = _http(base + "/run",
                             {"Content-Type": "application/json",
                              "Origin": "https://evil.example"},
                             data=json.dumps({"node": "lint", "args": {}}).encode("utf-8"))
        _check("陌生来源的 /run 被 403 挡住（连门都进不去）", code == 403, f"实得 {code}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


# --------------------------------------------------------------------------- #
# manual 里手抄的数字 / index.html 内联快照（2026-10-14 全库检查抓出的两处无守卫）
# --------------------------------------------------------------------------- #
def run_manual_numbers() -> None:
    """`manual/review.prompts.json` 里手抄的提示词数字必须与 `data/review-prompts.json` 对账。

    manual 是**人工语义层**（人写的"这个命令到底干什么"），里面写着"32 条（旧体系 29 +
    新增 W-17/R-03/E-11）""阻断项共 4 条""⚑ 需双人独立复核 8 条""D 1 · W 17 · E 11 · R 3"——
    这些都是**从代码里能算出来的事实**，抄在文档里没有守卫就会漂（改提示词的人不会想起来）。
    """
    import re

    from skillverify.review import load_catalog

    print("[test_manual_numbers]")
    cat = load_catalog()
    total = len(cat)
    new_ids = sorted(p.id for p in cat if (p.legacy_source or "").startswith("本项目新增"))
    legacy = total - len(new_ids)
    from collections import Counter

    fam = Counter(p.family for p in cat)
    blocking = sorted(p.id for p in cat if p.blocking)
    dual = sorted(p.id for p in cat if p.raw.get("dual"))

    text = (CONSOLE / "manual" / "review.prompts.json").read_text(encoding="utf-8")
    got_total = re.search(r"(\d+) 条（旧体系 (\d+)", text)
    _check("manual 写的提示词总数 = 目录事实",
           bool(got_total) and int(got_total.group(1)) == total,
           f"manual {got_total.groups() if got_total else None} vs 实际 {total}/{legacy}")

    def _ids(pattern: str) -> set[str]:
        m = re.search(pattern, text)
        return set(m.group(1).split("/")) if m else set()

    # 注意：模式串先绑到变量再用进 f-string——**f-string 表达式里不许出现反斜杠**
    # （PEP 701 是 Python 3.12 才放开的；本机 3.13 绿、CI 的 3.11 直接 SyntaxError，
    # 实测栽过一次：「本机独有版本」这类坑，见 AGENTS §五.15）。
    pat_new = r"新增 ([WERD]-\d+(?:/[WERD]-\d+)*)"
    got_new = sorted(_ids(pat_new))
    _check("manual 列出的新增提示词 id = 目录事实",
           _ids(pat_new) == set(new_ids), f"manual {got_new} vs 实际 {new_ids}")
    pat_block = r"阻断项共 \d+ 条（([WERD]-\d+(?:/[WERD]-\d+)*)"
    got_block = sorted(_ids(pat_block))
    _check("manual 列出的阻断项 = 目录事实",
           _ids(pat_block) == set(blocking), f"manual {got_block} vs {blocking}")
    pat_dual = r"双人独立复核的项共 \d+ 条（([WERD]-\d+(?:/[WERD]-\d+)*)"
    got_dual = sorted(_ids(pat_dual))
    _check("manual 列出的双人独立复核项 = 目录事实（raw.dual）",
           _ids(pat_dual) == set(dual), f"manual {got_dual} vs {dual}")
    m_fam = re.search(r"D 设计期 (\d+) · W 编写期 (\d+) · E 测试期 (\d+) · R 运行期 (\d+)", text)
    want_fam = (fam.get("D", 0), fam.get("W", 0), fam.get("E", 0), fam.get("R", 0))
    _check("manual 写的家族分布 = 目录事实",
           bool(m_fam) and tuple(int(x) for x in m_fam.groups()) == want_fam,
           f"manual {m_fam.groups() if m_fam else None} vs 实际 {want_fam}")


def run_inline_snapshot() -> None:
    """`app/index.html` 里内联的 `nodes-data` 必须与 `nodes.json` 一致。

    生成器把 nodes.json **内联**进 index.html（页面要能直接 file:// 打开、不靠 fetch）。
    原来的守卫只比 `nodes.json`，于是"只改了 nodes.json 忘了重跑 build.py"这一半没人查。
    """
    import re

    print("[test_inline_snapshot]")
    html = (CONSOLE / "app" / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<script type="application/json" id="nodes-data">(.*?)</script>', html, re.S)
    if m is None:
        _check("index.html 里有内联的 nodes-data", False, "没找到 <script id=\"nodes-data\">")
        return
    _check("index.html 里有内联的 nodes-data", True)
    inline = json.loads(m.group(1))
    committed = json.loads(COMMITTED.read_text(encoding="utf-8"))
    same = _norm(inline) == _norm(committed)
    detail = "" if same else "；".join(_diff(_norm(committed), _norm(inline))[:5])
    _check("index.html 内联数据与 nodes.json 一致（除生成时间戳）", same, detail)


def run_history_limit_clamp() -> None:
    """`/history?limit=` 的夹取：**下界也必须夹**（`lines[-0:]` 会返回全部记录）。

    这条是"文档复审带出来的代码缺陷"：桥 API 文档写"默认 50，上限 1000"，读代码发现
    `min(int(...), 1000)` 只夹了上界——`limit=0` 时 `_read_history` 的 `lines[-limit:]`
    变成 `lines[0:]`，审计全量被吐出来（负数则是去掉开头 N 条）。抽成 `_clamp_limit()` 后可直接钉。
    """
    import sys as _sys

    print("[test_history_limit_clamp]")
    _sys.path.insert(0, str(CONSOLE))
    try:
        import serve_bridge as bridge           # 纯标准库，可安全导入
    except Exception as exc:                    # noqa: BLE001
        _check("能导入 serve_bridge（纯标准库）", False, f"{type(exc).__name__}: {exc}")
        return
    cases = [(None, 50), ("5", 5), ("0", 1), ("-3", 1), ("99999", 1000), ("abc", 50),
             ("", 50), ("1000", 1000), ("1", 1)]
    bad = [(raw, got, want) for raw, want in cases
           for got in [bridge._clamp_limit(raw)] if got != want]
    _check("_clamp_limit 把 limit 夹在 1..1000（含 0 / 负数 / 非法值）", not bad, f"不符: {bad}")
    # 反向自检：不夹下界的老写法在 limit=0 时会命中全部记录
    lines = ["a\n", "b\n", "c\n"]
    _check("反向自检：lines[-0:] 确实是全部记录（这就是原缺陷）",
           lines[-0:] == lines and lines[-1:] == ["c\n"])


def main() -> int:
    if not COMMITTED.exists():
        _check("仓库产物存在", False, f"{COMMITTED} 不存在——请先 python console/build_nodes.py 并提交")
        return 1

    # 1. 重新生成到临时目录（不触碰仓库文件）
    with temp_dir("console-guard-") as td:
        out_path = Path(td) / "nodes.regenerated.json"
        proc = subprocess.run(
            [sys.executable, str(CONSOLE / "build_nodes.py"), "--out", str(out_path)],
            capture_output=True, text=True, encoding="utf-8", timeout=300,
            cwd=str(ROOT),
        )
        _check("生成器可运行", proc.returncode == 0,
               (proc.stderr or "").strip()[:2000])
        if proc.returncode != 0:
            return 1
        regen = json.loads(out_path.read_text(encoding="utf-8"))

    # 2. 仓库产物可解析
    try:
        committed = json.loads(COMMITTED.read_text(encoding="utf-8"))
        _check("仓库产物是合法 JSON", True)
    except json.JSONDecodeError as exc:
        _check("仓库产物是合法 JSON", False, str(exc))
        return 1

    # 3. 归一化对比
    diffs = _diff(_norm(regen), _norm(committed))
    _check("nodes.json 与重新生成结果一致（除 generated_at）", not diffs,
           f"共 {len(diffs)} 处差异" if diffs else "")
    for line in diffs[:20]:
        print(f"  - {line}")
    if len(diffs) > 20:
        print(f"  - ……另有 {len(diffs) - 20} 处差异未展开")

    if diffs:
        print("\n修复方式：python console/build_nodes.py && python console/build.py，"
              "过目 git diff 后把 nodes.json 与 manual/ 同一提交。")

    # 3b. 产物里**不许烘进平台分隔符**。这是 2026-10-12 那次连红的根因：
    #     Windows 上生成的 `<ROOT>\skillverify\data\hosts.toml` 到 Linux 重生成变成 `/`，
    #     守卫只在 CI 红、本地永远绿。这条断言**在本机就能红**，不靠 CI 才发现。
    hp_text = ((committed.get("hosts_panel") or {}).get("text") or "")
    _check("hosts_panel 不含平台分隔符（跨机字节一致）",
           "<ROOT>\\" not in hp_text and "<HOME>\\" not in hp_text,
           f"发现反斜杠路径: {[ln for ln in hp_text.splitlines() if chr(92) in ln][:2]}")

    # 4. lint 规则目录与源码对账（M4-01）：manual/lint.json 的 rules 快照
    #    必须与 skillverify.lint.RULES 的 id 集合一致——lint 加规则后忘同步
    #    manual 就在这里红
    try:
        from skillverify.lint import RULES as LINT_RULES

        lint_doc_path = CONSOLE / "manual" / "lint.json"
        lint_doc = json.loads(lint_doc_path.read_text(encoding="utf-8"))
        manual_ids = [r.get("rid") for r in lint_doc.get("rules", [])]
        src_ids = sorted(LINT_RULES)
        manual_sorted = sorted(x for x in manual_ids if x)
        _check("lint 规则目录与源码 RULES 一致", manual_sorted == src_ids,
               f"manual 缺 {sorted(set(src_ids) - set(manual_sorted))} "
               f"多 {sorted(set(manual_sorted) - set(src_ids))}"
               if manual_sorted != src_ids else "")
    except (OSError, json.JSONDecodeError, ImportError) as exc:
        _check("lint 规则目录与源码 RULES 一致", False, f"无法对账: {exc}")

    # 5. describe 协议与 argparse 遍历两条数据源等价：内省脚本
    #    auto 模式优先吃 describe 契约——它必须与兜底的 argparse 遍历产出
    #    完全一致，否则"切数据源"会悄悄改变 nodes.json 的内容。
    proc_d = subprocess.run(
        [sys.executable, str(CONSOLE / "introspect.py"), "--data-source", "describe"],
        capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=str(ROOT),
    )
    proc_a = subprocess.run(
        [sys.executable, str(CONSOLE / "introspect.py"), "--data-source", "argparse"],
        capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=str(ROOT),
    )
    ok5 = proc_d.returncode == 0 and proc_a.returncode == 0
    detail5 = ""
    if ok5:
        diffs5 = _diff(json.loads(proc_d.stdout), json.loads(proc_a.stdout))
        ok5 = not diffs5
        detail5 = f"两数据源 {len(diffs5)} 处差异" if diffs5 else ""
        for line in diffs5[:5]:
            print(f"  - {line}")
    else:
        detail5 = ((proc_d.stderr or "") + (proc_a.stderr or "")).strip()[:500]
    _check("describe 契约与 argparse 遍历等价（内省数据源切换零漂移）", ok5, detail5)

    # 6. 执行桥的来源闸（真实起桥 + 真实发请求）
    run_bridge_origin_guard()

    # 7. manual 手抄数字 + index.html 内联快照
    run_history_limit_clamp()
    run_manual_numbers()
    run_inline_snapshot()

    print(f"\n合计: PASS={len(_passed)} FAIL={len(_failed)}")
    return 0 if not _failed else 1


if __name__ == "__main__":
    sys.exit(main())
