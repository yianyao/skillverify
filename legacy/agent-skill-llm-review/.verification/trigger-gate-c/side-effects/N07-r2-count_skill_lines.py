#!/usr/bin/env python3
"""统计指定文件夹内所有 SKILL.md 的行数，并按行数从大到小排序输出。

用法:
    python count_skill_lines.py <文件夹路径>
"""
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        print(f"用法: python {Path(sys.argv[0]).name} <文件夹路径>")
        sys.exit(1)

    root = Path(sys.argv[1])
    if not root.is_dir():
        print(f"错误: {root} 不是有效的文件夹路径")
        sys.exit(1)

    # 递归查找所有名为 SKILL.md 的文件（不区分大小写）
    results = [
        (f, len(f.read_text(encoding="utf-8", errors="ignore").splitlines()))
        for f in root.rglob("*")
        if f.is_file() and f.name.upper() == "SKILL.MD"
    ]

    if not results:
        print("未找到任何 SKILL.md 文件")
        return

    # 按行数从大到小排序
    results.sort(key=lambda x: x[1], reverse=True)

    total = 0
    print(f"{'行数':>8}  路径")
    print("-" * 60)
    for path, lines in results:
        print(f"{lines:>8}  {path}")
        total += lines
    print("-" * 60)
    print(f"共 {len(results)} 个文件，总计 {total} 行")


if __name__ == "__main__":
    main()
