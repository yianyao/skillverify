"""check_overlap.py —— 防自我应验查重（建议性 WARN，不阻断）。

同一个模型既写技能 description 又写 trigger-queryset 时，查询容易不自觉复用
描述词句，导致触发率被测得虚高、评测集失去代表性。本脚本对每条查询与
description 做词面重叠检查（ASCII 词 + CJK 字符 bigram，纯标准库）：

- 共享领域词是正常的（查询本来就该命中技能领域）；
- 重叠系数过高 = 整句几乎是描述的改写，需要改写成"用户会怎么说"的口吻。

用法：python check_overlap.py <skill-dir>
退出码：0 正常（含有 WARN 的情况）；2 输入问题（找不到文件等）。
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

#: 词元数低于该值的查询不参与比对（太短的查询没有比对价值）
MIN_TOKENS = 6

#: 重叠系数告警阈值（交集 / 较小集合；与 specSkill 的 LIB-002 同一口径）
THRESHOLD = 0.6

_WORD_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+")


def tokens(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    out: set[str] = set()
    for word in _WORD_RE.findall(normalized):
        if len(word) > 1:
            out.add(word)
    for chunk in _CJK_RE.findall(normalized):
        out.update(chunk[i:i + 2] for i in range(max(len(chunk) - 1, 1)))
    return out


def overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def read_description(skill_md: Path) -> str:
    """从 frontmatter 取 description（单行标量；折叠块取首行——本脚本只做建议性检查）。"""
    text = skill_md.read_text(encoding="utf-8")
    match = re.search(r"^---\s*\n(.*?)\n---", text, re.S)
    if not match:
        return ""
    for line in match.group(1).splitlines():
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return ""


USAGE = "用法: python check_overlap.py <skill-dir>"


def main() -> int:
    if "-h" in sys.argv or "--help" in sys.argv:
        print("check_overlap.py —— 防自我应验查重（建议性 WARN，不阻断）")
        print(USAGE)
        print("参数: <skill-dir>  目标技能目录（内含 SKILL.md 与 evals/trigger-queryset.json）")
        print("退出码: 0 正常（含有 WARN 的情况）; 2 输入问题（找不到文件等）")
        return 0
    if len(sys.argv) != 2:
        print(USAGE)
        return 2
    root = Path(sys.argv[1])
    skill_md = next((root / name for name in ("SKILL.md", "skill.md")
                     if (root / name).is_file()), None)
    if skill_md is None:
        print(f"FAIL 找不到 {root}/SKILL.md")
        return 2
    qs_path = root / "evals" / "trigger-queryset.json"
    if not qs_path.is_file():
        print(f"FAIL 找不到 {qs_path}")
        return 2
    try:
        data = json.loads(qs_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"FAIL trigger-queryset.json 解析失败：{exc}")
        return 2

    description = read_description(skill_md)
    if not description:
        print("FAIL frontmatter 里读不到 description")
        return 2
    dtok = tokens(description)

    queries = data.get("queries", [])
    warned = 0
    for query in queries:
        qtok = tokens(query.get("query", ""))
        if len(qtok) < MIN_TOKENS:
            continue
        score = overlap(qtok, dtok)
        if score >= THRESHOLD:
            warned += 1
            print(f"WARN {query.get('id')}: 与 description 词面重叠 {score:.0%}"
                  f"——疑似照抄描述而非用户口吻，考虑改写")
    if warned == 0:
        print(f"OK {len(queries)} 条查询与 description 无高度词面重合"
              f"（阈值 {THRESHOLD}，只做建议性提示）")
    else:
        print(f"共 {warned}/{len(queries)} 条需要人工改写（建议性，不阻断）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
