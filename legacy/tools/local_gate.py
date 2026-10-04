#!/usr/bin/env python3
"""local_gate.py — 本地回归门禁（待办 C：S/T 的执行机制固化）。

把工具族回归固化为一键门禁，任何工具改动后先过本门再提交/同步双盘。
两项检查（编号为工具本地编号，V1–V29 已占用）：

  LG-1 单测回归    tests/test_*.py 全部逐个子进程运行（动态 glob——未来新增
                   测试文件自动纳入，无需改本工具）；exit 0=PASS，非 0=FAIL，
                   证据取输出尾部
  LG-2 V6 冒烟     复用 smoke_runner.smoke_one 对工具目录全部 .py 冒烟
                   （C1–C5；排除本工具自身，防自引用）

用法:
    python local_gate.py --run                 # 全量门禁（LG-1 + LG-2）
    python local_gate.py --run --tests-only    # 仅 LG-1 快速回路
    python local_gate.py --run --out .verification/iteration-N/local-gate.md

退出码: 0=全 PASS；1=任一 FAIL（阻断——不得同步双盘/不得提交）；2=仅 WARN。
覆盖口径: local_gate 自身由 tests/test_local_gate.py 覆盖快速路径（无参契约/
--timeout 校验/tail/发现函数/导入兜底），刻意不跑全量门禁（防 LG-1/LG-2 递归
自引用，故不入 LG-2 冒烟清单）；smoke_runner 无专属单测，由 LG-2 冒烟覆盖
（其无参 C2 契约路径在册）。

口径声明:
- 单测以子进程隔离运行——任一套件内部 sys.exit 不影响后续套件
- 门禁只证"回归未破"，不替代验证批次的实弹（三技能扫描属批次动作，另行）
- A1 实检口径：环境无 agentskills 时 check_skill 单测走 SKIP 路径，本门禁
  结果不受 PATH 影响（单测夹具不依赖官方 CLI）

版本: v1.2（2026-10-03 二评 6 条处置：返回值语义统一（导入失败也返清单数）+
          _flat 证据压平收编（管道符+换行，行为验证取代源码断言）+ 测试改
          fail/ok 族惯例（mock 注入取代全局变量 hack）；v1.1 同日首评 8 条、
          v1.0 同日建成，待办 C——S/T 执行机制固化）
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

VERSION = "v1.2"
SELF = Path(__file__).resolve()
TOOLS_DIR = SELF.parent
TESTS_DIR = TOOLS_DIR / "tests"
TAIL_LINES = 3  # 单测证据取输出尾部行数


class _BlockArgParser(argparse.ArgumentParser):
    """参数错误统一 exit 1（阻断码）——argparse 默认 exit 2 撞 WARN 码
    （naming_precheck v1.0.1 评审 5 纪律，全工具对齐口径）。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"错误: {message}。下一步: 按用法核对参数后重试。", file=sys.stderr)
        raise SystemExit(1)


def tail(text: str, n: int = TAIL_LINES) -> str:
    """取非空尾部 n 行，压平管道符。"""
    lines = [ln.strip().replace("|", "｜") for ln in text.splitlines() if ln.strip()]
    return " ⏎ ".join(lines[-n:]) if lines else "(无输出)"


def _flat(text: str) -> str:
    """LG-2 证据压平：管道符→全角、各类换行（\\r\\n/\\r/\\n）→ ⏎（与 tail 同口径）。

    框架异常消息可含多行——只替换管道符不够，换行同样会破坏表格行；
    \\r 单独出现（旧式行尾）也须作分隔而非删除，否则前后文粘连。
    """
    return (str(text).replace("|", "｜")
            .replace("\r\n", "\n").replace("\r", "\n")
            .replace("\n", " ⏎ "))


def discover_tests() -> list[Path]:
    """LG-1 测试清单：tests/test_*.py 动态发现，按名排序保证稳定顺序。"""
    return sorted(TESTS_DIR.glob("test_*.py"))


def discover_scripts() -> list[Path]:
    """LG-2 冒烟清单：tools/*.py 排除本工具自身与 tests/。"""
    return sorted(p for p in TOOLS_DIR.glob("*.py") if p.resolve() != SELF)


