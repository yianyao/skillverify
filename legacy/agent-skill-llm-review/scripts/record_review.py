#!/usr/bin/env python3
"""record_review.py — 向 llm-review-log.md 追加一条 V12 留痕记录。

用法:
    python record_review.py --skill-dir <dir> --prompt-id W-02 \
        --model "glm-4.7" --verdict FAIL --evidence "证据摘要/引用" --dual 是 --package A
退出码: 0=成功; 1=参数错误; 2=⚑ 提示词未双评——警告级（记录已写入，需人工复核后补录）。
双评记录请分别带 --package A / --package B，写入证据列前缀以便区分两个独立会话。
"""
import argparse
import datetime
import os
import re
import sys

DUAL_REQUIRED = {"W-02", "W-04", "W-05", "W-08", "W-15", "E-04", "E-06", "R-02"}

HEADER = """# LLM 评审日志（V12 留痕）

> 双评 ⚑ 权威范围：W-02、W-04、W-05、W-08、W-15、E-04、E-06、R-02。
> 同一会话内跑两遍不构成双评，不得标"是"。

| 日期 | 提示词编号 | 模型名+版本 | 输出证据（结论摘要/引用） | 判定 | 是否双评 |
| --- | --- | --- | --- | --- | --- |
"""


def main() -> int:
    p = argparse.ArgumentParser(description="追加 LLM 评审留痕")
    p.add_argument("--skill-dir", required=True, help="目标技能目录")
    p.add_argument("--prompt-id", required=True, help="提示词编号，如 W-02 / E-04")
    p.add_argument("--model", required=True, help="模型名+版本")
    p.add_argument("--verdict", required=True, choices=["PASS", "FAIL"], help="判定")
    p.add_argument("--evidence", required=True, help="输出证据（结论摘要/引用）")
    p.add_argument("--dual", default="不适用", choices=["是", "否", "不适用"], help="是否双评")
    p.add_argument("--package", default="", choices=["", "A", "B"],
                   help="双评包编号（可选）：双评时分别以 A/B 各留一条记录")
    a = p.parse_args()

    if not all(field.strip() for field in (a.prompt_id, a.model, a.evidence)):
        print("错误: prompt-id/model/evidence 均不得为空。\n下一步: 补齐参数后重试。", file=sys.stderr)
        return 1
    if not re.fullmatch(r"[DWER]-\d{2}", a.prompt_id):
        print(f"错误: prompt-id 格式不合法: {a.prompt_id}。\n下一步: 使用两位数编号，如 D-01、W-02、E-06、R-02。", file=sys.stderr)
        return 1
    evidence = f"[包{a.package}] {a.evidence}" if a.package else a.evidence
    # markdown 表格防护：半角 | 破坏列结构（不用 \|——summarize 按裸 | 切列，
    # \| 仍会断列）；换行破坏单行记录格式。均替换后写入。
    evidence = (evidence.replace("|", "｜")
                        .replace("\r\n", " ").replace("\r", " ").replace("\n", " "))
    model = (a.model.replace("|", "｜")
                    .replace("\r\n", " ").replace("\r", " ").replace("\n", " "))

    vdir = os.path.join(os.path.abspath(a.skill_dir), ".verification")
    log_path = os.path.join(vdir, "llm-review-log.md")
    os.makedirs(vdir, exist_ok=True)
    if not os.path.exists(log_path):
        with open(log_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(HEADER)
        print(f"已按模板初始化日志: {log_path}")

    today = datetime.date.today().isoformat()
    row = f"| {today} | {a.prompt_id} | {model} | {evidence} | {a.verdict} | {a.dual} |\n"
    with open(log_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(row)
    print(f"已写入: {log_path}\n  {row.strip()}")

    if a.prompt_id in DUAL_REQUIRED and a.dual != "是":
        print(
            f"警告: {a.prompt_id} 属 ⚑ 双评范围，本次记录 dual={a.dual}。"
            "\n下一步: 用 plan_dual_review.py 生成任务包，由两个独立会话分别判定后"
            "以 --package A / --package B 各补录一条。",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
