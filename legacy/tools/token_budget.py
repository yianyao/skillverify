#!/usr/bin/env python3
"""token_budget.py — Agent Skill V11 token 口径估算 + V17 上下文预算阻断门（S 工具链）。

落实《Agent-Skill 生命周期验证方案》：
  V11 [M] token 计数统一口径——优先使用目标宿主 tokenizer，否则字符数÷4 保守估算；
      CI 内固定同一实现（本工具即该固定实现：chars/4，--chars-per-token 可校准，
      校准后须同步 CI 配置保持全流水线一致）。
  V17 [M] 上下文预算阻断门（W-S §3 各行，本工具承载除行数外的预算项）：
      - SKILL.md 正文 <5000 tokens（官方 [M]）
      - 元数据（name + description）约 100 tokens（项目级收紧为阻断；官方 [S]）
      - 扩展层单文件 ≤500 行（项目级收紧为阻断；官方 [P]）
      - SKILL.md <300 行由 check_skill.py A6 承载，本工具只记 INFO 不重复判定。

检查项:
  V11-1 token 口径      正文 token 估算 <5000（V11 chars/4 口径），超限 FAIL
  V17-1 元数据预算      name + description token ≤100（项目收紧），超限 FAIL
  V17-2 扩展层行数      references/ 与 assets/ 逐文件行数 ≤500（项目收紧），
                        任一超限 FAIL 并列出文件
  V17-3 SKILL.md 行数   INFO 行——A6（<300 行）判定归 check_skill.py，此处仅记录
  COV   扫描覆盖        读取失败/目录缺失计覆盖缺口，零命中行降 WARN 不假 PASS

token 口径声明（docstring 显式，V11 要求 CI 固定同一实现）:
  tokens = ceil(字符数 / chars_per_token)，chars_per_token 默认 4（V11 保守兜底口径）。
  注意：CJK 文本实际 token 密度远高于 chars/4（常见 1–2 字符/token），
  chars/4 对 CJK 占比高的文本会**低估**——正文/元数据的 CJK 占比 >30% 时
  在证据中显式提示，提示人工关注（不改变判定，判定仍按 V11 固定口径）。

退出码: 0=全 PASS；1=任一 FAIL（预算超限）或参数错误（阻断）；2=无 FAIL 但有 WARN
（工具族 0/1/2 约定；**所有参数错误——缺参自查与 argparse 解析错误（含类型转换失败
如 --chars-per-token abc）——统一 exit 1 阻断码**，覆写 ArgumentParser.error() 实现，
不用 argparse 默认 exit 2 撞 WARN 码——naming_precheck v1.0.1 评审 5 纪律全工具对齐，
v1.0.1 评审 5 扩展覆盖类型错误场景）。

用法:
    python token_budget.py <skill_dir> [--body-budget 5000] [--metadata-budget 100]
                           [--ext-lines 500] [--chars-per-token 4] [--out report.md]

注: 本工具只做机械初筛；预算取舍（是否拆分正文、外移内容）由 V26/V27 流程与
人工裁决承担，本工具 FAIL 不得自动改写技能内容。

版本: v1.0.1（2026-10-02 建成 v1.0，同日首轮外部评审 6 条全属实修订：
无 SKILL.md 早退 stats 补齐键、V17-3 读取失败不缺席改 WARN、name+description
合并口径注释固化、argparse 解析错误统一 exit 1（error() 覆写）、测试 walrus 清理）
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- 常量表 ----

VERSION = "v1.0.1"

SKIP_DIRS = {".git", ".verification", "__pycache__", "node_modules", ".venv", "venv"}

DEFAULT_BODY_BUDGET = 5000        # 官方 [M]：SKILL.md 正文 <5000 tokens
DEFAULT_METADATA_BUDGET = 100     # 项目级收紧（官方 [S] "约 100"）
DEFAULT_EXT_LINES = 500           # 项目级收紧（官方 [P]）
DEFAULT_CHARS_PER_TOKEN = 4       # V11 保守兜底口径

CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
FM_KEY_RE = re.compile(r"[a-z][a-z0-9-]*")

# 扩展层目录（W-S §3 行明确为 references/、assets/；scripts/ 不属扩展层材料）
EXT_DIRS = ("references", "assets")


# ---------------------------------------------------------------- 基础设施 ----

def load_frontmatter_split(skill_md: Path) -> tuple[dict[str, str], str]:
    """解析 frontmatter 并返回 (fm 字典, 正文文本)。

    口径与 naming_precheck.py v1.0.1 同源：剥 BOM、缩进续行并入上一顶层键；
    正文 = frontmatter 结束符之后的内容（V11-1 只估正文，元数据不占正文预算）。"""
    try:
        raw = skill_md.read_bytes()
    except OSError:
        return {}, ""
    raw = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
    text = raw.decode("utf-8", errors="replace")
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", text, re.S)
    if not m:
        # 无 frontmatter：整文件视作正文（元数据不可验，交 COV/上游 A 门处理）
        return {}, text
    body = text[m.end():]
    fm: dict[str, str] = {}
    last_key: str | None = None
    for ln in m.group(1).split("\n"):
        if ln[:1] in (" ", "\t"):
            if last_key:
                fm[last_key] = (fm[last_key] + " " + ln.strip()).strip()
            continue
        if ":" in ln:
            k, _, v = ln.partition(":")
            k = k.strip()
            if FM_KEY_RE.fullmatch(k):
                fm[k] = v.strip()
                last_key = k
            else:
                last_key = None
    return fm, body


def estimate_tokens(text: str, chars_per_token: float) -> int:
    """V11 固定口径：ceil(字符数 / chars_per_token)。"""
    if not text:
        return 0
    return math.ceil(len(text) / chars_per_token)


def cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    n_cjk = len(CJK_CHAR_RE.findall(text))
    return n_cjk / len(text)


def _ratio_note(text: str) -> str:
    r = cjk_ratio(text)
    if r > 0.3:
        return f"〔CJK 占比 {r:.0%}，chars/4 口径可能低估实际 token，建议人工关注〕"
    return ""


def count_lines(p: Path) -> int:
    """行数口径与 check_skill.py A6 同源：按 \\n 计数，含末行无换行的孤行，
    剥离孤立 \\r（A7）。"""
    raw = p.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text = raw.decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


# ---------------------------------------------------------------- 检查主体 ----

def budget_check(skill_dir: Path, body_budget: int, metadata_budget: int,
                 ext_lines: int, chars_per_token: float) -> tuple[list[dict], dict]:
    """返回 (报告行, 统计)。行: dict(vid,title,level,ev)。"""
    rows: list[dict] = []
    n_read_err = 0
    read_err_files: list[str] = []

    def add(vid: str, title: str, level: str, ev: str) -> None:
        rows.append(dict(vid=vid, title=title, level=level, ev=ev))

    sm = skill_dir / "SKILL.md"
    if not sm.is_file():
        add("V11-1", "SKILL.md 正文 token 预算", "FAIL",
            f"SKILL.md 不存在: {sm}——无预算可验，先补交付物（A1 亦会 FAIL）")
        # stats 键结构全场景一致（v1.0.1 评审 1）：缺 SKILL.md 早退也不缺
        # body_tokens/meta_tokens 键，防下游调用方 KeyError
        return rows, dict(read_err=1, ext_files=0, body_tokens=0, meta_tokens=0)

    fm, body = load_frontmatter_split(sm)

    # ---- V11-1 正文 token ----
    body_tokens = estimate_tokens(body, chars_per_token)
    note = _ratio_note(body)
    body_lines = None
    try:
        body_lines = count_lines(sm)
    except OSError as e:
        n_read_err += 1
        read_err_files.append(f"SKILL.md（{e.strerror or e}）")
    add("V11-1", f"SKILL.md 正文 token <{body_budget}（官方 [M]，V11 chars/{chars_per_token:g} 口径）",
        "FAIL" if body_tokens >= body_budget else "PASS",
        f"正文 {len(body)} 字符 ≈ {body_tokens} tokens{note}")

    # ---- V17-1 元数据预算（name + description，项目级收紧）----
    # V17 原文口径即 "name + description 约 100 tokens"——两者合并计预算（含 1 个连接
    # 空格 ≈0.25 token，方向与规格一致，v1.0.1 评审 3 确认保留，不做仅 description 口径）
    meta_text = (fm.get("name", "") or "") + " " + (fm.get("description", "") or "")
    meta_tokens = estimate_tokens(meta_text.strip(), chars_per_token)
    meta_note = _ratio_note(fm.get("description", ""))
    if not fm.get("description"):
        add("V17-1", f"元数据 token ≤{metadata_budget}（项目级收紧，官方 [S]）", "WARN",
            "description 缺失——元数据预算不可验，不假 PASS")
    else:
        add("V17-1", f"元数据 token ≤{metadata_budget}（项目级收紧，官方 [S]）",
            "FAIL" if meta_tokens > metadata_budget else "PASS",
            f"name+description {len(meta_text.strip())} 字符 ≈ {meta_tokens} tokens{meta_note}")

    # ---- V17-2 扩展层单文件行数（references/ assets/，项目级收紧）----
    ext_files = 0
    over: list[str] = []
    for d in EXT_DIRS:
        dp = skill_dir / d
        if not dp.is_dir():
            continue
        for p in sorted(dp.rglob("*")):
            if not p.is_file() or p.is_symlink():
                continue
            if any(part in SKIP_DIRS for part in p.relative_to(skill_dir).parts):
                continue
            ext_files += 1
            try:
                lines = count_lines(p)
            except OSError as e:
                n_read_err += 1
                read_err_files.append(f"{p.relative_to(skill_dir)}（{e.strerror or e}）")
                continue
            if lines > ext_lines:
                over.append(f"{p.relative_to(skill_dir)}: {lines} 行")

    add("V17-2", f"扩展层单文件 ≤{ext_lines} 行（项目级收紧，官方 [P]）",
        "FAIL" if over else "PASS",
        ("; ".join(over) + "——超出项目收紧线，触发拆分评审") if over
        else (f"扩展层 {ext_files} 个文件全部达标" if ext_files else "无 references/、assets/ 文件"))

    # ---- V17-3 SKILL.md 行数（INFO，A6 域）----
    # v1.0.1 评审 2：读取失败时行也不缺席（level=WARN 明示"行数不可验"），
    # 与 COV 降级纪律一致——审查者不会找不到行
    if body_lines is not None:
        add("V17-3", "SKILL.md 行数（<300 行判定归 check_skill.py A6）", "INFO",
            f"当前 {body_lines} 行（≥240 触发 V27 预警线，≥300 由 A6 阻断）")
    else:
        add("V17-3", "SKILL.md 行数（<300 行判定归 check_skill.py A6）", "WARN",
            "读取失败——行数不可验（详 COV 行），A6 判定交由 check_skill.py 复核")

    # ---- COV 覆盖行 + 覆盖不全降级 ----
    cov_parts = [f"扩展层文件 {ext_files} 个"]
    if read_err_files:
        cov_parts.append("读取失败 " + "; ".join(read_err_files[:3]) +
                         ("（覆盖不全，零命中行已同步降 WARN）" if n_read_err else ""))
    add("COV", "扫描覆盖", "WARN" if n_read_err else "INFO", "; ".join(cov_parts))

    stats = dict(read_err=n_read_err, ext_files=ext_files,
                 body_tokens=body_tokens, meta_tokens=meta_tokens)

    if n_read_err:
        for r in rows:
            if r["level"] == "PASS":
                r["level"] = "WARN"
                r["ev"] += f"（WARN 缘由: {n_read_err} 个文件读取失败，覆盖不全）"
    return rows, stats


# ---------------------------------------------------------------- 报告与入口 ----

class _BlockArgParser(argparse.ArgumentParser):
    """参数错误统一 exit 1（阻断码）——argparse 默认 exit 2 撞 WARN 码。

    v1.0.1 评审 5：缺参自查（return 1）只覆盖了位置参数缺失，--body-budget abc 等
    类型转换失败仍走 argparse 内部 error() → exit 2。覆写 error() 统一收口：
    用法提示照常输出（V6 冒烟 C2 认 usage 关键词），退出码改 1。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"错误: {message}。下一步: 按用法核对参数后重试。", file=sys.stderr)
        raise SystemExit(1)


