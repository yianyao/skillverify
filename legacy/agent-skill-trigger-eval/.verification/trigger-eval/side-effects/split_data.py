# -*- coding: utf-8 -*-
"""
将标注数据按 6:4 切分为训练集和验证集（先打乱顺序）。

用法:
    python split_data.py data.jsonl                # 输出 train.jsonl / val.jsonl
    python split_data.py data.csv --outdir splits  # 输出 splits/train.csv / splits/val.csv
    python split_data.py data.txt --seed 42

支持格式: .jsonl / .json(JSON Lines) / .csv / .txt(每行一条样本)
"""
import argparse
import csv
import json
import os
import random
import sys


def read_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        return [line for line in (l.rstrip("\n").rstrip("\r") for l in f) if line]


def read_rows(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jsonl", ".json"):
        return read_lines(path)  # 每行一条 JSON 记录
    if ext == ".csv":
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            return list(csv.reader(f))  # 保留表头行
    # txt 及其他：按行切
    return read_lines(path)


def write_rows(path, rows, is_csv):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if is_csv:
        with open(path, "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(rows)
    else:
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(r + "\n")


def main():
    ap = argparse.ArgumentParser(description="按 6:4 切分训练/验证集（先打乱）")
    ap.add_argument("input", help="输入数据文件")
    ap.add_argument("--train-ratio", type=float, default=0.6, help="训练集比例，默认 0.6")
    ap.add_argument("--seed", type=int, default=42, help="随机种子，默认 42")
    ap.add_argument("--outdir", default=".", help="输出目录，默认当前目录")
    args = ap.parse_args()

    if not os.path.isfile(args.input):
        sys.exit(f"文件不存在: {args.input}")

    is_csv = os.path.splitext(args.input)[1].lower() == ".csv"
    rows = read_rows(args.input)

    header = None
    if is_csv:
        header, body = rows[0], rows[1:]
    else:
        body = rows

    if not body:
        sys.exit("数据为空，无法切分")

    random.seed(args.seed)
    random.shuffle(body)  # 原地打乱

    n_train = int(len(body) * args.train_ratio)
    train, val = body[:n_train], body[n_train:]

    stem = os.path.splitext(os.path.basename(args.input))[0]
    ext = ".csv" if is_csv else ".jsonl" if os.path.splitext(args.input)[1].lower() in (".jsonl", ".json") else ".txt"
    train_path = os.path.join(args.outdir, f"{stem}_train{ext}")
    val_path = os.path.join(args.outdir, f"{stem}_val{ext}")

    if is_csv:
        write_rows(train_path, [header] + train, True)
        write_rows(val_path, [header] + val, True)
    else:
        write_rows(train_path, train, False)
        write_rows(val_path, val, False)

    print(f"共 {len(body)} 条样本（种子 {args.seed}）")
    print(f"训练集: {train_path}  {len(train)} 条 ({len(train)/len(body):.1%})")
    print(f"验证集: {val_path}  {len(val)} 条 ({len(val)/len(body):.1%})")


if __name__ == "__main__":
    main()
