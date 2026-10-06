"""lint.refs —— 文件引用与路径检查。

官方条款：
- https://agentskills.io/specification#file-references
  "use relative paths from the skill root" / "Keep file references one level deep
  from SKILL.md. Avoid deeply nested reference chains."
- https://agentskills.io/specification#directory-structure
  约定承载目录为 `scripts/`、`references/`、`assets/`。
- https://agentskills.io/skill-creation/best-practices
  "'Read references/api-errors.md if ...' is more useful than a generic
  'see references/ for details.'"

**本模块最重要的一个设计决定**：把「文档指针」（代码围栏**外**的引用）与
「可执行示例」（围栏**内**的引用）分开判定——
- 围栏外的断链是客观缺陷（文档指向一个不存在的文件），记 FAIL；
- 围栏内可能是占位示例（`scripts/foo.py`），记 WARN 并要求人工确认。
旧体系把两者混在一张表里，结果只有两个选择：要么静默漏报（做了却不影响判定），
要么把示例路径一律 FAIL（假阳性）。分开判定才两头都站得住。
"""

from __future__ import annotations

import re
from pathlib import Path

from ..report import FAIL, INFO, PASS, WARN, Result, Rule
from .shared import (
    LintContext,
    REF_RE,
    URL_RE,
    fence_map,
    normalize_ref,
    ref_depth,
    res,
    strip_urls,
    summarize,
)

_SPEC_REFS = "https://agentskills.io/specification#file-references"
_SPEC_DIRS = "https://agentskills.io/specification#directory-structure"
_BP = "https://agentskills.io/skill-creation/best-practices#structure-large-skills-with-progressive-disclosure"

#: 承载目录（官方约定的三个 + 本项目曾用过、明确告知不再推荐的两个）
CARRIER_DIRS = ("references", "scripts", "assets", "evals", "templates")

RULES: dict[str, Rule] = {
    "REF-001": Rule(
        "REF-001",
        "正文引用的包内文件必须存在（代码块外）",
        "SHOULD",
        _SPEC_REFS,
        "修正路径或补上被引用的文件；相对技能根目录书写",
    ),
    "REF-002": Rule(
        "REF-002",
        "代码块内引用的路径须存在（可能是占位示例）",
        "HOUSE",
        "本项目收紧：官方未要求校验存在性",
        "示例性引用改为不含真实承载目录的占位写法（如 `scripts/<name>.py`）或补上文件",
    ),
    "REF-003": Rule(
        "REF-003",
        "不得使用宿主绝对路径（~/、$HOME、盘符）",
        "SHOULD",
        _SPEC_REFS,
        "改为相对技能根目录的路径；技能要跨宿主可用，不能绑定某一台机器",
    ),
    "REF-004": Rule(
        "REF-004",
        "指向本包文件的引用应写相对路径（禁绝对路径与 `..` 上跳）",
        "HOUSE",
        "本项目收紧：官方只说“用相对路径”，未单列上跳",
        "把绝对路径/上跳写法改成相对技能根目录的写法",
    ),
    "REF-005": Rule(
        "REF-005",
        "引用深度 ≤1 层（避免深层引用链）",
        "SHOULD",
        _SPEC_REFS,
        "把二级引用改为直接从 SKILL.md 引用，或把内容合并进一层文件",
    ),
    "REF-006": Rule(
        "REF-006",
        "避免笼统指引（须点名具体文件）",
        "SHOULD",
        _BP,
        "写成「读 references/api-errors.md（API 返回非 200 时）」，点名文件并给出加载时机",
    ),
    "REF-007": Rule(
        "REF-007",
        "scripts/ 下的脚本须在 SKILL.md 中被列出",
        "SHOULD",
        "https://agentskills.io/skill-creation/using-scripts#referencing-scripts-from-skillmd",
        "在 SKILL.md 的「可用脚本」清单里加上该脚本及其用途，否则 Agent 不知道它存在",
    ),
}

#: 宿主绝对路径（家目录形态 + 盘符）。负向后顾避免把 `http://` 里的 `p:/` 误判为盘符。
HOST_PATH_RE = re.compile(
    r"(?<![\w.])~[\\/]"
    r"|\$\{?(?:HOME|USERPROFILE|HOMEPATH)\}?"
    r"|%(?:USERPROFILE|HOMEPATH|HOMEDRIVE)%"
    r"|\$env:(?:USERPROFILE|HOMEPATH|HOMEDRIVE)"
    r"|(?<![\w.])[A-Za-z]:[\\/]"
)

