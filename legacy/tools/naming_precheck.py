#!/usr/bin/env python3
"""naming_precheck.py — Agent Skill V2 命名冲突预检器（S 工具链）。

落实《Agent-Skill 生命周期验证方案》V2 条目（[M]，设计期执行，D 门出口判据之一）：
设计期必须执行命名冲突预检——目标技能库中无同名 name、无高度重叠 description
（相似度默认阈值：余弦相似度 >0.85 或关键词重叠 >0.6 即告警，可按库规模调整）。

检查项:
  V2-1 同名 name 检索     目标 name 与库内技能 name 精确比对（大小写不敏感），
                          以及目标目录名与库内技能目录名冲突（name 必须与目录名
                          一致——总表 §1 第 2 条，故目录撞名等价于 name 撞名）；
                          命中即 FAIL
  V2-2 description 余弦   目标与库内全部技能 description 两两算余弦相似度，
                          top-1 超阈值即 WARN（告警级——语义重叠由人工判断，
                          本工具只做初筛）
  V2-3 关键词重叠         目标与库内 description 关键词集合算 Jaccard 重叠度
                          （交集/并集），top-1 超阈值即 WARN

相似度口径（启发式，docstring 显式声明）:
  分词 = ASCII 词元（[a-z0-9]+，小写化）+ CJK 二字元（bigram）。
  CJK 不取单字（"的/与/可"等虚字会淹没信号），二字元对中文词形召回足够；
  注意"二字元"的"相邻"指 CJK 字符**抽取序列**相邻——中间非 CJK 字符被丢弃，
  跨段伪 bigram（如"评审 Agent Skill 的"产出"审的"）属有意行为，口径固化于测试 0；
  余弦基于词元计数向量，Jaccard 基于词元集合。纯启发式，误报/漏报均由人工复核，
  与 V12 语义评审不互替。

覆盖不全不假 PASS（对齐工具族纪律）:
  库内存在 SKILL.md 存在但 name/description 不可解析的技能（解析失败）时，
  其 description 不参与相似度——覆盖有缺口，零命中行降 WARN + exit 不得为 0。
  目标无 description 时相似度不可验：V2-2/V2-3 记 WARN（不假 PASS）。

用法:
    python naming_precheck.py <skill_dir> --library <lib_dir> [--library ...]
    python naming_precheck.py --name <name> --description <desc> --library <lib_dir>
                              [--cos-threshold 0.85] [--overlap-threshold 0.6]
                              [--out report.md]

  设计期（立项前，技能目录尚不存在）用 --name/--description 直接输入；
  也可以传技能目录（SKILL.md 的 name/description 为准；name 缺失时以目录名兜底）。
  同时提供 skill_dir 与 --name/--description 时 **skill_dir 优先**，后者被忽略
  （检测到组合时打 stderr 提示，不静默）。
  --library 可重复传入多个技能库根目录；库内约定为扁平结构（<lib>/<skill-name>/SKILL.md）。
  目标目录若位于库内，自动排除自身（自比相似度恒 1.0，无意义）。

退出码: 0=全 PASS；1=任一 FAIL（同名冲突）或参数错误（阻断）；2=无 FAIL 但有 WARN
（工具族 0/1/2 约定；argparse 缺参不用其默认 exit 2（v1.0.1 评审 5），v1.0.3 进一步
把 argparse 解析错误（含类型转换失败如 --cos-threshold abc）经 error() 覆写统一
exit 1——不再有任何路径输出撞 WARN 码的 2）。
注: 目标无 description 时 V2-2/V2-3 必为 WARN（exit 2）——设计期 description 未定稿属常态，
建议先完成 description 草稿再预检，或接受告警走人工复核。
注: 本工具只做机械初筛；"范围定位是否与相邻技能实质重叠"的语义判断由 V1 设计
评审（H）承担，本工具告警不豁免 V1。

版本: v1.0.3（2026-10-02 建成 v1.0；同日 v1.0.1 首轮外部评审 7 条全属实修订：top-1 文案、
CJK 跨段口径成文、name 格式预检、参数优先级成文、缺参 exit 2→1 撞码修正、
V2-1 证据去重、覆盖缺口语义与 description 指引入 docstring；
v1.0.2 收尾自检发现 v1.0.1 引入 V6 冒烟 C2 回归——自查报错缺"用法"提示，
缺参消息补用法行修复；v1.0.3 随 token_budget 评审扩撞码覆盖——argparse
类型转换错误统一 exit 1）
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------- 常量表 ----

VERSION = "v1.0.3"

SKIP_DIRS = {".git", ".verification", "__pycache__", "node_modules", ".venv", "venv"}

DEFAULT_COS_THRESHOLD = 0.85
DEFAULT_OVERLAP_THRESHOLD = 0.6

ASCII_TOKEN_RE = re.compile(r"[a-z0-9]+")
CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
FM_KEY_RE = re.compile(r"[a-z][a-z0-9-]*")


# ---------------------------------------------------------------- 基础设施 ----

def tokenize(text: str) -> list[str]:
    """ASCII 词元 + CJK 二字元（bigram）。口径见模块 docstring。"""
    low = text.lower()
    toks = ASCII_TOKEN_RE.findall(low)
    cjk = CJK_CHAR_RE.findall(low)
    toks += [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
    if len(cjk) == 1:
        toks.append(cjk[0])  # 孤立单字（无相邻字可组 bigram）不丢
    return toks


def cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[t] * b[t] for t in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def jaccard(sa: set, sb: set) -> float:
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def load_frontmatter(skill_md: Path) -> dict[str, str]:
    """极简 frontmatter 顶层键解析（与 security_scan.py v1.0.2 同口径：剥 BOM、
    缩进续行并入上一顶层键——description 折叠标量/多行续写不丢内容）。"""
    try:
        raw = skill_md.read_bytes()
    except OSError:
        return {}
    raw = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
    text = raw.decode("utf-8", errors="replace")
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", text, re.S)
    if not m:
        return {}
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
        else:
            last_key = None
    return fm


def scan_library(library: Path) -> tuple[list[dict], int]:
    """扫描一个技能库根目录（扁平结构）。返回 (技能条目, 跳过目录数)。

    条目: dict(name, description, dir, parsed)。SKILL.md 存在但 name 不可解析
    → parsed=False（计覆盖缺口 unparsed）；无 SKILL.md 的子目录计 skipped_dirs
    但**不计覆盖缺口**——非技能目录系有意排除，不属覆盖损失。"""
    entries: list[dict] = []
    n_skipped = 0
    for p in sorted(library.iterdir()):
        if not p.is_dir() or p.name.startswith(".") or p.name in SKIP_DIRS:
            continue
        sm = p / "SKILL.md"
        if not sm.is_file():
            n_skipped += 1
            continue
        fm = load_frontmatter(sm)
        name = fm.get("name", "")
        parsed = bool(name) and bool(FM_KEY_RE.fullmatch(name))
        entries.append(dict(name=name.lower() if parsed else "",
                            description=fm.get("description", ""),
                            dir=p, parsed=parsed))
    return entries, n_skipped


# ---------------------------------------------------------------- 检查主体 ----

def precheck(name: str, description: str, libraries: list[Path],
             target_dir: Path | None,
             cos_threshold: float, overlap_threshold: float) -> tuple[list[dict], dict]:
    """返回 (报告行, 统计)。行: dict(vid,title,level,ev)。"""
    rows: list[dict] = []

    def add(vid: str, title: str, level: str, ev: str) -> None:
        rows.append(dict(vid=vid, title=title, level=level, ev=ev))

    name_low = name.lower().strip()
    target_dir_res = target_dir.resolve() if target_dir else None

    all_entries: list[dict] = []
    n_unparsed = 0
    n_skipped_dirs = 0
    n_lib_dirs_missing = 0
    dir_collisions: list[str] = []
    name_collisions: list[tuple[str, Path]] = []  # (name, 所在技能目录)

    for lib in libraries:
        if not lib.is_dir():
            n_lib_dirs_missing += 1
            continue
        # V2-1 目录名冲突：目标将占用 <lib>/<name>/，该路径已被占即撞名
        cand = lib / name_low
        if cand.is_dir() and (target_dir_res is None or cand.resolve() != target_dir_res):
            dir_collisions.append(str(cand))
        entries, skipped = scan_library(lib)
        n_skipped_dirs += skipped
        for e in entries:
            if target_dir_res is not None and e["dir"].resolve() == target_dir_res:
                continue  # 排除自身
            if not e["parsed"]:
                n_unparsed += 1
                continue
            if e["name"] == name_low:
                name_collisions.append((e["name"], e["dir"]))
            all_entries.append(e)

    # V2-1 证据拼装：同名条目已含其目录路径，同一技能的目录撞名证据去重
    # （同名+同目录时路径不得出现两次——v1.0.1 评审 6）
    nc_paths = {str(d) for _, d in name_collisions}
    name_evs = [f"{n}（{d}）" for n, d in name_collisions]
    dir_evs = [d for d in dir_collisions if d not in nc_paths]
    v2_1_ev = [*name_evs, *dir_evs]
    add("V2-1", "同名 name / 目录名冲突（§1 第 2 条）",
        "FAIL" if v2_1_ev else "PASS",
        ("; ".join(v2_1_ev) + "——撞名须更名（name 必须与目录名一致）")
        if v2_1_ev
        else f"库内 {len(all_entries)} 个已解析技能 + 目录名检索零冲突")

    # ---- V2-2 / V2-3 相似度 ----
    tgt_tokens = tokenize(description)
    tgt_vec = Counter(tgt_tokens)
    tgt_set = set(tgt_tokens)

    scored: list[dict] = []
    if tgt_tokens:
        for e in all_entries:
            e_tokens = tokenize(e["description"])
            e_vec = Counter(e_tokens)
            scored.append(dict(e, cos=cosine(tgt_vec, e_vec),
                               jac=jaccard(tgt_set, set(e_tokens))))
        top_cos = sorted(scored, key=lambda x: x["cos"], reverse=True)
        top_jac = sorted(scored, key=lambda x: x["jac"], reverse=True)

        def top3(items: list[dict], key: str) -> str:
            return "; ".join(f"{it['name']}={it[key]:.3f}" for it in items[:3]) or "（库空）"

        c_top = top_cos[0] if top_cos else None
        j_top = top_jac[0] if top_jac else None
        add("V2-2", f"description 余弦相似度 ≤{cos_threshold}（V2 阈值，可调）",
            "WARN" if (c_top and c_top["cos"] > cos_threshold) else "PASS",
            (f"top-1 **{c_top['name']}={c_top['cos']:.3f}**（判定取第 1，超阈值即告警）；"
             f"前 3 名: {top3(top_cos, 'cos')}") if c_top else "目标无 description 或库内无可比条目")
        add("V2-3", f"description 关键词重叠(Jaccard) ≤{overlap_threshold}（V2 阈值，可调）",
            "WARN" if (j_top and j_top["jac"] > overlap_threshold) else "PASS",
            (f"top-1 **{j_top['name']}={j_top['jac']:.3f}**（判定取第 1，超阈值即告警）；"
             f"前 3 名: {top3(top_jac, 'jac')}") if j_top else "目标无 description 或库内无可比条目")
    else:
        add("V2-2", f"description 余弦相似度 ≤{cos_threshold}（V2 阈值，可调）", "WARN",
            "目标无 description——相似度不可验，不假 PASS（人工确认 description 待补）")
        add("V2-3", f"description 关键词重叠(Jaccard) ≤{overlap_threshold}（V2 阈值，可调）", "WARN",
            "目标无 description——相似度不可验，不假 PASS（人工确认 description 待补）")

    # ---- COV 覆盖行 + 覆盖不全降级 ----
    cov_parts = [f"库 {len(libraries)} 个（不可达 {n_lib_dirs_missing}）、"
                 f"可比技能 {len(all_entries)} 个",
                 f"跳过非技能子目录 {n_skipped_dirs}、name 不可解析 {n_unparsed}、"
                 f"排除目录 {sorted(SKIP_DIRS)}"]
    if n_unparsed or n_lib_dirs_missing:
        cov_parts.append("存在覆盖缺口（不可解析/不可达条目的 description 未参与相似度）")
    add("COV", "扫描覆盖", "WARN" if (n_unparsed or n_lib_dirs_missing) else "INFO",
        "; ".join(cov_parts))

    stats = dict(libraries=len(libraries), lib_missing=n_lib_dirs_missing,
                 comparable=len(all_entries), unparsed=n_unparsed,
                 skipped_dirs=n_skipped_dirs)

    if n_unparsed or n_lib_dirs_missing:
        # 降级语义精确化：不可解析条目的**目录名仍参与 V2-1 检索**（name 必须与
        # 目录名一致，目录撞名扫描不依赖解析），故解析缺口只降相似度行；
        # 不可达库则目录与描述都扫不到，全部行降级。
        for r in rows:
            if r["level"] == "PASS":
                if n_lib_dirs_missing or r["vid"] in ("V2-2", "V2-3"):
                    r["level"] = "WARN"
                    r["ev"] += f"（WARN 缘由: 覆盖缺口——{n_unparsed} 个不可解析/{n_lib_dirs_missing} 个不可达，覆盖不全）"
    return rows, stats


# ---------------------------------------------------------------- 报告与入口 ----

_ORDER = {"V2-1": 1, "V2-2": 2, "V2-3": 3, "COV": 50}


def build_report(name: str, libraries: list[Path], rows: list[dict], stats: dict,
                 cos_threshold: float, overlap_threshold: float) -> str:
    has_fail = any(r["level"] == "FAIL" for r in rows)
    has_warn = any(r["level"] == "WARN" for r in rows)
    judged = [r for r in rows if r["level"] in ("PASS", "FAIL")]
    lines = [
        "# V2 命名冲突预检报告（naming_precheck.py）",
        "",
        f"- 目标: {name}",
        f"- 工具版本: {VERSION}",
        f"- 口径: V2（[M] 设计期）——同名 name 检索（§1 第 2 条）/description 相似度"
        f"（余弦 >{cos_threshold} 或关键词重叠 >{overlap_threshold} 告警，阈值可调）",
        f"- 库: {'; '.join(str(p) for p in libraries)}",
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
        "相似度告警=人工复核入口；范围定位的实质重叠判断由 V1 设计评审（H）承担，本工具零命中不豁免 V1。",
    ]
    if has_fail:
        lines[-1] += " [M] 级 FAIL 阻断：撞名须更名后复跑。"
    return "\n".join(lines) + "\n"


class _BlockArgParser(argparse.ArgumentParser):
    """参数错误统一 exit 1（阻断码）——argparse 默认 exit 2 撞 WARN 码。

    v1.0.3：v1.0.1 评审 5 的自查（return 1）只覆盖缺参，--cos-threshold abc 等
    类型转换失败仍走 argparse 内部 error() → exit 2。覆写 error() 统一收口：
    用法提示照常输出（V6 冒烟 C2 认 usage 关键词），退出码改 1。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"错误: {message}。下一步: 按用法核对参数后重试。", file=sys.stderr)
        raise SystemExit(1)