_ORDER = {"V11-1": 1, "V17-1": 2, "V17-2": 3, "V17-3": 4, "COV": 50}


def build_report(skill_dir: Path, rows: list[dict], stats: dict, args) -> str:
    has_fail = any(r["level"] == "FAIL" for r in rows)
    has_warn = any(r["level"] == "WARN" for r in rows)
    judged = [r for r in rows if r["level"] in ("PASS", "FAIL")]
    lines = [
        "# V11/V17 上下文预算报告（token_budget.py）",
        "",
        f"- 技能: {skill_dir.name}（{skill_dir}）",
        f"- 工具版本: {VERSION}",
        f"- 口径: V11 token 计数（chars/{args.chars_per_token:g} 保守兜底，宿主 tokenizer 缺席时的固定实现）；"
        f"V17 预算门——正文 <{args.body_budget} tokens（官方 [M]）/元数据 ≤{args.metadata_budget} tokens"
        f"（项目收紧）/扩展层单文件 ≤{args.ext_lines} 行（项目收紧）",
        f"- 总结论: {'FAIL（存在阻断项）' if has_fail else ('WARN（需人工复核）' if has_warn else 'PASS')}",
        "",
        "| 项 | 检查内容 | 结论 | 证据 |",
        "|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: (_ORDER.get(r["vid"], 99), r["vid"])):
        lines.append(f"| {r['vid']} | {r['title']} | {r['level']} | {r['ev']} |")
    lines += [
        "",
        f"> 判定统计: {sum(1 for r in judged if r['level'] == 'PASS')}/{len(judged)} PASS。"
        "SKILL.md <300 行由 check_skill.py A6 承载；预算超限的处置（拆分/外移）由 V26/V27 与人工裁决承担，本工具不自动改写。",
    ]
    if has_fail:
        lines[-1] += " [M] 级 FAIL 阻断：先处置预算超限再进入下一阶段。"
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = _BlockArgParser(
        description="Agent Skill V11/V17 上下文预算门（token 估算 + 扩展层行数）")
    ap.add_argument("skill_dir", nargs="?",
                    help="待检技能目录（含 SKILL.md）")
    ap.add_argument("--body-budget", type=int, default=DEFAULT_BODY_BUDGET,
                    help=f"正文 token 预算（默认 {DEFAULT_BODY_BUDGET}，官方 [M]）")
    ap.add_argument("--metadata-budget", type=int, default=DEFAULT_METADATA_BUDGET,
                    help=f"元数据 token 预算（默认 {DEFAULT_METADATA_BUDGET}，项目级收紧）")
    ap.add_argument("--ext-lines", type=int, default=DEFAULT_EXT_LINES,
                    help=f"扩展层单文件行数上限（默认 {DEFAULT_EXT_LINES}，项目级收紧）")
    ap.add_argument("--chars-per-token", type=float, default=DEFAULT_CHARS_PER_TOKEN,
                    help=f"V11 口径字符/token 比（默认 {DEFAULT_CHARS_PER_TOKEN}；宿主 tokenizer 校准后须全 CI 同步）")
    ap.add_argument("--out", help="报告落盘路径（建议 .verification/m1-s/token-budget.md）")
    a = ap.parse_args()

    # 参数自查返回 1（阻断码）——不用 argparse 默认 exit 2 撞 WARN 码
    # （skill_dir 缺参同此口径，naming_precheck v1.0.1 评审 5 纪律全工具对齐）
    if not a.skill_dir:
        print("错误: 缺技能目录参数。用法: python token_budget.py <skill_dir> "
              "[--body-budget N] [--metadata-budget N] [--ext-lines N] [--out report.md]。",
              file=sys.stderr)
        return 1
    if a.chars_per_token <= 0:
        print("错误: --chars-per-token 须为正数。下一步: 校准为宿主 tokenizer 实测比值后重试。",
              file=sys.stderr)
        return 1
    for flag, val in (("--body-budget", a.body_budget), ("--metadata-budget", a.metadata_budget),
                      ("--ext-lines", a.ext_lines)):
        if val <= 0:
            print(f"错误: {flag} 须为正整数。下一步: 核对预算配置后重试。", file=sys.stderr)
            return 1

    skill_dir = Path(a.skill_dir)
    if not skill_dir.is_dir():
        print(f"错误: 目录不存在: {skill_dir}。下一步: 核对路径后重试。", file=sys.stderr)
        return 1

    rows, stats = budget_check(skill_dir, a.body_budget, a.metadata_budget,
                               a.ext_lines, a.chars_per_token)
    report = build_report(skill_dir, rows, stats, a)
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

    has_fail = any(r["level"] == "FAIL" for r in rows)
    has_warn = any(r["level"] == "WARN" for r in rows)
    return 1 if has_fail else (2 if has_warn else 0)


if __name__ == "__main__":
    sys.exit(main())