def run_tests(py: list[Path], timeout: int) -> list[dict]:
    """LG-1：逐套子进程运行。返回行 dict（vid/title/level/ev）。"""
    rows: list[dict] = []
    for t in py:
        try:
            p = subprocess.run(
                [sys.executable, str(t)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout, stdin=subprocess.DEVNULL,
            )
            out = (p.stdout or "") + (p.stderr or "")
            if p.returncode == 0:
                rows.append(dict(vid="LG-1", title=f"单测 {t.name}", level="PASS",
                                 ev=tail(out)))
            else:
                rows.append(dict(vid="LG-1", title=f"单测 {t.name}", level="FAIL",
                                 ev=f"exit={p.returncode}: {tail(out)}"))
        except subprocess.TimeoutExpired:
            rows.append(dict(vid="LG-1", title=f"单测 {t.name}", level="FAIL",
                             ev=f"超时（>{timeout}s）——疑似挂起"))
        except OSError as e:
            rows.append(dict(vid="LG-1", title=f"单测 {t.name}", level="FAIL",
                             ev=f"启动失败（{e}）"))
    return rows


def run_smoke(scripts: list[Path], timeout: int) -> tuple[list[dict], int]:
    """LG-2：复用 smoke_runner.smoke_one 逐脚本冒烟。返回 (行, 脚本数)。

    脚本数恒为纳入冒烟清单的脚本数（与执行计划口径一致）——即使
    smoke_runner 导入失败也返回清单数，实际未处理由 FAIL 行明示，
    避免报告头"0 脚本"与执行计划自相矛盾。
    ev 经 _flat 压平（管道符+换行）；smoke_runner 导入失败记 FAIL 行
    而非崩溃（覆盖缺口纪律：缺口须可见）。
    """
    sys.path.insert(0, str(TOOLS_DIR))
    try:
        import smoke_runner  # noqa: PLC0415——同目录延迟导入，保持独立可运行
    except ImportError as e:
        return [dict(vid="LG-2", title="框架导入", level="FAIL",
                     ev=f"smoke_runner 导入失败：{e}")], len(scripts)
    rows: list[dict] = []
    for s in scripts:
        try:
            for c in smoke_runner.smoke_one(s, timeout):
                rows.append(dict(vid="LG-2", title=f"{s.name}｜{c['cid']}",
                                 level=c["level"], ev=_flat(c["ev"])))
        except Exception as e:  # 冒烟框架自身异常不中断全量，记 FAIL 继续
            rows.append(dict(vid="LG-2", title=f"{s.name}｜框架异常", level="FAIL",
                             ev=_flat(f"{type(e).__name__}: {e}")))
    return rows, len(scripts)


def main() -> int:
    ap = _BlockArgParser(description="本地回归门禁（LG-1 单测 + LG-2 V6 冒烟）——工具改动后的一键回归")
    ap.add_argument("--run", action="store_true",
                    help="实际执行（必填语义——无参报错 exit 1，防长任务无参误触发）")
    ap.add_argument("--out", help="报告落盘路径（建议 .verification/iteration-N/local-gate.md）")
    ap.add_argument("--tests-only", action="store_true", help="仅跑 LG-1 单测（快速回路）")
    ap.add_argument("--timeout", type=int, default=60, help="单套单测/单脚本冒烟超时秒数（默认 60）")
    a = ap.parse_args()

    if a.timeout <= 0:
        print("错误: --timeout 须为正整数（秒）。下一步: 如 --timeout 60。",
              file=sys.stderr)
        return 1

    tests = discover_tests()
    if not tests:
        print(f"错误: {TESTS_DIR} 下未发现 test_*.py——测试目录缺失或被移动。"
              "下一步: 核对 tests/ 位置后重试。", file=sys.stderr)
        return 1

    scripts = discover_scripts()  # 一次发现，scope_plan 与 run_smoke 共享（防口径漂移）
    scope_plan = (f"LG-1 {len(tests)} 套单测（{', '.join(t.name for t in tests)}）"
                  + ("" if a.tests_only else f" + LG-2 {len(scripts)} 脚本 V6 冒烟"))
    if not a.run:
        out_hint = "（--out 只是报告落盘路径，执行仍需 --run）" if a.out else ""
        print(f"错误: 缺 --run 确认旗标{out_hint}"
              f"（无参不执行——防长任务无参误触发，冒烟 C2 契约）。"
              f"用法: python local_gate.py --run [--tests-only] [--out 报告路径]\n"
              f"执行计划: {scope_plan}", file=sys.stderr)
        return 1

    t0 = time.time()

    rows = run_tests(tests, a.timeout)
    n_scripts = 0
    if not a.tests_only:
        smoke_rows, n_scripts = run_smoke(scripts, a.timeout)
        rows += smoke_rows

    has_fail = any(r["level"] == "FAIL" for r in rows)
    has_warn = any(r["level"] == "WARN" for r in rows)
    n_pass = sum(1 for r in rows if r["level"] == "PASS")
    n_fail = sum(1 for r in rows if r["level"] == "FAIL")
    n_warn = sum(1 for r in rows if r["level"] == "WARN")
    elapsed = time.time() - t0

    verdict = ("FAIL（存在阻断项——不得同步双盘/提交，先修复后重跑）" if has_fail
               else "PASS（WARN 并存——人工复核后可放行）" if has_warn
               else "PASS（全绿）")
    scope = f"LG-1 {len(tests)} 套单测" + ("" if a.tests_only else f" + LG-2 {n_scripts} 脚本 V6 冒烟")
    print(f"\n本地回归门禁 {VERSION}｜{scope}")
    print(f"| 检查项 | 判级 | 证据 |")
    print(f"|---|---|---|")
    for r in rows:
        print(f"| {r['vid']} {r['title']} | {r['level']} | {r['ev'][:110]} |")
    print(f"\n总结论: {verdict}｜PASS={n_pass} FAIL={n_fail} WARN={n_warn}"
          f"｜耗时 {elapsed:.1f}s")

    if a.out:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="\n") as f:
            f.write(f"# 本地回归门禁报告（{VERSION}，{time.strftime('%Y-%m-%d %H:%M:%S')}）\n\n")
            f.write(f"- 范围: {scope}\n- Python: {sys.executable}\n\n")
            f.write("| 检查项 | 判级 | 证据 |\n|---|---|---|\n")
            for r in rows:
                f.write(f"| {r['vid']} {r['title']} | {r['level']} | {r['ev']} |\n")
            f.write(f"\n**总结论: {verdict}**｜PASS={n_pass} FAIL={n_fail} WARN={n_warn}｜耗时 {elapsed:.1f}s\n")
        print(f"报告已落盘: {out}")

    return 1 if has_fail else (2 if has_warn else 0)


if __name__ == "__main__":
    sys.exit(main())
