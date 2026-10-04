#!/usr/bin/env python3
"""test_local_gate.py — local_gate.py 固化回归单测（v1.2 二评处置后对齐族惯例）。

只覆盖快速路径（无参契约/--timeout 校验/tail/_flat/发现函数/导入兜底/ev 压平）
——刻意不跑全量门禁（--run 会递归触发 LG-1/LG-2 自引用），与 local_gate 不入
LG-2 冒烟清单的豁免口径互为镜像。风格沿工具族 fail()/ok() 惯例（fail-fast、
消息明确、python -O 下不假阳性），只读，无系统副作用。

用法: python tests/test_local_gate.py    # 全过打印 ALL PASS，失败非零退出
"""
from __future__ import annotations

import builtins
import importlib.util
import subprocess
import sys
import types
import unittest.mock as mock
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
LG = TOOLS / "local_gate.py"
passed: list[str] = []


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ok(msg: str) -> None:
    passed.append(msg)
    print(f"  PASS {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")
    sys.exit(1)


lg = load("local_gate_under_test", LG)


def run_gate(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(LG), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=60, stdin=subprocess.DEVNULL)


# ── 1. 无参契约（C2）+ --tests-only 计划口径（同一"缺 --run"分支，合并断言）──
def test_no_run_contract_and_plans():
    p = run_gate()
    if p.returncode != 1:
        fail(f"无参调用应 exit 1，实为 {p.returncode}")
    if not ("用法" in p.stderr and "执行计划" in p.stderr and "--run" in p.stderr):
        fail(f"无参 stderr 应含 用法/执行计划/--run，实为 {p.stderr[:120]!r}")
    p2 = run_gate("--tests-only")
    if p2.returncode != 1:
        fail(f"--tests-only 无 --run 应 exit 1，实为 {p2.returncode}")
    if "LG-1" not in p2.stderr or "LG-2" in p2.stderr:
        fail(f"--tests-only 计划应含 LG-1 不含 LG-2，实为 {p2.stderr[:160]!r}")
    ok("无参 exit 1 带用法+执行计划（C2 契约）；--tests-only 计划仅 LG-1")


# ── 2. --out 缺 --run：消息须点破 --out 不是执行开关 ──
def test_out_without_run_hint():
    p = run_gate("--out", "x.md")
    if p.returncode != 1 or "--out 只是报告" not in p.stderr:
        fail(f"应 exit 1 且点破 --out 非执行开关，实为 exit={p.returncode} "
             f"stderr={p.stderr[:120]!r}")
    ok("--out 无 --run 时消息点破报告路径≠执行开关")


# ── 3. --timeout <= 0 校验 ──
def test_timeout_validation():
    for bad in ("0", "-1"):
        p = run_gate("--run", "--tests-only", "--timeout", bad)
        if p.returncode != 1 or "正整数" not in p.stderr:
            fail(f"--timeout {bad} 应 exit 1 带正整数提示（不进全量跑），"
                 f"实为 exit={p.returncode} stderr={p.stderr[:100]!r}")
    ok("--timeout 0/-1 → exit 1 带正整数提示")


# ── 4. tail 边界：空/单行/多行截尾/管道符压平 ──
def test_tail():
    cases = [("", "(无输出)"), ("a", "a"),
             ("l1\nl2\nl3\nl4", "l2 ⏎ l3 ⏎ l4"),   # 尾部 3 行
             ("a|b\nc", "a｜b ⏎ c")]                # 管道符压平
    for src, want in cases:
        got = lg.tail(src)
        if got != want:
            fail(f"tail({src!r}) 应为 {want!r}，实为 {got!r}")
    ok("tail 空串/单行/截尾 3 行/管道符压平")


# ── 5. discover_tests/discover_scripts 动态清单（软化断言——只依赖自引用）──
def test_discover():
    tests = lg.discover_tests()
    names = {t.name for t in tests}
    if "test_local_gate.py" not in names:
        fail(f"自引用测试须在 LG-1 清单，实为 {sorted(names)}")
    if not tests or not all(t.name.startswith("test_") and t.exists() for t in tests):
        fail("discover_tests 应只返回存在的 test_*.py 且非空")
    snames = {s.name for s in lg.discover_scripts()}
    if "local_gate.py" in snames:
        fail("本工具不得入 LG-2 清单（防递归自引用）")
    if "smoke_runner.py" not in snames:
        fail("smoke_runner 应在 LG-2 清单（C2 契约路径覆盖）")
    ok("discover_tests 含自引用且全为存在文件 + discover_scripts 排自身含 smoke_runner")


# ── 6. run_smoke 导入失败兜底：FAIL 行而非崩溃（mock 注入，不依赖 cwd/路径）──
def test_import_fail_guard():
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "smoke_runner":
            raise ImportError("mocked: 注入导入失败")
        return real_import(name, *args, **kwargs)

    with mock.patch.object(builtins, "__import__", side_effect=fake_import):
        rows, n = lg.run_smoke([TOOLS / "no-such.py"], 10)
    if n != 1:
        fail(f"导入失败也应返回清单数（计划口径一致），实为 n={n}")
    if not rows or rows[0]["level"] != "FAIL" or "导入失败" not in rows[0]["ev"]:
        fail(f"导入失败应返 FAIL 行含'导入失败'，实为 {rows!r}")
    ok("smoke_runner 导入失败 → LG-2 FAIL 行且 n=清单数（语义不分裂）")


# ── 7. LG-2 证据压平（行为验证：假模块注入，管道符+换行均压平）──
def test_ev_flat():
    fake = types.ModuleType("smoke_runner")
    fake.smoke_one = lambda s, t: [dict(cid="C1", level="PASS", ev="a|b\rc\nd|e")]
    saved = sys.modules.get("smoke_runner")
    sys.modules["smoke_runner"] = fake
    try:
        rows, n = lg.run_smoke([TOOLS / "any.py"], 10)
    finally:
        if saved is None:
            sys.modules.pop("smoke_runner", None)
        else:
            sys.modules["smoke_runner"] = saved
    if n != 1:
        fail(f"应返回清单数 1，实为 {n}")
    want = "a｜b ⏎ c ⏎ d｜e"
    if not rows or rows[0]["ev"] != want:
        fail(f"ev 应压平为 {want!r}，实为 {rows[0]['ev']!r}" if rows else f"rows 为空")
    ok("LG-2 证据压平管道符+换行（假模块行为验证，不依赖源码形态）")


def main() -> int:
    for fn in [test_no_run_contract_and_plans, test_out_without_run_hint,
               test_timeout_validation, test_tail, test_discover,
               test_import_fail_guard, test_ev_flat]:
        print(f"[{fn.__name__}]")
        fn()
    print(f"\nALL PASS（{len(passed)} 组断言）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