#: 绝对路径（或上跳）形式的包内引用：`pre` 非空即命中
ABS_REF_RE = re.compile(
    r"(?P<pre>(?:[A-Za-z]:[\\/]|/|~[\\/]|\.\.[\\/])(?:[\w.@+\-]+[\\/])*)"
    r"(?P<ref>(?:" + "|".join(CARRIER_DIRS) + r")[\\/][\w./\\-]+)"
)

#: 笼统指引（中文/英文）：承载目录后没有具体文件名
VAGUE_RE = re.compile(
    r"(?:详见|参见|参考|见|阅读|读取|see|read|refer\s+to)\s*[`\"']?"
    r"(?:references|scripts|assets|evals|templates)[\\/]?[`\"']?"
    r"\s*(?:目录|文件夹|文件夹下|for\s+details|for\s+more)?\s*[。.，,；;：:]?\s*$",
    re.I,
)
VAGUE_MORE_RE = re.compile(r"更多示例|更多例子|更多内容|more\s+examples", re.I)


def _extract_refs(text: str) -> list[tuple[str, int, bool]]:
    """从文本抽取引用，返回 [(规范化引用, 行号, 是否在代码围栏内)]。"""
    out: list[tuple[str, int, bool]] = []
    fences = fence_map(text)
    for idx, line in enumerate(strip_urls(text).split("\n")):
        in_fence = fences[idx] if idx < len(fences) else False
        for match in REF_RE.finditer(line):
            ref = normalize_ref(match.group(0))
            if not ref:
                continue
            out.append((ref, idx + 1, in_fence))
    return out


def _exists(root: Path, ref: str) -> bool:
    try:
        return (root / ref).exists()
    except OSError:
        return False


def _exact_case(inv, ref: str) -> bool:
    """包内是否存在**大小写完全一致**的路径记录（跨宿主可移植性）。"""
    return any(rec.rp == ref for rec in inv.files)


def _case_variant(inv, ref: str) -> bool:
    """包内是否存在**仅大小写不同**的同路径记录。

    这类引用在大小写不敏感的磁盘上（Windows/macOS 默认）能打开，在 Linux 上是断链——
    无论当前磁盘属于哪种，都该按「大小写不一致」警告，而不是按断链 FAIL：
    修复动作是改大小写，不是补文件。
    """
    folded = ref.casefold()
    return any(rec.rp != ref and rec.rp.casefold() == folded for rec in inv.files)