def main() -> int:
    ap = _BlockArgParser(
        description="Agent Skill V2 命名冲突预检器（同名 name / description 相似度告警）")
    ap.add_argument("skill_dir", nargs="?", help="待检技能目录（含 SKILL.md）；设计期无目录时用 --name/--description")
    ap.add_argument("--name", help="目标 name（设计期直接输入模式）")
    ap.add_argument("--description", default="", help="目标 description（设计期直接输入模式）")
    # 不用 required=True：argparse 缺参会 SystemExit(2)，与工具族 WARN 码 2 撞码
    # （v1.0.1 评审 5）——改 main() 自查并返回 1（FAIL 码，明确阻断）
    ap.add_argument("--library", action="append",
                    help="目标技能库根目录（扁平结构），可重复")
    ap.add_argument("--cos-threshold", type=float, default=DEFAULT_COS_THRESHOLD,
                    help=f"余弦告警阈值（默认 {DEFAULT_COS_THRESHOLD}，V2 可按库规模调整）")
    ap.add_argument("--overlap-threshold", type=float, default=DEFAULT_OVERLAP_THRESHOLD,
                    help=f"关键词重叠告警阈值（默认 {DEFAULT_OVERLAP_THRESHOLD}）")
    ap.add_argument("--out", help="报告落盘路径（建议 .verification/m1-s/naming-precheck.md）")
    a = ap.parse_args()

    if not a.library:
        print("错误: 缺 --library（目标技能库根目录，可重复传入多个）。"
              "用法: naming_precheck.py <skill_dir> --library <lib_dir> [--library ...] "
              "或 --name <name> --description <desc> --library <lib_dir>。下一步: 补充后重试。",
              file=sys.stderr)
        return 1

    target_dir: Path | None = None
    if a.skill_dir:
        target_dir = Path(a.skill_dir)
        if not target_dir.is_dir():
            print(f"错误: 目录不存在: {target_dir}。下一步: 核对路径后重试，或改用 --name/--description 设计期模式。",
                  file=sys.stderr)
            return 1
        if a.name or a.description:
            print("提示: skill_dir 模式优先，--name/--description 已被忽略（取值来自 SKILL.md）。",
                  file=sys.stderr)
        fm = load_frontmatter(target_dir / "SKILL.md")
        name = fm.get("name") or target_dir.name  # name 缺失以目录名兜底（§1 第 2 条）
        description = fm.get("description", "")
    elif a.name:
        name = a.name
        description = a.description
    else:
        print("错误: 须提供技能目录或 --name。用法: naming_precheck.py <skill_dir> --library <lib_dir> "
              "或 --name <name> --description <desc> --library <lib_dir>。下一步: 补充输入后重试。",
              file=sys.stderr)
        return 1

    # name 格式预检（v1.0.1 评审 3）：防 --name "../etc"/"a/b" 构造越界路径；
    # 同时与 V2-1 报告"name 必须与目录名一致"的措辞呼应（§1 name 规范）
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name.lower().strip()):
        print(f"错误: name 不符合规范 ^[a-z0-9]+(-[a-z0-9]+)*$: {name!r}。"
              "下一步: 按 §1 命名规范更名后重试。", file=sys.stderr)
        return 1

    libraries = [Path(p) for p in a.library]
    rows, stats = precheck(name, description, libraries, target_dir,
                           a.cos_threshold, a.overlap_threshold)
    report = build_report(name, libraries, rows, stats,
                          a.cos_threshold, a.overlap_threshold)
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
