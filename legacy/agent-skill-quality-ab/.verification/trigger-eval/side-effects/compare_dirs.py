#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比两个文件夹中同名文件的内容差异，输出 diff 报告。

用法:
    python compare_dirs.py <目录A> <目录B> [-o 报告文件]

说明:
    - 以相对路径匹配同名文件（支持子目录递归）
    - 仅在其中一个目录存在的文件会在报告中列出
    - 文本文件输出 unified diff；二进制文件仅提示"内容不同/相同"
    - 报告同时写入文件（默认 diff_report.txt）并打印到终端
"""

import argparse
import difflib
import os
import sys


def list_files(root):
    """返回 {相对路径: 绝对路径} 字典。"""
    files = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            files[rel.replace(os.sep, "/")] = full
    return files


def is_binary(data):
    return b"\x00" in data[:8192]


def main():
    parser = argparse.ArgumentParser(description="对比两个文件夹中同名文件的差异")
    parser.add_argument("dir_a", help="第一个目录")
    parser.add_argument("dir_b", help="第二个目录")
    parser.add_argument("-o", "--output", default="diff_report.txt", help="报告输出文件（默认 diff_report.txt）")
    args = parser.parse_args()

    for d in (args.dir_a, args.dir_b):
        if not os.path.isdir(d):
            print(f"错误: 目录不存在: {d}", file=sys.stderr)
            sys.exit(1)

    files_a = list_files(args.dir_a)
    files_b = list_files(args.dir_b)

    common = sorted(set(files_a) & set(files_b))
    only_a = sorted(set(files_a) - set(files_b))
    only_b = sorted(set(files_b) - set(files_a))

    lines = []
    lines.append("=" * 60)
    lines.append(f"目录对比报告")
    lines.append(f"目录 A: {os.path.abspath(args.dir_a)}")
    lines.append(f"目录 B: {os.path.abspath(args.dir_b)}")
    lines.append(f"共有文件: {len(common)} | 仅在 A: {len(only_a)} | 仅在 B: {len(only_b)}")
    lines.append("=" * 60)

    if only_a:
        lines.append("\n## 仅存在于目录 A 的文件:")
        lines.extend(f"  - {f}" for f in only_a)
    if only_b:
        lines.append("\n## 仅存在于目录 B 的文件:")
        lines.extend(f"  - {f}" for f in only_b)

    diff_count = 0
    for rel in common:
        with open(files_a[rel], "rb") as f:
            data_a = f.read()
        with open(files_b[rel], "rb") as f:
            data_b = f.read()

        if data_a == data_b:
            continue

        diff_count += 1
        lines.append(f"\n{'=' * 60}")
        lines.append(f"## 文件不同: {rel}")
        lines.append("=" * 60)

        if is_binary(data_a) or is_binary(data_b):
            lines.append("  [二进制文件] 内容不同，跳过逐行 diff。")
            continue

        try:
            text_a = data_a.decode("utf-8").splitlines(keepends=True)
            text_b = data_b.decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError:
            enc = "gbk"
            try:
                text_a = data_a.decode(enc).splitlines(keepends=True)
                text_b = data_b.decode(enc).splitlines(keepends=True)
            except UnicodeDecodeError:
                lines.append("  [无法解码] 非 UTF-8/GBK 文本，跳过 diff。")
                continue

        diff = difflib.unified_diff(
            text_a, text_b,
            fromfile=f"A/{rel}", tofile=f"B/{rel}",
        )
        lines.extend(l.rstrip("\n") for l in diff)

    lines.append(f"\n{'=' * 60}")
    lines.append(f"总结: 共 {len(common)} 个同名文件，其中 {diff_count} 个内容不同。")

    report = "\n".join(lines) + "\n"
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    print(f"报告已写入: {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
