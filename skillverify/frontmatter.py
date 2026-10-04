"""frontmatter —— SKILL.md 的 YAML frontmatter 解析（纯标准库，零依赖）。

为什么不依赖 PyYAML：
1. 本项目要求"装在哪个宿主下都能用"，外部依赖越少越好；
2. 官方校验器用的 strictyaml 只支持 YAML 的受限子集，我们要对齐的是**它**，
   而不是完整 YAML；
3. Agent Skill 的 frontmatter 实际只会用到很小的 YAML 子集。

支持的子集（覆盖官方规范允许的全部 6 个字段所需的写法）：
- 顶层 `key: value` 标量；值可加单/双引号，可用 YAML 转义
- 顶层 `key:` 后接缩进的**映射**（用于 metadata）
- YAML 块标量 `key: |` / `key: >`（多行值）
- 注释行（`#` 开头）与空行
- 行内 flow 映射 `{a: b, c: d}`（用于 metadata 的单行写法）

明确**不支持**（遇到即报错，与 strictyaml 的"严格"取向一致）：
- 序列（`- item`）、锚点/别名、多文档（`---` 分隔多份）、复杂类型标签

字段类型处理与官方 parser 一致：`metadata` 的值会被强制转为字符串。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

FM_DELIMITER = "---"
_KEY_RE = re.compile(r"^([A-Za-z0-9_.\-]+)\s*:\s*(.*)$")
_FLOW_MAP_RE = re.compile(r"^\{(.*)\}$")


class FrontmatterError(Exception):
    """frontmatter 结构性错误（无法解析）。"""


@dataclass
class Frontmatter:
    """解析结果。

    data      顶层键 -> 值（值可能是 str，或 metadata 这类 dict）
    body      frontmatter 之后的正文（已 strip 两端空白）
    raw       原始 frontmatter 文本（不含分隔行）
    start_line / end_line  在文件中的行号（1 基），便于报告定位
    """

    data: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    raw: str = ""
    start_line: int = 0
    end_line: int = 0

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.data


#: 双引号标量里支持的转义（YAML 的子集）
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", '"': '"', "\\": "\\",
            "/": "/", "b": "\b", "f": "\f"}


def _unescape_double(inner: str) -> str:
    """**单遍**从左到右解转义。

    早先实现是链式 `replace("\\n") .replace("\\t") … .replace("\\\\")`——
    顺序错了：`a\\\\nb` 里的第 3、4 个字符正好是 `\\n`，会被先换成换行，
    于是"字面反斜杠 + n"变成了换行。单遍扫描天然没有这个歧义。
    未知转义（YAML 里其实是错误）保守保留原样，不擅自吞掉反斜杠。
    """
    out: list[str] = []
    idx = 0
    while idx < len(inner):
        ch = inner[idx]
        if ch == "\\" and idx + 1 < len(inner):
            nxt = inner[idx + 1]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
                idx += 2
                continue
            out.append(ch)
            idx += 1
            continue
        out.append(ch)
        idx += 1
    return "".join(out)


def _coerce_scalar(value: str) -> str:
    """把标量值转成字符串，处理引号与转义。

    与官方 parser 的取向一致：所有标量最终都是字符串（因此 `version: 1.0`
    会变成 `"1.0"`，而不是浮点数）。
    """
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        inner = text[1:-1]
        if text[0] == '"':
            return _unescape_double(inner)
        # 单引号内 '' 表示一个 '
        return inner.replace("''", "'")
    return text


def _strip_comment(value: str) -> str:
    """去掉行尾注释：仅当 `#` 前是空白且不在引号内时才算注释。"""
    if value.lstrip().startswith("#"):
        return ""
    quote: str | None = None
    for idx, ch in enumerate(value):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            continue
        if ch == "#" and idx > 0 and value[idx - 1] in (" ", "\t"):
            return value[:idx]
    return value


def _parse_flow_map(text: str) -> dict[str, str]:
    """解析行内 flow 映射 `{a: b, c: d}`。"""
    inner = text.strip()[1:-1]
    result: dict[str, str] = {}
    for part in _split_flow_items(inner):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise FrontmatterError(f"行内映射项缺少冒号: {part!r}")
        key, _, val = part.partition(":")
        result[_coerce_scalar(key)] = _coerce_scalar(val)
    return result


def _split_flow_items(inner: str) -> list[str]:
    """按逗号切分行内映射项，忽略引号内的逗号。"""
    items: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            continue
        if ch == ",":
            items.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if buf:
        items.append("".join(buf))
    return items


def parse_frontmatter(text: str) -> Frontmatter:
    """解析 SKILL.md 全文，抽取 frontmatter 与正文。

    异常：FrontmatterError —— 结构不合法（未以 --- 开头、未闭合等）。
    语法层面的错误（如缺少冒号）也抛 FrontmatterError。
    """
    if text.startswith("\ufeff"):
        text = text[1:]

    lines = text.splitlines()
    if not lines or lines[0].strip() != FM_DELIMITER:
        raise FrontmatterError(
            "SKILL.md 必须以 YAML frontmatter 起始（文件首行须为 ---）"
        )

    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == FM_DELIMITER:
            end_idx = idx
            break
    if end_idx is None:
        raise FrontmatterError("frontmatter 未正确闭合（缺少结束的 --- 行）")

    fm_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1 :]).strip()
    data = _parse_block(fm_lines)

    return Frontmatter(
        data=data,
        body=body,
        raw="\n".join(fm_lines),
        start_line=2,
        end_line=end_idx + 1,
    )


def _parse_block(fm_lines: list[str]) -> dict[str, Any]:
    """解析 frontmatter 内的键值块（含嵌套映射与块标量）。"""
    data: dict[str, Any] = {}
    idx = 0
    total = len(fm_lines)

    while idx < total:
        raw_line = fm_lines[idx]
        stripped = raw_line.strip()

        # 空行与注释
        if not stripped or stripped.startswith("#"):
            idx += 1
            continue

        # 顶层键必须顶格（无前导空白）
        if raw_line[:1] in (" ", "\t"):
            raise FrontmatterError(
                f"第 {idx + 2} 行：出现无归属的缩进行（顶层键必须顶格）"
            )

        match = _KEY_RE.match(raw_line)
        if not match:
            raise FrontmatterError(
                f"第 {idx + 2} 行：不是合法的 `键: 值` 形式 —— {stripped!r}"
            )

        key, raw_value = match.group(1), _strip_comment(match.group(2)).strip()

        # 块标量：| 或 >
        if raw_value in ("|", ">", "|-", ">-", "|+", ">+"):
            literal = raw_value.startswith("|")
            kept_bare = raw_value.endswith("-")
            kept_all = raw_value.endswith("+")
            block: list[str] = []
            idx += 1
            while idx < total:
                nxt = fm_lines[idx]
                if nxt.strip() and nxt[:1] not in (" ", "\t"):
                    break
                block.append(nxt)
                idx += 1
            # 逐行 strip() 会吃掉**相对**缩进（块里的二级缩进是有意义的内容）；
            # 正确做法是去掉块内公共缩进，行内相对缩进原样保留。
            indents = [len(line) - len(line.lstrip(" ")) for line in block if line.strip()]
            common = min(indents) if indents else 0
            dedented = [line[common:] if line.strip() else "" for line in block]
            if literal:
                value = "\n".join(dedented)
            else:
                value = " ".join(part.strip() for part in dedented if part.strip())
            if kept_all:
                value += "\n"
            elif not kept_bare:
                value = value.rstrip("\n") + "\n"
            data[key] = value
            continue

        # 空值 + 后续缩进行 = 嵌套映射（metadata）
        if raw_value == "":
            nested: dict[str, str] = {}
            idx += 1
            while idx < total:
                nxt = fm_lines[idx]
                if not nxt.strip():
                    idx += 1
                    continue
                if nxt[:1] not in (" ", "\t"):
                    break
                sub = nxt.strip()
                sub_match = _KEY_RE.match(sub)
                if not sub_match:
                    raise FrontmatterError(
                        f"第 {idx + 2} 行：嵌套映射项不是合法的 `键: 值` —— {sub!r}"
                    )
                nested[_coerce_scalar(sub_match.group(1))] = _coerce_scalar(
                    _strip_comment(sub_match.group(2))
                )
                idx += 1
            # 与官方 parser 一致：metadata 的值统一转字符串
            data[key] = {str(k): str(v) for k, v in nested.items()}
            continue

        # 行内 flow 映射
        if _FLOW_MAP_RE.match(raw_value):
            data[key] = _parse_flow_map(raw_value)
            idx += 1
            continue

        data[key] = _coerce_scalar(raw_value)
        idx += 1

    return data
