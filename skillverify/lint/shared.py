"""lint.shared —— lint 各检查族共用的上下文、文本工具与证据整形。

设计纪律（来自旧体系的教训，逐条对应）：
1. **证据整形集中一处**：旧体系把 `_head(160)`/`[:5]`/`[:3]` 等截断魔数散在各工具里，
   导致"包很大但只看过 5% 命中"。此处统一 MAX_EVIDENCE_ITEMS / MAX_EVIDENCE_CHARS，
   并始终在证据里回显总命中数（"等 N 处"），使报告不隐瞒规模。
2. **密钥证据必须脱敏**：旧体系曾把命中的密钥原文写进落盘报告（二次泄露面）。
3. **URL 必须先剥离再做引用匹配**：`https://host/scripts/foo` 曾被当成包内相对引用。
4. **行号一律换算成文件真实行号**（含 frontmatter 偏移），否则人工核对扑空。
5. 文本工具函数只做纯函数变换，不读文件——IO 全归 inventory。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from ..report import Result, Rule
from ..spec import SkillDocument
from .inventory import Inventory

#: 单条规则证据中最多列举的条目数（其余以"等 N 处"计）
MAX_EVIDENCE_ITEMS = 5

#: 单条规则证据的最大字符数（超出截断并标注）
MAX_EVIDENCE_CHARS = 400

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
URL_RE = re.compile(r"(?:https?|ftp|file)://[^\s<>()\[\]\"'`]+")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
#: 引用形态：以约定的承载目录开头（官方 specification#directory-structure）
REF_RE = re.compile(r"(?:references|scripts|assets|evals|templates)/[\w./\\-]+")


# --------------------------------------------------------------------------- #
# 上下文
# --------------------------------------------------------------------------- #


@dataclass
class LintContext:
    """一次 lint 的输入集合。检查族只读它，不各自遍历文件系统。"""

    root: Path
    doc: SkillDocument
    skill_md_rel: str
    text: str  # SKILL.md 全文（含 frontmatter）
    body: str  # 正文（不含 frontmatter）
    inventory: Inventory
    run_scripts: bool = False
    script_timeout_s: float = 10.0
    script_budget_s: float = 120.0

    @property
    def frontmatter(self) -> dict:
        return self.doc.frontmatter.data if self.doc.frontmatter else {}

    def meta_text(self) -> str:
        """frontmatter 全文（含缩进叶值），用于"依赖是否被文档说明"这类检索。"""
        return self.doc.frontmatter.raw if self.doc.frontmatter else ""


# --------------------------------------------------------------------------- #
# 结果构造与证据整形
# --------------------------------------------------------------------------- #


def res(rule: Rule, status: str, evidence: str = "") -> Result:
    """按规则元数据构造一条结果（FAIL/WARN 自动带修复指引）。"""
    from ..report import FAIL, WARN

    text = clip(evidence)
    return Result(
        rid=rule.rid,
        title=rule.title,
        status=status,
        level=rule.level,
        evidence=text,
        remediation=rule.remediation if status in (FAIL, WARN) else "",
    )


def clip(text: str) -> str:
    """证据单行化 + 长度封顶（报告是表格，换行与超长都会破坏可读性）。"""
    flat = " ".join(str(text).split())
    if len(flat) > MAX_EVIDENCE_CHARS:
        flat = flat[: MAX_EVIDENCE_CHARS - 1] + "…"
    return flat


def summarize(items: list[str], limit: int = MAX_EVIDENCE_ITEMS) -> str:
    """列举前 limit 条并在超出时回显总数，绝不静默丢弃规模信息。"""
    if not items:
        return ""
    head = "；".join(items[:limit])
    if len(items) > limit:
        head += f"；等共 {len(items)} 处"
    return head


def mask_secret(value: str) -> str:
    """脱敏：保留首 4 + 尾 2，短值整体省略。报告是会被归档/分享的产物。"""
    if len(value) <= 6:
        return "…"
    return f"{value[:4]}…{value[-2:]}(len={len(value)})"


# --------------------------------------------------------------------------- #
# 文本工具（纯函数）
# --------------------------------------------------------------------------- #


def count_lines(text: str) -> int:
    """真实行数：splitlines() 不把行尾换行算成额外一行（旧体系的 off-by-one 来源）。"""
    return len(text.splitlines())


def estimate_tokens(text: str) -> int:
    """token 估算：ceil(字符数 / 4)。

    **局限（必须随报告一起呈现）**：该系数对英文散文尚可，对 CJK 明显**低估**
    （1 个汉字通常 ≥1 token）。调用方应在 CJK 占比高时附提示，不得当成硬指标。
    """
    return math.ceil(len(text) / 4) if text else 0


def cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    return len(CJK_RE.findall(text)) / len(text)


def strip_urls(text: str) -> str:
    """剥离 URL：否则 `https://host/scripts/foo` 会被当成包内相对引用。"""
    return URL_RE.sub("", text)


def fence_map(text: str) -> list[bool]:
    """逐行标注是否处于代码围栏内（含围栏分隔行本身）。

    用途：把"文档指针"（围栏外）与"可执行示例"（围栏内）分开判定——
    两者误报率相差极大，混在一起必然要么漏报要么噪音。
    """
    flags: list[bool] = []
    in_fence = False
    for line in text.split("\n"):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            flags.append(True)
            continue
        flags.append(in_fence)
    return flags


def strip_inline_comment(line: str) -> str:
    """去掉行尾 `#` 注释（不处理引号内 #，仅用于 CJK 混译这类启发式）。

    为什么要剥：`pip install x  # 安装依赖` 里的中文注释是**推荐写法**，
    不剥掉就会被"代码块内混入 CJK"误报。
    """
    idx = line.find("#")
    if idx <= 0:
        return line
    if line[idx - 1] in (" ", "\t"):
        return line[:idx]
    return line


def shannon_entropy(text: str) -> float:
    """香农熵（比特/字符）。

    保留理由与边界：十六进制字符集上限仅 4.0 bit/char，故 sha256 十六进制串
    **不会**被熵阈值命中（这是刻意设计，不是缺陷）；熵只作廉价补充网，
    判定上限为 WARN，永不作 FAIL。
    """
    if not text:
        return 0.0
    counts: dict[str, int] = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    total = len(text)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


#: 引用所在行的判定：只认"目录前缀 + 路径"，并统一反斜杠为正斜杠
def normalize_ref(raw: str) -> str:
    return raw.replace("\\", "/").rstrip(".,;:!?)]}>》。，、；：！？").lstrip("./")


def ref_depth(ref: str) -> int:
    """引用的路径层级（按 Path.parts 计算，不数字符串里的斜杠）。

    旧体系用 `r.count("/") > 1` 判深度，在 Windows 反斜杠路径上会静默失真。
    """
    return len([p for p in Path(normalize_ref(ref)).parts if p not in ("", ".")])
