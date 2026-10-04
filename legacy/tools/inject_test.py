#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inject_test.py — V23 fail-loud 注入测试（人工清单 M0-3，单宿主口径）。

对技能临时副本注入非法 frontmatter，验证解析器/宿主**报错而非静默跳过**
（fail-loud 纪律）；原目录全程只读。§人工评审检查清单 M0-3/V23。

检查项:
  V23-0 对照组       解析器对未修改临时副本应通过（零退出）——失败=环境/解析器问题，
                     注入用例转 SKIP（注入结果失去可解释性）
  V23-1 非法 YAML    frontmatter 内注入 tab 缩进坏行（YAML 禁 tab）
  V23-2 缺必填键     剥除 name/description 顶层键**及其整块**（折叠标量 ">" 的
                     缩进续行一并删——产物语义恒为"缺必填键"而非"孤续行 YAML 结构错"）
  V23-3 name 违规    name 改 Bad_Name（违 ^[a-z0-9]+(-[a-z0-9]+)*$）
  V23-4 原目录未触碰 全文件 SHA256 清单执行前后一致（原目录只读自证）

每个注入副本正文尾部追加标记行 V23INJECT——供 --parser-cmd 自定义解析器
区分对照组/注入副本（官方解析器不受影响，注释/正文不影响其判定）。

解析器定位: 默认复用 check_skill.find_official_cli（官方入口 agentskills 优先，
npm skills-ref 第三方占用警示同 A1），并按 A1 同款调用形态追加 "validate"
子命令（agentskills 为命令组，裸路径会被当作未知子命令拒识）；未装 →
V23-0..3 SKIP（COV 纪律：SKIP 不计警告，覆盖缺口须可见）；V23-4 不依赖
解析器仍实检。
--parser-cmd 覆盖: 完整命令行字符串（shlex.split 拆分），尾元自动追加
<临时技能目录>——默认路径等价 --parser-cmd "<cli> validate"；测试经此
注入假解析器，不依赖外部 CLI。

用法: python inject_test.py <skill_dir> [--parser-cmd "cmd args..."] [--timeout 秒] [--out 报告路径]
退出码: 0=全 PASS；1=任一 FAIL；2=仅 WARN/SKIP（含解析器缺位）。参数错误 exit 1 带用法。
注: SKIP 计 exit 2——与 check_skill A1 SKIP 计 exit 0 的差异为设计决策：
    A1 SKIP 有 A2–A11 等效覆盖，本工具 SKIP 表示"注入未跑"的真实覆盖缺口，须触发提醒。

版本: v1.0.3（2026-10-03 复检二）— main 前置读 SKILL.md 补 try/except OSError
      （.is_file() 过但不可读→友好提示 exit 1，对齐族惯例）；v1.0.2 复检——
      SKILL.md 读码 utf-8-sig 双点/删死常量 NAME_PAT；v1.0.1 三评 8 条处置；
      v1.0 2026-10-03 建成
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VERSION = "v1.0.3"
TOOLS_DIR = Path(__file__).resolve().parent
MARKER = "V23INJECT"
# 临时副本排除：留痕（.verification 常含敏感留痕与大量文件）等不入注入副本
_IGNORE = shutil.ignore_patterns(".git", ".verification", "__pycache__",
                                 "node_modules", ".venv", "venv", ".idea", ".vscode")


class _BlockArgParser(argparse.ArgumentParser):
    """参数错误统一 exit 1（阻断码）——argparse 默认 exit 2 撞 WARN 码。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"错误: {message}。下一步: 按用法核对参数后重试。", file=sys.stderr)
        raise SystemExit(1)


def _flat(text: str) -> str:
    """证据压平：管道符→全角、各类换行→ ⏎（族惯例，与 local_gate 同口径）。"""
    return (str(text).replace("|", "｜")
            .replace("\r\n", " ⏎ ").replace("\r", " ⏎ ").replace("\n", " ⏎ "))


def _head(text: str, n: int = 160) -> str:
    t = _flat(text).strip()
    return t[:n] + ("…" if len(t) > n else "")


def _split_frontmatter(text: str) -> tuple[list[str], list[str], list[str]]:
    """拆 (前置行含首个---, frontmatter 行列, 其余行)。无合法 frontmatter 返回 None 语义。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return [], [], lines
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[:1], lines[1:i], lines[i:]
    return [], [], lines


