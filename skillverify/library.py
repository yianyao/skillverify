"""library —— 库级（多技能组合）检查：元数据预算与描述词面重叠。

为什么单独一个模块：`discover` 的 `DISC-*` 管的是"能不能发现技能"，而这里管的是
**把整个已安装的技能集合当成一个整体**来看的两件事——它们不属于任何单个技能，
放在 lint（单技能）或 discover（发现机制）里都会让那两处的语义变浑。

两条规则都是 **WARN 级提示**，不是判定：
- `LIB-001` 元数据预算：宿主启动时会把所有技能的 name+description 一起读进上下文。
  总量超了，某些技能会被宿主**静默丢弃**（不报错、不提示、就是不生效）。
- `LIB-002` 描述词面高度重叠：两个技能的描述用词高度重合 → 触发时互相抢。
  这是"触发盗窃"里**可机械发现的那一半**（另一半是语义相似，需要模型，本项目不做）。

口径必须写明，不能让人以为这是官方硬线：
- 预算默认 8000 字符，**本项目约定**（可用 `--metadata-budget` 覆盖）；真实上限由宿主决定；
- 只计 `len(name) + len(description)`，**不含**宿主自身的包装开销（那部分不可知）；
- 重叠用字符 bigram + 词元的重叠系数（CJK 友好、纯标准库），**不是**语义相似度。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .report import FAIL, INFO, PASS, WARN, Result, Rule
from .spec import load_skill

_LEGACY = "旧体系《Agent-Skill 生命周期验证方案》v1.3（V2 命名冲突预检；上下文预算）"

#: 元数据预算默认值（**本项目约定，非官方硬约束**）
DEFAULT_METADATA_BUDGET = 8000

#: 词面重叠的默认阈值（重叠系数）与最小词元数
DEFAULT_OVERLAP = 0.5
MIN_TOKENS = 8

#: 说明里常见的功能词：它们几乎出现在每个描述里，计分只会制造噪声
STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "for", "to", "of", "in", "on", "with", "use", "uses",
    "used", "when", "this", "that", "it", "is", "are", "be", "by", "as", "at", "from",
    "skill", "skills", "agent", "user", "users", "you", "your", "can", "will", "help",
    "helps", "create", "creates", "any", "all", "into", "out", "not", "no", "if", "then",
    "支持", "使用", "用于", "一个", "这个", "可以", "需要", "以及", "或者", "进行", "技能",
    "时候", "如果", "那么", "已经", "并且", "包含", "提供", "生成", "处理", "任务",
})

RULES: dict[str, Rule] = {
    "LIB-001": Rule(
        "LIB-001",
        f"库内元数据总量不超过预算（默认 {DEFAULT_METADATA_BUDGET} 字符）",
        "HOUSE",
        _LEGACY,
        "宿主启动时会把所有技能的 name+description 一起读入；总量超限时某些技能会被"
        "**静默丢弃**（不报错，就是不生效）。精简描述、合并同类技能，"
        "或用 `--metadata-budget` 按你的宿主实测值调整这个口径",
    ),
    "LIB-002": Rule(
        "LIB-002",
        "技能描述之间没有高度词面重叠（可能互相抢触发）",
        "HOUSE",
        _LEGACY,
        "两个技能的描述用词高度重合时，触发会互相抢。让每个描述点明**本技能独有**的能力与"
        "边界（何时用它、何时不用它）；确实同类的，合并成一个技能",
    ),
}


def _res(rule: Rule, status: str, evidence: str = "") -> Result:
    return Result(rid=rule.rid, title=rule.title, status=status, level=rule.level,
                  evidence=evidence,
                  remediation=rule.remediation if status in (FAIL, WARN) else "")


# --------------------------------------------------------------------------- #
# LIB-001 元数据预算
# --------------------------------------------------------------------------- #


@dataclass
class SkillMetadata:
    """一个技能在宿主启动时会被读到的元数据。"""

    name: str
    description: str
    path: Path

    @property
    def size(self) -> int:
        return len(self.name) + len(self.description)


def collect_metadata(skills) -> list[SkillMetadata]:
    """读出一批技能的 name/description（读不出的按 0 计，由 spec 阶段另行报错）。"""
    out: list[SkillMetadata] = []
    for ref in skills:
        doc = load_skill(Path(ref.path))
        out.append(SkillMetadata(name=doc.name or ref.name,
                                 description=doc.description, path=Path(ref.path)))
    return out


def check_metadata_budget(skills, *, budget: int = DEFAULT_METADATA_BUDGET,
                          top: int = 5) -> Result:
    """库级元数据预算。**始终给出总量与主要贡献者**（这本身就是那个"组合视图"）。"""
    items = collect_metadata(skills)
    if not items:
        return _res(RULES["LIB-001"], INFO, "没有技能可统计")
    items.sort(key=lambda item: item.size, reverse=True)
    total = sum(item.size for item in items)
    biggest = "、".join(f"{item.name}({item.size})" for item in items[:top])
    head = (f"{len(items)} 个技能的 name+description 合计 {total} 字符"
            f"（预算 {budget}；只计 name+description，不含宿主包装开销）；"
            f"最大贡献：{biggest}")
    if total > budget:
        over = total - budget
        return _res(RULES["LIB-001"], WARN,
                    f"{head}。**超出 {over} 字符**：宿主若按预算截断，"
                    f"排在后面的技能会被静默丢弃（不报错、不生效）")
    return _res(RULES["LIB-001"], PASS, f"{head}；余量 {budget - total} 字符")


# --------------------------------------------------------------------------- #
# LIB-002 描述词面重叠
# --------------------------------------------------------------------------- #


_WORD_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+")


def tokens(text: str) -> set[str]:
    """把描述切成可比对的词元集合：ASCII 词 + CJK 字符 bigram。

    CJK 没有空格，按字符 bigram 近似"词"；纯标准库、离线、确定性。
    """
    normalized = unicodedata.normalize("NFKC", text).lower()
    out: set[str] = set()
    for word in _WORD_RE.findall(normalized):
        if word not in STOPWORDS and len(word) > 1:
            out.add(word)
    for chunk in _CJK_RE.findall(normalized):
        grams = [chunk[i:i + 2] for i in range(max(len(chunk) - 1, 1))]
        for gram in grams:
            if gram not in STOPWORDS:
                out.add(gram)
    return out


def overlap(a: set[str], b: set[str]) -> tuple[float, list[str]]:
    """重叠系数与共同词元。

    用重叠系数（交集 / 较小集合）而不是 Jaccard：两个技能描述一长一短时，
    Jaccard 会被长度差冲淡，而"短描述整个被长描述覆盖"恰恰是最该提示的情形。
    """
    if not a or not b:
        return 0.0, []
    shared = a & b
    return len(shared) / min(len(a), len(b)), sorted(shared)


def check_description_overlap(skills, *, threshold: float = DEFAULT_OVERLAP,
                              top: int = 5) -> Result:
    """两两比对描述词面重叠，只报**最像的几对**（WARN），并列出共同词元。"""
    items = collect_metadata(skills)
    if len(items) < 2:
        return _res(RULES["LIB-002"], INFO, "技能不足 2 个，无需比对描述重叠")
    token_sets = [(item, tokens(item.description)) for item in items]
    # 词元太少的描述**不参与比对**：`Do A.` 与 `Do B.` 的词元集合几乎相同，
    # 算出来就是 100% 重叠——那是噪声，不是"可能互相抢触发"。
    # （这个 guard 早先只写在备注里、没用于过滤，等于没起作用。）
    comparable = [(item, toks) for item, toks in token_sets if len(toks) >= MIN_TOKENS]
    short = [item.name for item, toks in token_sets if len(toks) < MIN_TOKENS]

    pairs: list[tuple[float, str, str, list[str]]] = []
    for i, (left, ltok) in enumerate(comparable):
        for right, rtok in comparable[i + 1:]:
            score, shared = overlap(ltok, rtok)
            if score >= threshold:
                pairs.append((score, left.name, right.name, shared[:8]))
    pairs.sort(reverse=True)

    if not pairs:
        note = f"（{len(comparable)} 个技能参与两两比对，阈值 {threshold}）"
        if short:
            note += (f"；词元不足 {MIN_TOKENS}、无法可靠比对：{'、'.join(short[:5])}"
                     f"（描述写具体些才有比对价值）")
        if not comparable:
            return _res(RULES["LIB-002"], INFO,
                        f"所有技能的描述都太短（词元 < {MIN_TOKENS}），无法可靠比对："
                        f"{'、'.join(short[:5])}")
        return _res(RULES["LIB-002"], PASS, f"没有高度重叠的描述{note}")

    detail = "；".join(f"{a} ↔ {b}（{score:.0%}，共同词元：{'/'.join(shared)}）"
                       for score, a, b, shared in pairs[:top])
    tail = f"；词元不足未参与比对：{'、'.join(short[:3])}" if short else ""
    return _res(RULES["LIB-002"], WARN,
                f"{len(pairs)} 对描述高度重叠（阈值 {threshold}）：{detail}。"
                f"词面重叠不等于冲突，但这是最该人工看一遍的地方{tail}")


def run_library(skills, *, budget: int = DEFAULT_METADATA_BUDGET,
                overlap_threshold: float = DEFAULT_OVERLAP) -> list[Result]:
    """跑完两条库级检查，返回结果列表（供 discover/check 追加进库级报告）。"""
    return [
        check_metadata_budget(skills, budget=budget),
        check_description_overlap(skills, threshold=overlap_threshold),
    ]


__all__ = ["DEFAULT_METADATA_BUDGET", "DEFAULT_OVERLAP", "MIN_TOKENS", "RULES", "STOPWORDS",
           "SkillMetadata", "check_description_overlap", "check_metadata_budget",
           "collect_metadata", "overlap", "run_library", "tokens"]
