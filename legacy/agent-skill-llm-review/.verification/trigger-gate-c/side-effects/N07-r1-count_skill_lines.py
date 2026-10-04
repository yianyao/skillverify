#!/usr/bin/env python3
"""统计文件夹内所有 SKILL.md 的行数，并按大小（行数或字节）排序输出。"""

import argparse
from pathlib import Path


def find_skill_files(root: Path):
    """递归查找 root 下所有名为 SKILL.md 的文件。"""
    return sorted(root.rglob("SKILL.md"))


def count_lines(path: Path) -> int:
    """统计文件行数；无法按 UTF-8 解码时退回二进制方式按换行符计数。"""
    try:
        with path.open("r", encoding="utf-8") as f:
            return sum(1 for _ in f)
    except UnicodeDecodeError:
        with path.open("rb") as f:
            return f.read().count(b"\n") + (1 if f.seekable() and path.stat().st_size else 0)


def main():
    parser = argparse.ArgumentParser(description="统计文件夹内所有 SKILL.md 的行数并排序输出")
    parser.add_argument("folder", type=Path, help="要扫描的目标文件夹")
    parser.add_argument("--by-size", action="store_true", help="按文件字节大小排序（默认按行数排序）")
    args = parser.parse_args()

    if not args.folder.is_dir():
        parser.error(f"不是有效的文件夹: {args.folder}")

    results = []
    for path in find_skill_files(args.folder):
        lines = count_lines(path)
        size = path.stat().st_size
        results.append((path, lines, size))

    key = (lambda r: r[2]) if args.by_size else (lambda r: r[1])
    results.sort(key=key, reverse=True)

    if not results:
        print("未找到任何 SKILL.md 文件。")
        return

    width = max(len(str(r[0])) for r in results)
    print(f"{'行数':>8}  {'字节':>10}  文件路径")
    print("-" * (width + 24))
    for path, lines, size in results:
        print(f"{lines:>8}  {size:>10}  {path}")

    total_lines = sum(r[1] for r in results)
    print("-" * (width + 24))
    print(f"共 {len(results)} 个文件，总计 {total_lines} 行")


if __name__ == "__main__":
    main()