def _drop_top_keys(fm: list[str], prefixes: tuple[str, ...]) -> list[str]:
    """删顶层键及其整块（缩进续行/嵌套块）——折叠标量（description: > 等）的
    续行一并删除，保证产物语义为"缺必填键"而非"孤续行 YAML 结构错"。"""
    out: list[str] = []
    skip_block = False
    for ln in fm:
        if skip_block:
            if ln.startswith((" ", "\t")) or not ln.strip():
                continue
            skip_block = False  # 回到顶层——当前行照常处理
        if not ln.startswith((" ", "\t")) and ln.lstrip().startswith(prefixes):
            skip_block = True
            continue
        out.append(ln)
    return out


def _mutate(src_text: str, case: str) -> str:
    """按用例改写 SKILL.md 文本（返回改写后全文，尾部追加 MARKER 行）。"""
    pre, fm, rest = _split_frontmatter(src_text)
    if case == "V23-1":
        fm = fm + ["\tbroken_inject: [未闭合"]
    elif case == "V23-2":
        fm = _drop_top_keys(fm, ("name:", "description:"))
    elif case == "V23-3":
        fm = [re.sub(r"^(name\s*:).*", r"\1 Bad_Name", ln) for ln in fm]
    out = "\n".join(pre + fm + rest) + f"\n{MARKER} {case}\n"
    return out


def _hash_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root)).replace("\\", "/")] = (
                hashlib.sha256(p.read_bytes()).hexdigest())
    return out


