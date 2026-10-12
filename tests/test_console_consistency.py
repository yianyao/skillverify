"""console/nodes.json 防漂移守卫（操作台 M2，设计文档 §9.2）。

重新跑 console/build_nodes.py 生成一份 nodes.json 到临时目录，
与仓库内提交的 console/nodes.json 做「归一化对比」（剔除 generated_at
时间戳）。不一致 → FAIL 并逐字段打印差异路径——防「改了 manual/ 语义层
或 skillverify 参数面、忘了重建产物」的漂移（SOP 第四章 M2-3）。

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
            hp["text"] = hp["text"].replace(str(ROOT), "<ROOT>")
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

    # 5. describe 协议与 argparse 遍历两条数据源等价（EVOL-01）：内省脚本
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

    print(f"\n合计: PASS={len(_passed)} FAIL={len(_failed)}")
    return 0 if not _failed else 1


if __name__ == "__main__":
    sys.exit(main())