def check(ctx: LintContext) -> list[Result]:
    out: list[Result] = []
    root = ctx.root
    refs = _extract_refs(ctx.text)

    # ---- REF-001 / REF-002：存在性（按围栏内外分流）----
    prose = [(ref, lineno) for ref, lineno, in_fence in refs if not in_fence]
    fenced = [(ref, lineno) for ref, lineno, in_fence in refs if in_fence]

    def _existence(items: list[tuple[str, int]]) -> tuple[list[str], list[str]]:
        broken: list[str] = []
        mismatch: list[str] = []
        seen_local: set[str] = set()
        for ref, lineno in items:
            if ref in seen_local:
                continue
            seen_local.add(ref)
            if _exists(root, ref):
                if (root / ref).is_file() and not _exact_case(ctx.inventory, ref):
                    mismatch.append(f"{ref}（{ctx.skill_md_rel}:{lineno}）")
                continue
            if _case_variant(ctx.inventory, ref):
                # 文件系统上打不开，但清单里有仅大小写不同的记录——
                # 这是大小写不一致（可移植性隐患），不是断链；Linux 上尤其要走到这分支
                mismatch.append(f"{ref}（{ctx.skill_md_rel}:{lineno}）")
                continue
            broken.append(f"{ref}（{ctx.skill_md_rel}:{lineno}）")
        return broken, mismatch

    if not prose:
        out.append(res(RULES["REF-001"], INFO,
                       f"不适用：{ctx.skill_md_rel} 正文（代码块外）未引用包内文件"))
    else:
        broken_prose, case_mismatch = _existence(prose)
        if broken_prose:
            out.append(res(RULES["REF-001"], FAIL, f"断链: {summarize(broken_prose)}"))
        elif case_mismatch:
            out.append(
                res(RULES["REF-001"], WARN,
                    f"路径大小写与磁盘不一致（Windows 通过、Linux 会失败）: "
                    f"{summarize(case_mismatch)}")
            )
        else:
            out.append(res(RULES["REF-001"], PASS, f"{len(prose)} 处正文引用均存在"))

    if not fenced:
        out.append(res(RULES["REF-002"], INFO,
                       f"不适用：{ctx.skill_md_rel} 代码块内未引用包内路径"))
    else:
        broken_example, _mismatch2 = _existence(fenced)
        if broken_example:
            out.append(
                res(RULES["REF-002"], WARN,
                    f"代码块内路径不存在（可能是有意的占位示例，须人工确认）: "
                    f"{summarize(broken_example)}")
            )
        else:
            out.append(res(RULES["REF-002"], PASS, f"{len(fenced)} 处代码块内引用均存在"))

    # ---- REF-003：宿主绝对路径（全包文本）----
    host_hits: list[str] = []
    for rec in ctx.inventory.texts:
        for lineno, line in enumerate(strip_urls(rec.text or "").split("\n"), 1):
            if HOST_PATH_RE.search(line):
                host_hits.append(f"{rec.rp}:{lineno}")
    if host_hits:
        out.append(res(RULES["REF-003"], FAIL, f"宿主绝对路径: {summarize(host_hits)}"))
    else:
        out.append(res(RULES["REF-003"], PASS, f"扫描 {len(ctx.inventory.texts)} 个文本文件，零命中"))

    # ---- REF-004：指向本包文件的绝对路径 / 上跳写法 ----
    abs_hits: list[str] = []
    for rec in ctx.inventory.texts:
        for lineno, line in enumerate(strip_urls(rec.text or "").split("\n"), 1):
            for match in ABS_REF_RE.finditer(line):
                ref = normalize_ref(match.group("ref"))
                if _exists(root, ref):
                    abs_hits.append(f"{rec.rp}:{lineno}: {match.group('pre')}{match.group('ref')}")
    if abs_hits:
        out.append(res(RULES["REF-004"], WARN, summarize(abs_hits)))
    else:
        out.append(res(RULES["REF-004"], PASS, "未发现绝对路径/上跳形式的包内引用"))

    # ---- REF-005：引用深度 ----
    chains: list[str] = []
    deep_paths: list[str] = []
    for ref, _lineno, _in_fence in refs:
        if ref_depth(ref) > 2:
            deep_paths.append(ref)
    for ref, _lineno, _in_fence in refs:
        if not _exists(root, ref) or Path(ref).suffix.lower() not in (".md", ".txt", ".rst"):
            continue
        rec = ctx.inventory.by_rel(ref)
        if rec is None or rec.text is None:
            continue
        for ref2, lineno2, _f2 in _extract_refs(rec.text):
            chains.append(f"SKILL.md → {ref} → {ref2}（{ref}:{lineno2}）")
    if chains or deep_paths:
        parts = []
        if chains:
            parts.append(f"二层引用链: {summarize(sorted(set(chains)))}")
        if deep_paths:
            parts.append(f"路径层级 >2: {summarize(sorted(set(deep_paths)))}")
        out.append(res(RULES["REF-005"], WARN, "；".join(parts)))
    else:
        out.append(res(RULES["REF-005"], PASS,
                       f"{len({r for r, _l, _f in refs})} 条引用均为一层且无更深链"))

    # ---- REF-006：笼统指引 ----
    fences = fence_map(ctx.text)
    vague: list[str] = []
    for idx, line in enumerate(strip_urls(ctx.text).split("\n")):
        if fences[idx] if idx < len(fences) else False:
            continue  # 围栏内是命令示例，不是指引
        if VAGUE_RE.search(line.strip()):
            vague.append(f"SKILL.md:{idx + 1}: 承载目录未点名具体文件")
        elif VAGUE_MORE_RE.search(line) and not REF_RE.search(line) and not URL_RE.search(line):
            vague.append(f"SKILL.md:{idx + 1}: 孤立“更多示例”且无路径")
    if vague:
        out.append(res(RULES["REF-006"], WARN, summarize(vague)))
    else:
        out.append(res(RULES["REF-006"], PASS, "未命中笼统指引模式"))

    # ---- REF-007：scripts/ 清单 ----
    scripts = [rec for rec in ctx.inventory.files if rec.under("scripts")]
    if not scripts:
        out.append(res(RULES["REF-007"], INFO, "不适用：包内无 scripts/ 目录"))
    else:
        missing = [
            rec.rp for rec in scripts
            if f"scripts/{rec.rel.name}" not in ctx.text and rec.rel.name not in ctx.text
        ]
        if missing:
            out.append(res(RULES["REF-007"], WARN, f"未在 SKILL.md 中列出: {summarize(missing)}"))
        else:
            out.append(res(RULES["REF-007"], PASS, f"{len(scripts)} 个脚本均在 SKILL.md 中被列出"))

    return out