def _run_parser(cmd: list[str], target: Path, timeout: int):
    """跑解析器，返回 (returncode, 合并输出尾部)。None=启动失败。"""
    try:
        p = subprocess.run(cmd + [str(target)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"{type(e).__name__}: {e}"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _make_case_copy(skill_dir: Path, case: str | None) -> tuple[Path, Path]:
    """构造临时副本：内层目录名=原技能目录名（官方解析器校验目录名与
    frontmatter name 一致）；case=None 为对照组，否则施加对应变异。
    copytree 按 _IGNORE 排除留痕目录（效率+敏感留痕不进临时暴露窗口）。
    返回 (外层目录, 内层技能目录)——调用方负责 finally 清理外层；
    copytree 中途失败时此处就地清理外层再抛出（无残留）。"""
    outer = Path(tempfile.mkdtemp(prefix="v23_"))
    case_dir = outer / skill_dir.name
    try:
        shutil.copytree(skill_dir, case_dir, ignore=_IGNORE)
    except BaseException:
        shutil.rmtree(outer, ignore_errors=True)
        raise
    if case is not None:
        sm = case_dir / "SKILL.md"
        sm.write_text(_mutate(sm.read_text(encoding="utf-8-sig"), case),
                      encoding="utf-8")
    return outer, case_dir


def run_injection(skill_dir: Path, parser_cmd: list[str] | None,
                  timeout: int) -> tuple[list[dict], int]:
    """V23 主流程。返回 (行, 级别最高值)——0 全 PASS / 1 有 FAIL / 2 仅 WARN+SKIP。"""
    rows: list[dict] = []

    def add(vid: str, title: str, level: str, ev: str) -> None:
        rows.append(dict(vid=vid, title=title, level=level, ev=_flat(ev)))

    before = _hash_tree(skill_dir)
    cases = ["V23-1", "V23-2", "V23-3"]

    # V23-0 对照组：未修改副本须被解析器接受
    if parser_cmd is None:
        for c in ["V23-0"] + cases:
            add(c, {"V23-0": "对照组（未修改副本应通过）"}.get(c, c)
                + "（解析器）",
                "SKIP",
                "官方解析器未安装（pip install skills-ref==0.1.1，入口名 agentskills；"
                "或用 --parser-cmd 指定）——COV 覆盖缺口，SKIP 不计警告")
    else:
        outer, ctrl_dir = _make_case_copy(skill_dir, None)
        try:
            rc, out = _run_parser(parser_cmd, ctrl_dir, timeout)
        finally:
            shutil.rmtree(outer, ignore_errors=True)
        if rc is None:
            add("V23-0", "对照组（解析器启动）", "FAIL", f"启动失败：{out}")
        elif rc != 0:
            add("V23-0", "对照组（未修改副本应通过）", "FAIL",
                f"解析器对合法技能报错 exit={rc}——环境/解析器问题，"
                f"注入用例转 SKIP：{_head(out)}")
        else:
            add("V23-0", "对照组（未修改副本应通过）", "PASS",
                "解析器对未修改副本零退出")
            # V23-1..3 注入用例：fail-loud = 非零退出
            for c in cases:
                outer, case_dir = _make_case_copy(skill_dir, c)
                try:
                    rc, out = _run_parser(parser_cmd, case_dir, timeout)
                finally:
                    shutil.rmtree(outer, ignore_errors=True)
                if rc is None:
                    add(c, c + "（注入后应报错）", "FAIL", f"解析器启动失败：{out}")
                elif rc != 0:
                    add(c, c + "（注入后应报错）", "PASS",
                        f"宿主 fail-loud：exit={rc}（{_head(out, 100)}）")
                else:
                    add(c, c + "（注入后应报错）", "FAIL",
                        "解析器零退出——非法 frontmatter 被静默接受（非 fail-loud）")

    # V23-4 原目录未触碰（不依赖解析器，恒实检）
    after = _hash_tree(skill_dir)
    if before == after:
        add("V23-4", "原目录未触碰（SHA256 全清单）", "PASS",
            f"{len(before)} 文件执行前后哈希一致")
    else:
        diff = sorted(set(before) ^ set(after)
                      | {k for k in set(before) & set(after)
                         if before[k] != after[k]})
        add("V23-4", "原目录未触碰（SHA256 全清单）", "FAIL",
            f"原目录被触碰：{', '.join(diff[:5])}")

    levels = {r["level"] for r in rows}
    worst = 1 if "FAIL" in levels else (2 if "WARN" in levels or "SKIP" in levels else 0)
    return rows, worst


def main() -> int:
    ap = _BlockArgParser(
        description="V23 fail-loud 注入测试（M0-3 单宿主口径）：临时副本注入非法 "
                    "frontmatter，宿主报错而非静默跳过；原目录只读")
    ap.add_argument("skill_dir", help="待测技能根目录（含 SKILL.md）")
    ap.add_argument("--parser-cmd", help='解析器命令行（如 "python check.py"），'
                                         '尾元自动追加临时技能目录；缺省自动定位官方 agentskills')
    ap.add_argument("--timeout", type=int, default=60,
                    help="单次解析器调用超时秒数（默认 60）")
    ap.add_argument("--out", help="报告落盘路径（建议 .verification/m0-s/inject-test.md）")
    a = ap.parse_args()

    if a.timeout <= 0:
        print("错误: --timeout 须为正整数。", file=sys.stderr)
        return 1
    if a.out is not None and not a.out.strip():
        print("错误: --out 为空字符串。下一步: 传有效报告路径或省略 --out 仅 stdout 输出。",
              file=sys.stderr)
        return 1

    skill_dir = Path(a.skill_dir)
    if not (skill_dir / "SKILL.md").is_file():
        print(f"错误: {skill_dir} 下无 SKILL.md。下一步: 传技能根目录（含 SKILL.md）。",
              file=sys.stderr)
        return 1
    try:
        _sm_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8-sig")
    except OSError as e:
        print(f"错误: {skill_dir}/SKILL.md 读取失败: {e}"
              "。下一步: 检查文件权限/占用后重试。", file=sys.stderr)
        return 1
    _pre, _fm, _rest = _split_frontmatter(_sm_text)
    if not _fm:
        print(f"错误: {skill_dir}/SKILL.md 无合法 frontmatter——注入用例无目标。"
              "下一步: 核对 SKILL.md 或以 check_skill.py 复检。", file=sys.stderr)
        return 1

    parser_cmd: list[str] | None
    if a.parser_cmd is not None:
        if not a.parser_cmd.strip():
            print("错误: --parser-cmd 为空字符串。", file=sys.stderr)
            return 1
        parser_cmd = shlex.split(a.parser_cmd)
    else:
        sys.path.insert(0, str(TOOLS_DIR))
        try:
            from check_skill import find_official_cli  # noqa: PLC0415
        except ImportError:
            find_official_cli = None
        cli = find_official_cli() if find_official_cli else None
        # A1 同款调用形态：agentskills 为命令组，须显式 validate 子命令
        parser_cmd = [cli, "validate"] if cli else None

    rows, worst = run_injection(skill_dir, parser_cmd, a.timeout)

    lines = [f"# V23 fail-loud 注入测试报告（inject_test.py {VERSION}）",
             "",
             f"- 技能: {skill_dir}",
             f"- 解析器: {' '.join(parser_cmd) if parser_cmd else '未安装（SKIP）'}",
             f"- 汇总: {sum(r['level'] == 'PASS' for r in rows)} PASS / "
             f"{sum(r['level'] == 'FAIL' for r in rows)} FAIL / "
             f"{sum(r['level'] in ('WARN', 'SKIP') for r in rows)} WARN+SKIP",
             "",
             "| 项 | 内容 | 级别 | 证据 |",
             "|---|---|---|---|"]
    lines += [f"| {r['vid']} | {r['title']} | {r['level']} | {r['ev']} |" for r in rows]
    report = "\n".join(lines) + "\n"
    print(report, end="")
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(report, encoding="utf-8")
    return worst


if __name__ == "__main__":
    sys.exit(main())
