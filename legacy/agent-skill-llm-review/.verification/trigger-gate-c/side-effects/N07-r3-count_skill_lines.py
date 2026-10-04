#!/usr/bin/env python3
"""统计文件夹内所有 SKILL.md 的行数并按行数排序输出。

用法:
    python count_skill_lines.py [目录]
    # 不传目录时默认统计当前目录
"""
import sys
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    if not root.is_dir():
        print(f"错误: {root} 不是有效目录", file=sys.stderr)
        sys.exit(1)

    results = []
    for md in root.rglob("SKILL.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            print(f"跳过（无法读取）: {md} -> {e}", file=sys.stderr)
            continue
        lines = len(text.splitlines())
        size = md.stat().st_size
        results.append((md, lines, size))

    # 按行数降序排序，行数相同时按文件字节大小降序
    results.sort(key=lambda x: (x[1], x[2]), reverse=True)

    if not results:
        print(f"在 {root} 下未找到任何 SKILL.md")
        return

    print(f"{'行数':>8}  {'字节':>10}  文件路径")
    print("-" * 80)
    total_lines = 0
    for md, lines, size in results:
        total_lines += lines
        print(f"{lines:>8}  {size:>10}  {md}")
    print("-" * 80)
    print(f"共 {len(results)} 个 SKILL.md，总计 {total_lines} 行")


if __name__ == "__main__":
    main()
