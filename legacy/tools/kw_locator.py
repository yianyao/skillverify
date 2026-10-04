#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kw_locator.py — B3-1 关键词定位器（§8.3.10 → W-08 定位段落供给）。

为 W-08（破坏性操作防护 L 评审）产出"定位段落"：检索技能内破坏性关键词命中，
逐处给出 文件:行 + 行文本 + ±2 行上下文 + 代码文件防护旗标在场性标注。
取代 v1.4 提示词清单 W-08 的"S 关键词定位器缺位"降级路径（评审员自定位）。

检查项:
  L-1 定位        SKILL.md 正文 + 文本文件逐行扫描（词表复用 security_scan
                  V8-5 DESTRUCTIVE_WORD_RE——§8.3.10 示例清单单一来源）
  L-2 防护标注    代码文件级 --confirm/--force/--dry-run 在场性——仅标注不判定，
                  判定归 W-08 L/H（本工具与 security_scan V8-5 分工：其门禁阻断，
                  本工具供给上下文段落）
  L-3 零命中声明  全域零命中 → 输出"定位段落为空"声明（W-08 降级句触发口径）

性质: 信息供给工具（非门禁）——无 FAIL 语义，exit 2 恒不出现（显式声明，
      与门禁族 0/1/2 的差异为设计决策而非缺口）。
用法: python kw_locator.py <skill_dir> [--out 报告路径]
退出码: 0=报告产出（无论命中与否）；1=参数/IO 错误（带用法）。
扫描口径: 跳过目录/符号链接（含指向文件的——防出界跟随）/二进制与不可解码文件
      （UnicodeDecodeError/OSError）/大于 MAX_FILE_BYTES(512KB) 的文件；报告头
      记"扫描 N 文件"为实际解码成功数，被跳过文件不计入且不单独列出。
      词表来源 security_scan 缺位/改名 → exit 1（词表导入失败）——不静默：
      若降级为空结果会被误读为"零命中"假声明，违反 L-3 语义。

版本: v1.0.1（2026-10-03 复检）— security_scan 导入失败显式 exit 1（原 ImportError
      崩栈；评审建议的"返空列表"会伪造 L-3 零命中声明，不采纳）+ docstring 声明
      扫描口径；v1.0 2026-10-03 建成——S 类补齐收官：B3-1 关键词定位器
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

VERSION = "v1.0.1"
TOOLS_DIR = Path(__file__).resolve().parent

SKIP_DIR_NAMES = {".git", ".verification", "__pycache__", "node_modules",
                  ".workbuddy", ".idea", ".vscode"}
CODE_SUFFIXES = {".py", ".sh", ".bash", ".js", ".ts", ".mjs", ".cjs", ".ps1",
                 ".psm1", ".rb", ".pl", ".bat", ".cmd"}
MAX_FILE_BYTES = 512 * 1024


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


def _scan_files(skill_dir: Path) -> list[tuple[Path, bool]]:
    """收集待扫文本文件 (路径, 是否代码文件)。符号链接与超限文件跳过。"""
    out: list[tuple[Path, bool]] = []
    for p in sorted(skill_dir.rglob("*")):
        if p.is_dir() or p.is_symlink() or not p.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in p.relative_to(skill_dir).parts):
            continue
        if p.stat().st_size > MAX_FILE_BYTES:
            continue
        out.append((p, p.suffix.lower() in CODE_SUFFIXES))
    return out


def locate(skill_dir: Path) -> tuple[list[dict], int, int]:
    """L-1/L-2 扫描。返回 (命中列表, 扫描文件数, 代码文件数)。

    命中 = dict(rel, line, kw, text, ctx, code, protected)。
    """
    sys.path.insert(0, str(TOOLS_DIR))
    from security_scan import DESTRUCTIVE_WORD_RE, PROTECTION_FLAGS  # noqa: PLC0415

    hits: list[dict] = []
    n_files = n_code = 0
    for path, code in _scan_files(skill_dir):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # 二进制/不可解码文件不入扫描
        n_files += 1
        n_code += 1 if code else 0
        protected = [f for f in PROTECTION_FLAGS if f in text] if code else []
        lines = text.splitlines()
        for i, ln in enumerate(lines):
            for m in DESTRUCTIVE_WORD_RE.finditer(ln):
                hits.append(dict(
                    rel=path.relative_to(skill_dir).as_posix(),
                    line=i + 1, kw=m.group(0).lower(),
                    text=_flat(ln.strip()),
                    ctx=[_flat(x.strip()) for x in
                         lines[max(0, i - 2):i + 3]],
                    code=code,
                    protected=list(protected)))
    return hits, n_files, n_code


def build_report(skill_dir: Path, hits: list[dict],
                 n_files: int, n_code: int) -> str:
    """L-3 + 报告拼装。零命中输出"定位段落为空"声明（W-08 降级句触发口径）。"""
    lines = [f"# B3-1 关键词定位报告（kw_locator.py {VERSION}）", "",
             f"- 技能: {skill_dir}",
             "- 定位方式: S 定位器（kw_locator "
             f"{VERSION}，词表复用 security_scan V8-5 / §8.3.10 示例清单）",
             f"- 扫描: {n_files} 文本文件（代码 {n_code}）", ""]
    if not hits:
        lines += ["## 定位段落", "",
                  "**定位段落为空**——全域零命中破坏性关键词。",
                  "W-08 无需降级（无目标），或按降级句口径声明"
                  "\"定位方式：S 定位器（零命中）\"。", ""]
        lines += ["## 结论", "", "命中 0 处。", ""]
        return "\n".join(lines)

    lines.append("## 定位段落")
    for i, h in enumerate(hits, 1):
        flag = ("已有防护 " + ",".join(h["protected"])) if h["protected"] \
            else "无 --confirm/--force/--dry-run（防护判定归 W-08）"
        kind = "代码" if h["code"] else "正文"
        lines += ["", f"### 命中 {i}: {h['rel']}:{h['line']}"
                     f"（关键词 {h['kw']}；{kind}；{flag}）", ""]
        for c in h["ctx"]:
            lines.append(f"> {c}" if c else ">")
    n_code_hit = sum(1 for h in hits if h["code"])
    lines += ["", "## 结论", "",
              f"命中 {len(hits)} 处（代码 {n_code_hit} / 正文 {len(hits) - n_code_hit}）；"
              "以上段落供 W-08 判定防护与风险相称性（L/H 终审）。", ""]
    return "\n".join(lines)


def main() -> int:
    ap = _BlockArgParser(
        description="B3-1 关键词定位器（§8.3.10 → W-08 定位段落供给；信息供给非门禁，"
                    "无 FAIL 语义）")
    ap.add_argument("skill_dir", help="待定位技能根目录（含 SKILL.md）")
    ap.add_argument("--out", help="报告落盘路径（建议 .verification/b3-s/kw-locate.md）")
    a = ap.parse_args()

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
        hits, n_files, n_code = locate(skill_dir)
    except ImportError as e:
        # 词表来源缺位不静默——返空结果会伪造 L-3"零命中"声明
        print(f"错误: 词表导入失败（security_scan 缺位/改名？）：{e}\n"
              "下一步: 核对 tools/security_scan.py 在位后重试。",
              file=sys.stderr)
        return 1
    except OSError as e:
        print(f"错误: 扫描失败 {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    report = build_report(skill_dir, hits, n_files, n_code)
    print(report, end="")
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
