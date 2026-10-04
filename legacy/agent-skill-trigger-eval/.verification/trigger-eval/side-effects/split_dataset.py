#!/usr/bin/env python3
"""将标注数据按 6:4 切分为训练集和验证集，切分前随机打乱顺序。

支持格式：
- CSV（含表头，默认标签列为最后一列，可用 --label-col 指定列名）
- JSONL（每行一个 JSON 对象）

用法：
    python split_dataset.py data.csv
    python split_dataset.py data.jsonl --train-ratio 0.6 --seed 42
"""

import argparse
import csv
import json
import random
from pathlib import Path


def read_rows(path: Path):
    if path.suffix.lower() == ".jsonl":
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)
    else:  # 默认按 CSV 处理
        with path.open(encoding="utf-8-sig", newline="") as f:
            yield from csv.DictReader(f)


def main():
    parser = argparse.ArgumentParser(description="按比例切分标注数据集")
    parser.add_argument("input", help="输入数据文件（.csv 或 .jsonl）")
    parser.add_argument("--train-ratio", type=float, default=0.6, help="训练集比例，默认 0.6")
    parser.add_argument("--seed", type=int, default=42, help="随机种子，保证可复现")
    parser.add_argument("--outdir", default=".", help="输出目录，默认当前目录")
    args = parser.parse_args()

    src = Path(args.input)
    rows = list(read_rows(src))
    if not rows:
        raise SystemExit("输入文件为空")

    random.seed(args.seed)
    random.shuffle(rows)

    n_train = int(len(rows) * args.train_ratio)
    train, valid = rows[:n_train], rows[n_train:]

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = src.stem

    def write(out_path: Path, data):
        with out_path.open("w", encoding="utf-8", newline="") as f:
            if src.suffix.lower() == ".jsonl":
                for r in data:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            else:
                writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
                writer.writeheader()
                writer.writerows(data)

    write(outdir / f"{stem}_train{src.suffix}", train)
    write(outdir / f"{stem}_valid{src.suffix}", valid)

    print(f"总计 {len(rows)} 条，训练集 {len(train)} 条，验证集 {len(valid)} 条")
    print(f"输出：{outdir / (stem + '_train' + src.suffix)}")
    print(f"输出：{outdir / (stem + '_valid' + src.suffix)}")


if __name__ == "__main__":
    main()
