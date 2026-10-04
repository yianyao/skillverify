#!/usr/bin/env python3
"""smoke_runner.py — V6 脚本冒烟套件（K 类共识：下沉 S 工具链层）。

对指定脚本逐个执行**机械可判定**的冒烟项；执行形态记 S、验证目标仍记 K（保追溯）。
语义项（--help 内容正确性）不在本套件范围，交 LLM 清单 W-14。

每个脚本执行的检查（全部为无害调用，不执行业务功能）：
  C1 --help 可运行    退出码 0 且 stdout 非空（内容正确性→W-14，另行）
  C2 无参调用         记录退出码；非零且报错含用法提示=PASS；退出 0=WARN（确认是否全可选参数）
  C3 非 TTY 不挂起    以上调用均在超时内完成（超时=FAIL 挂起）
  C4 dry-run 静态检测 源码含 --dry-run/--dry_run 则记"适用，动态验证需专属用例"
  C5 --help 幂等      连跑两次 stdout 一致（幂等的机械代理；业务幂等需专属用例，另行）

用法:
    python smoke_runner.py --scripts a.py b.py            # 指定脚本
    python smoke_runner.py --scripts <目录>               # 目录下全部 .py
    python smoke_runner.py --scripts <dir> --out smoke.md # 同时落盘报告

退出码: 0=全 PASS；1=任一 FAIL；2=仅 WARN。参数错误亦统一 exit 1（_BlockArgParser，
不撞 WARN 码）。
留痕: 报告落 .verification/iteration-N/smoke.md（由调用方指定 --out 路径）。

版本: v1.1（2026-10-03 收官回填批次补 VERSION 常量+报告头版本标识；
      v1.0 建成，2026-10-03 回填 _BlockArgParser）
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

VERSION = "v1.1"
TIMEOUT_DEFAULT = 15
# P-6（收紧版）：只认用法/必需类提示，不含 error 系——任何崩溃栈（如 NameError:）
# 都不应被误判为"报错带用法"；经验证据：host_compat 曾因 "NameError:" 命中 "error:" 误判 PASS
USAGE_HINTS = ("usage:", "usage", "用法", "required", "必需", "the following arguments")


def run_py(script: Path, args: list[str], timeout: int) -> tuple[str, int, str, str, bool]:
    """返回 (标签, 退出码, stdout, stderr, 是否超时)。"""
    try:
        p = subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, stdin=subprocess.DEVNULL,  # 非 TTY + 无输入
        )
        return (script.name, p.returncode, p.stdout or "", p.stderr or "", False)
    except subprocess.TimeoutExpired:
        return (script.name, -1, "", "", True)


def head(s: str, n: int = 120) -> str:
    s = s.replace("\r", "").strip().replace("|", "｜").replace("\n", " ⏎ ")
    return s[:n] + ("…" if len(s) > n else "")


def smoke_one(script: Path, timeout: int) -> list[dict]:
    rows: list[dict] = []

    # C1/C3/C5 --help
    _, rc, out, err, timed_out = run_py(script, ["--help"], timeout)
    if timed_out:
        rows.append(dict(cid="C3 非 TTY 不挂起", level="FAIL", ev="--help 调用超时挂起", script=script))
        return rows
    c1 = "PASS" if (rc == 0 and out.strip()) else "FAIL"
    rows.append(dict(cid="C1 --help 可运行", level=c1, ev=f"exit={rc}, stdout={'有' if out.strip() else '空'}｜{head(out or err)}", script=script))
    rows.append(dict(cid="C3 非 TTY 不挂起", level="PASS", ev=f"--help 于 {timeout}s 内完成", script=script))

    # C5 幂等（--help 连跑两次；P-4：先区分超时，避免把挂起误诊为"输出不一致"）
    _, rc2, out2, _, to2 = run_py(script, ["--help"], timeout)
    if to2:
        c5, ev5 = "FAIL", "第二次 --help 调用超时挂起"
    elif out != out2:
        c5, ev5 = "FAIL", "两次 stdout 不一致"
    else:
        c5, ev5 = "PASS", "两次 stdout 一致"
    rows.append(dict(cid="C5 --help 幂等", level=c5, ev=ev5, script=script))

    # C2 无参调用
    _, rc0, out0, err0, to0 = run_py(script, [], timeout)
    if to0:
        rows.append(dict(cid="C2 无参调用", level="FAIL", ev="无参调用超时挂起", script=script))
    else:
        combined = (out0 + err0).lower()
        hint = any(h.lower() in combined for h in USAGE_HINTS)
        if rc0 != 0:
            c2 = "PASS" if hint else "WARN"
            ev = f"exit={rc0}, 报错{'含' if hint else '未含'}用法提示｜{head(err0 or out0)}"
        else:
            c2, ev = "WARN", f"exit=0（无参也能跑；确认是否全为可选参数）｜{head(out0)}"
        rows.append(dict(cid="C2 无参调用报错带用法", level=c2, ev=ev, script=script))

    # C4 dry-run 静态检测（S-4/2.4：先剥 docstring 再过滤行注释；只认参数定义形态——
    # argparse 的 add_argument 或 click 风格的 option（第四轮 2.4）；
    # 裸字面量正则会把 print("使用 --dry-run") 这类提示串误判为"适用"，已废弃）
    src = script.read_text(encoding="utf-8", errors="replace")
    src = re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", src)  # 剥除三引号 docstring/字符串块
    code_lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    src = "\n".join(code_lines)
    has_dry = bool(
        re.search(r"""add_argument\(\s*['"]--dry[-_]run\b""", src)
        or re.search(r"""option\(\s*['"]--dry[-_]run\b""", src)
    )
    rows.append(dict(
        cid="C4 dry-run 适用性",
        level="PASS",
        ev="源码含 dry-run 标志（动态验证需任务专属用例，不在本套件）" if has_dry else "无 dry-run 标志（不适用，如技能约定适用则人工复核）",
        script=script,
    ))
    return rows


class _BlockArgParser(argparse.ArgumentParser):
    """参数错误统一 exit 1（阻断码）——argparse 默认 exit 2 撞 WARN 码
    （naming_precheck v1.0.1 评审 5 纪律，local_gate v1.0 建成时当轮回填）。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"错误: {message}。下一步: 按用法核对参数后重试。", file=sys.stderr)
        raise SystemExit(1)


def main() -> int:
    ap = _BlockArgParser(description="V6 脚本冒烟套件（机械项）")
    ap.add_argument("--scripts", nargs="+", required=True, help="脚本文件或目录（目录取其下全部 .py）")
    ap.add_argument("--out", help="报告落盘路径（如 .verification/iteration-1/smoke.md）")
    ap.add_argument("--timeout", type=int, default=TIMEOUT_DEFAULT, help="单次调用超时秒数（默认 15）")
    a = ap.parse_args()

    scripts: list[Path] = []
    for s in a.scripts:
        p = Path(s)
        if p.is_dir():
            scripts.extend(sorted(p.glob("*.py")))
        elif p.is_file():
            scripts.append(p)
        else:
            print(f"[FAIL] 路径不存在: {p}", file=sys.stderr)
    skipped = [p.name for p in scripts if p.name == Path(__file__).name]
    scripts = [p for p in scripts if p.name not in skipped]
    if skipped:
        print(f"[提示] 已跳过 smoke_runner.py 自身（避免递归自测）: {', '.join(skipped)}")
    if not scripts:
        print("错误: 未找到任何待测脚本。下一步: 核对 --scripts 参数。", file=sys.stderr)
        return 1

    all_rows: list[dict] = []
    for s in scripts:
        all_rows.extend(smoke_one(s, a.timeout))

    has_fail = any(r["level"] == "FAIL" for r in all_rows)
    has_warn = any(r["level"] == "WARN" for r in all_rows)

    lines = [
        f"# V6 脚本冒烟报告（smoke_runner.py {VERSION}）",
        "",
        f"- 待测脚本: {len(scripts)} 个（{', '.join(p.name for p in scripts)}）",
        f"- 口径: 机械项脚本判定；--help 内容正确性（语义）留待 W-14；执行形态记 S，验证目标记 K（V6）",
        f"- 总结论: {'FAIL（存在阻断项）' if has_fail else ('WARN（有告警，人工书面评估）' if has_warn else 'PASS')}",
        "",
        "| 脚本 | 检查项 | 结论 | 证据 |",
        "|---|---|---|---|",
    ]
    for r in all_rows:
        lines.append(f"| {r['script'].name} | {r['cid']} | {r['level']} | {r['ev']} |")
    lines += [
        "",
        "> 本报告为机械门结果；放行与否由人工签认，[M] 级 FAIL 不得自动放行。",
    ]
    report = "\n".join(lines) + "\n"

    print(report)
    if a.out:
        outp = Path(a.out)
        try:
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text(report, encoding="utf-8", newline="\n")
            print(f"[已落盘] {outp}")
        except OSError as e:
            print(f"[FAIL] 报告落盘失败: {outp} — {e}。下一步: 检查路径权限或改用其他 --out 路径。",
                  file=sys.stderr)
            return 1

    return 1 if has_fail else (2 if has_warn else 0)


if __name__ == "__main__":
    sys.exit(main())
