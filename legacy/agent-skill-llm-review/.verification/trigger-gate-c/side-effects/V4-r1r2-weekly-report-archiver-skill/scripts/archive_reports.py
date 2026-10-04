#!/usr/bin/env python3
"""批量归档周报脚本。

用法:
    python archive_reports.py <源文件或目录...> --root weekly-reports [--week 2026-W40] [--author 姓名]

行为:
    - 解析输入文件（.md/.txt/.docx），推断作者与 ISO 周期
    - 复制为 <root>/<年>/W<周>/<作者>_周报_<周期截止日>.md
    - 同名归档已存在时，旧版保留为 *.bak.<今日日期>
    - 生成/更新该周的 INDEX.md
    - 无法推断作者或周期的文件跳过并列出，供人工确认
"""

import argparse
import datetime
import re
import shutil
import sys
from pathlib import Path

SUPPORTED_EXTS = {".md", ".txt", ".docx"}

# 从文件名推断作者的常见模式: 张三_周报_2026-09-25.docx / 周报-张三-0925.md
NAME_PATTERNS = [
    re.compile(r"^(?P<name>[\u4e00-\u9fa5A-Za-z·]+?)[_\- ]*(?:周报|weekly)", re.I),
    re.compile(r"(?:周报|weekly)[_\- ]*(?P<name>[\u4e00-\u9fa5A-Za-z·]+)", re.I),
]
DATE_PATTERN = re.compile(r"(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})")


def infer_week(target_date: datetime.date) -> tuple[int, int]:
    """返回 (ISO 年, ISO 周号)，周期截止日取该周周五。"""
    iso = target_date.isocalendar()
    friday = datetime.date.fromisocalendar(iso.year, iso.week, 5)
    fiso = friday.isocalendar()
    return fiso.year, fiso.week


def parse_one(path: Path, force_week: str | None, force_author: str | None):
    """从文件名/内容推断 (作者, iso_year, iso_week, 截止日)。返回 None 表示需人工确认。"""
    stem = path.stem
    author = force_author
    week_str = force_week
    anchor_date = None

    if not author:
        for pat in NAME_PATTERNS:
            m = pat.search(stem)
            if m:
                author = m.group("name").strip("_- ")
                break

    m = DATE_PATTERN.search(stem)
    if m:
        try:
            anchor_date = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            anchor_date = None

    if week_str:
        mw = re.fullmatch(r"(\d{4})-?W(\d{1,2})", week_str, re.I)
        if not mw:
            print(f"[跳过] --week 格式应为 2026-W40: {week_str}", file=sys.stderr)
            return None
        iso_year, iso_week = int(mw.group(1)), int(mw.group(2))
        due = datetime.date.fromisocalendar(iso_year, iso_week, 5)
    elif anchor_date:
        iso_year, iso_week = infer_week(anchor_date)
        due = datetime.date.fromisocalendar(iso_year, iso_week, 5)
    else:
        due = None
        iso_year = iso_week = None

    if not author or iso_week is None:
        return None
    return author, iso_year, iso_week, due


def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        try:
            from docx import Document  # type: ignore

            return "\n".join(p.text for p in Document(str(path)).paragraphs)
        except Exception as e:
            print(f"[警告] 读取 docx 失败，仅归档不解析: {path.name} ({e})", file=sys.stderr)
            return ""
    return path.read_text(encoding="utf-8", errors="replace")


def first_topic(text: str) -> str:
    """取正文第一个非空、非标题行作为一句话主题。"""
    for line in text.splitlines():
        s = line.strip().lstrip("#-*> ").strip()
        if s:
            return s[:50]
    return ""


def archive(files: list[Path], root: Path, force_week: str | None, force_author: str | None, today: datetime.date):
    root.mkdir(parents=True, exist_ok=True)
    archived: list[tuple[str, Path, str]] = []
    skipped: list[Path] = []

    for f in files:
        if f.suffix.lower() not in SUPPORTED_EXTS or not f.is_file():
            continue
        info = parse_one(f, force_week, force_author)
        if info is None:
            skipped.append(f)
            continue
        author, y, w, due = info
        dest_dir = root / str(y) / f"W{w}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{author}_周报_{due.isoformat()}{f.suffix.lower()}"
        if dest.exists():
            backup = dest.with_suffix(f"{dest.suffix}.bak.{today.isoformat()}")
            shutil.copy2(dest, backup)
            print(f"[备份] {dest.name} -> {backup.name}")
        shutil.copy2(f, dest)
        text = extract_text(f)
        archived.append((author, dest, first_topic(text)))
        print(f"[归档] {f.name} -> {dest.relative_to(root.parent)}")

    # 生成 INDEX.md（按已归档的最后一个周目录）
    if archived:
        last_dir = archived[-1][1].parent
        index = last_dir / "INDEX.md"
        rows = [f"| {a} | `{p.name}` | {t or '—'} |" for a, p, t in archived if p.parent == last_dir]
        index.write_text(
            f"# 周报索引 {last_dir.name}\n\n| 姓名 | 文件 | 一句话主题 |\n|---|---|---|\n" + "\n".join(rows) + "\n",
            encoding="utf-8",
        )
        print(f"[索引] {index}")

    if skipped:
        print("\n[待确认] 以下文件无法推断作者或周期，请用 --author/--week 补充后重跑:")
        for s in skipped:
            print(f"  - {s}")


def main():
    ap = argparse.ArgumentParser(description="批量归档团队周报")
    ap.add_argument("inputs", nargs="+", help="源文件或目录")
    ap.add_argument("--root", default="weekly-reports", help="归档库根目录")
    ap.add_argument("--week", help="强制周期，如 2026-W40")
    ap.add_argument("--author", help="强制作者（单文件时用）")
    args = ap.parse_args()

    files: list[Path] = []
    for i in args.inputs:
        p = Path(i)
        if p.is_dir():
            files.extend(sorted(p.iterdir()))
        else:
            files.append(p)

    archive(files, Path(args.root), args.week, args.author, datetime.date.today())


if __name__ == "__main__":
    main()
