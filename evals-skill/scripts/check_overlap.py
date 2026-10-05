"""check_overlap.py —— 防自我应验查重（建议性 WARN，不阻断）。

同一个模型既写技能 description 又写 trigger-queryset 时，查询容易不自觉复用
描述词句，导致触发率被测得虚高、评测集失去代表性。本脚本对每条查询与
description 做词面重叠检查（ASCII 词 + CJK 字符 bigram，纯标准库）：

- 共享领域词是正常的（查询本来就该命中技能领域）；
- 重叠系数过高 = 整句几乎是描述的改写，需要改写成「用户会怎么说」的口吻。

**三类「未比对」必须说出来**（本项目铁律：没检查不许伪装成通过）：
1. `queries` 为空或缺失；
2. description 词元太少（低于 `MIN_DESCRIPTION_TOKENS`）——短描述下这个指标本身不稳定；
3. 某些查询词元太少（低于 `MIN_TOKENS`）被跳过。
以上都按「未比对」披露，并给出**实际参与比对的条数**，不输出「无高度词面重合」。

用法：python check_overlap.py <技能目录>
退出码：0 正常（可能含 WARN）；2 输入问题（找不到文件、JSON 坏、字段类型不对…）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

#: 词元数低于该值的查询不参与比对（太短的查询没有比对价值）
MIN_TOKENS = 6

#: description 词元数低于该值时整体不比对：短描述下 min() 口径摆动大，
#: 硬比会同时产生误报（T12 实测：`csv 报表` + 合法提问 → 100% 重叠）
MIN_DESCRIPTION_TOKENS = 10

#: 重叠系数告警阈值（交集 / 较小集合）。
#: 注意：与 `LIB-002` **同公式但更严**（LIB-002 用 0.5）——本脚本定位是建议性提示，
#: 宁可多提醒。别写成「同一口径」，那是两回事。
THRESHOLD = 0.6

WORD_RE = re.compile(r"[a-z0-9]+")
CJK_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+")


def tokens(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    out: set[str] = set()
    for word in WORD_RE.findall(normalized):
        if len(word) > 1:
            out.add(word)
    for chunk in CJK_RE.findall(normalized):
        out.update(chunk[i:i + 2] for i in range(max(len(chunk) - 1, 1)))
    return out


def overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


class InputError(Exception):
    """输入问题（对应退出码 2）。"""


def read_description(skill_md: Path) -> str:
    """从 frontmatter 取 description。

    支持单行标量、引号标量，以及官方的**折叠/字面块**（`>-` / `>-` 缩进续行 / `|`）——
    早先只取冒号后那一截，`description: >-` 会原样返回 `>-`，于是整个查重**静默失效**。
    """
    text = skill_md.read_text(encoding="utf-8")
    match = re.search(r"^---\s*\n(.*?)\n---", text, re.S)
    if not match:
        return ""
    lines = match.group(1).splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("description:"):
            continue
        inline = line.split(":", 1)[1].strip()
        if inline and not inline.startswith((">", "|")):
            return inline.strip("\"'")
        # 块标量：把后续更深的缩进行拼起来
        parts: list[str] = []
        for follow in lines[index + 1:]:
            if not follow.strip():
                parts.append("")
                continue
            if not follow.startswith((" ", "\t")):
                break
            parts.append(follow.strip())
        return " ".join(p for p in parts if p).strip()
    return ""


def load_queries(path: Path) -> list[dict]:
    """读查询集并**校验类型**（早先 `{"query": 123}` 会抛 TypeError 直接崩）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputError(f"trigger-queryset.json 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise InputError("trigger-queryset.json 顶层必须是对象")
    queries = data.get("queries")
    if queries is None:
        raise InputError("trigger-queryset.json 里没有 queries 字段")
    if not isinstance(queries, list):
        raise InputError(f"queries 必须是数组（实为 {type(queries).__name__}）")
    for index, item in enumerate(queries, 1):
        if not isinstance(item, dict):
            raise InputError(f"第 {index} 条查询必须是对象（实为 {type(item).__name__}）")
        if not isinstance(item.get("query"), str):
            raise InputError(f"第 {index} 条查询的 query 必须是字符串"
                             f"（实为 {type(item.get('query')).__name__}）")
    return queries


def check(root: Path) -> int:
    skill_md = next((root / name for name in ("SKILL.md", "skill.md")
                     if (root / name).is_file()), None)
    if skill_md is None:
        raise InputError(f"找不到 {root}/SKILL.md")
    qs_path = root / "evals" / "trigger-queryset.json"
    if not qs_path.is_file():
        raise InputError(f"找不到 {qs_path}")
    queries = load_queries(qs_path)

    description = read_description(skill_md)
    if not description:
        raise InputError("frontmatter 里读不到 description")
    dtok = tokens(description)
    if not dtok:
        raise InputError(f"description 读完只剩标点/空白（原文：{description[:40]!r}）")

    if len(dtok) < MIN_DESCRIPTION_TOKENS:
        # 短描述：指标本身不稳定 → 明确说「未比对」，不给任何"没问题"的暗示
        print(f"SKIP 未比对：description 词元仅 {len(dtok)} 个"
              f"（低于 {MIN_DESCRIPTION_TOKENS}）——短描述下该指标摆动大，不硬比")
        print(f"     建议：把 description 写具体些（做什么 + 何时触发），再加查询集")
        return 0

    compared = skipped = warned = 0
    for item in queries:
        qtok = tokens(item["query"])
        if len(qtok) < MIN_TOKENS:
            skipped += 1
            print(f"SKIP {item.get('id')}: 查询词元仅 {len(qtok)} 个（低于 {MIN_TOKENS}），未参与比对")
            continue
        compared += 1
        score = overlap(qtok, dtok)
        if score >= THRESHOLD:
            warned += 1
            print(f"WARN {item.get('id')}: 与 description 词面重叠 {score:.0%}"
                  f"——疑似照抄描述而非用户口吻，考虑改写")

    # 只有真比对过才允许说"没发现重合"；一条都没比对上就是「未比对」
    if compared == 0:
        print(f"SKIP 未比对：{len(queries)} 条查询没有一条达到 {MIN_TOKENS} 个词元"
              f"（全部跳过）——这不是「无重合」")
        return 0
    if warned == 0:
        print(f"OK 已比对 {compared} 条查询，未发现高度词面重合"
              f"（阈值 {THRESHOLD}，另跳过 {skipped} 条；建议性提示，不阻断）")
    else:
        print(f"共 {warned}/{compared} 条需要人工改写"
              f"（另跳过 {skipped} 条；建议性，不阻断）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_overlap.py",
        description="防自我应验查重：检查触发查询是否照抄了 description（建议性，不阻断）",
        epilog="退出码：0 正常（可能含 WARN/SKIP）；2 输入问题。",
    )
    parser.add_argument("skill_dir", help="技能目录（需含 SKILL.md 与 evals/trigger-queryset.json）")
    args = parser.parse_args(argv)

    try:
        return check(Path(args.skill_dir))
    except InputError as exc:
        print(f"FAIL {exc}")
        return 2
    except OSError as exc:
        print(f"FAIL 读取失败：{exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
