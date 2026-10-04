#!/usr/bin/env python3
"""对比两个文件夹中同名文件的内容差异，输出 diff 报告。

用法:
    python diff_folders.py <folder_a> <folder_b> [-o report.txt] [-r]
"""
import argparse
import difflib
import sys
from pathlib import Path


def collect_files(folder: Path, recursive: bool) -> dict:
    """收集文件夹中的文件，返回 {相对路径: 绝对路径}。"""
    pattern = "**/*" if recursive else "*"
    files = {}
    for p in sorted(folder.glob(pattern)):
        if p.is_file():
            files[p.relative_to(folder).as_posix()] = p
    return files


def read_text(path: Path):
    """读取文本，二进制文件返回 None。"""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    except OSError as e:
        print(f"[警告] 无法读取 {path}: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser(description="对比两个文件夹中同名文件的差异")
    parser.add_argument("folder_a", type=Path)
    parser.add_argument("folder_b", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=Path("diff_report.txt"),
                        help="报告输出路径 (默认 diff_report.txt)")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="递归对比子目录")
    parser.add_argument("--context", type=int, default=3, help="diff 上下文行数 (默认 3)")
    args = parser.parse_args()

    fa, fb = args.folder_a, args.folder_b
    if not fa.is_dir() or not fb.is_dir():
        print("[错误] 两个参数都必须是已存在的目录", file=sys.stderr)
        sys.exit(1)

    files_a = collect_files(fa, args.recursive)
    files_b = collect_files(fb, args.recursive)

    common = sorted(set(files_a) & set(files_b))
    only_a = sorted(set(files_a) - set(files_b))
    only_b = sorted(set(files_b) - set(files_a))

    lines = [
        "=" * 70,
        f"文件夹 Diff 报告",
        f"A: {fa.resolve()}",
        f"B: {fb.resolve()}",
        "=" * 70,
        f"共  {len(common)} 个同名文件, 仅 A 有 {len(only_a)} 个, 仅 B 有 {len(only_b)} 个",
        "",
    ]

    diff_count = 0
    same_count = 0

    for rel in common:
        ta = read_text(files_a[rel])
        tb = read_text(files_b[rel])
        if ta is None or tb is None:
            lines.append(f"[跳过] {rel} (无法按文本读取)")
            continue

        la, lb = ta.splitlines(keepends=True), tb.splitlines(keepends=True)
        if la == lb:
            same_count += 1
            continue

        diff_count += 1
        diff = difflib.unified_diff(
            la, lb,
            fromfile=f"A/{rel}", tofile=f"B/{rel}",
            n=args.context,
        )
        lines.append("-" * 70)
        lines.append(f"[差异] {rel}")
        lines.extend(diff)
        lines.append("")

    if only_a:
        lines.append("-" * 70)
        lines.append(f"仅在 A 中存在 ({len(only_a)}):")
        lines.extend(f"  - {p}" for p in only_a)
        lines.append("")
    if only_b:
        lines.append("-" * 70)
        lines.append(f"仅在 B 中存在 ({len(only_b)}):")
        lines.extend(f"  - {p}" for p in only_b)
        lines.append("")

    lines.append("=" * 70)
    lines.append(f"统计: 相同 {same_count} | 有差异 {diff_count} | 仅 A {len(only_a)} | 仅 B {len(only_b)}")

    report = "\n".join(lines) + "\n"
    args.output.write_text(report, encoding="utf-8")
    print(report)
    print(f"报告已写入: {args.output.resolve()}")


if __name__ == "__main__":
    main()
