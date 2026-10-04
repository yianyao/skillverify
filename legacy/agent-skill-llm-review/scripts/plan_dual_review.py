#!/usr/bin/env python3
"""plan_dual_review.py — 生成双评/盲评任务包。

双评: 为 ⚑ 提示词生成 A/B 两份独立任务包，人工分别开两个会话投喂。
盲评: 对两份输出文件随机匿名化为"版本 A/B"，供 E-06 评委使用；
      真实来源映射写入同目录 mapping.json，投喂评委前勿让其接触。

用法:
    双评:  python plan_dual_review.py --skill-dir <dir> --prompt-id W-15 \
               --inputs SKILL.md scripts/foo.py
    盲评:  python plan_dual_review.py --skill-dir <dir> --prompt-id E-06 \
               --blind out_new.md out_old.md

退出码: 0=成功; 1=参数错误。
"""
import argparse
import datetime
import json
import os
import random
import re
import sys

DUAL_REQUIRED = {"W-02", "W-04", "W-05", "W-08", "W-15", "E-04", "E-06", "R-02"}
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF_DIR = os.path.join(SKILL_ROOT, "references")


def extract_prompt(prompt_id: str) -> tuple[str, str]:
    """从 references/*.md 提取提示词正文，返回 (提示词文本, 来源文件名)。"""
    group = prompt_id.split("-")[0]
    ref = os.path.join(REF_DIR, {"D": "d", "W": "w", "E": "e", "R": "r"}[group] + "-prompts.md")
    if not os.path.exists(ref):
        raise FileNotFoundError(f"错误: 找不到提示词库 {ref}\n下一步: 确认技能安装完整。")
    with open(ref, encoding="utf-8") as f:
        text = f.read()
    m = re.search(
        r"^##\s+" + re.escape(prompt_id) + r"(?!\d).*?\n```text\n(.*?)```",
        text, re.S | re.M,
    )
    if not m:
        raise ValueError(f"错误: 在 {os.path.basename(ref)} 中未找到 {prompt_id} 的提示词块。\n下一步: 核对提示词编号。")
    return m.group(1).strip(), os.path.basename(ref)


def read_inputs(paths: list[str]) -> list[tuple[str, str]]:
    out = []
    for p in paths:
        if not os.path.exists(p):
            raise FileNotFoundError(f"错误: 输入文件不存在: {p}\n下一步: 确认路径后重试。")
        with open(p, encoding="utf-8", errors="replace") as f:
            out.append((os.path.basename(p), f.read()))
    return out


def write_pkg(path: str, title: str, body: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    print(f"已生成: {path}  ({title})")


def main() -> int:
    p = argparse.ArgumentParser(description="生成双评/盲评任务包")
    p.add_argument("--skill-dir", required=True, help="目标技能目录（任务包写入其 .verification/）")
    p.add_argument("--prompt-id", required=True, help="提示词编号，如 W-15 / E-06")
    p.add_argument("--inputs", nargs="*", default=[], help="待评审文件路径（内嵌进任务包）")
    p.add_argument("--blind", nargs=2, metavar=("FILE_A", "FILE_B"),
                   help="盲评模式：两份输出文件随机匿名化")
    a = p.parse_args()

    if not os.path.isdir(a.skill_dir):
        print(f"错误: 目标技能目录不存在: {a.skill_dir}\n下一步: 确认路径后重试；本脚本不代为创建目标技能目录。", file=sys.stderr)
        return 1
    if not a.blind and not a.inputs:
        print("错误: 双评模式需 --inputs，盲评模式需 --blind（二选一）。\n下一步: 补齐参数后重试。", file=sys.stderr)
        return 1
    if a.blind and os.path.realpath(a.blind[0]) == os.path.realpath(a.blind[1]):
        print(f"错误: 盲评两份输入指向同一文件: {a.blind[0]}\n下一步: 盲评需同一任务的两份不同输出，核对路径后重试。", file=sys.stderr)
        return 1
    try:
        prompt_text, source = extract_prompt(a.prompt_id)
    except (FileNotFoundError, ValueError) as e:
        print(e, file=sys.stderr)
        return 1

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = os.path.join(os.path.abspath(a.skill_dir), ".verification", "dual-review", f"{a.prompt_id}-{ts}")
    os.makedirs(outdir, exist_ok=True)

    if a.blind:
        files = read_inputs(a.blind)
        random.shuffle(files)
        # 标签用 "版本 A/B"：与 e-prompts.md E-06 提示词（"版本 A / 版本 B"，
        # 输出 JSON 键 "A"/"B"）逐字对齐，避免评委在两套命名间困惑。
        labels = ("A", "B")
        for (name, content), lab in zip(files, labels):
            body = (
                f"# 盲评任务包 · 版本 {lab}\n\n"
                f"来源信息禁止接触。按提示词独立评分并给证据引用。\n\n"
                f"## 提示词（{a.prompt_id}，来自 {source}）\n\n```text\n{prompt_text}\n```\n\n"
                f"## 待评输出（版本 {lab}）\n\n```\n{content}\n```\n"
            )
            write_pkg(os.path.join(outdir, f"blind-{lab}.md"), f"版本 {lab}", body)
        mapping = {f"版本 {lab}": name for (name, _), lab in zip(files, labels)}
        with open(os.path.join(outdir, "mapping.json"), "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        print(f"已生成映射（投喂评委前勿展示）: {os.path.join(outdir, 'mapping.json')}")
    else:
        if a.prompt_id not in DUAL_REQUIRED:
            print(f"提示: {a.prompt_id} 非 ⚑ 双评范围，通常单评即可；仍按双评生成任务包。")
        materials = "\n\n".join(f"### 输入: {name}\n\n```\n{content}\n```" for name, content in read_inputs(a.inputs))
        for pkg in ("A", "B"):
            body = (
                f"# 双评任务包 {pkg}（包编号：{pkg}）· {a.prompt_id}\n\n"
                f"**本包编号: {pkg}**（留痕时 record_review.py --package {pkg}）\n\n"
                f"**独立判定声明**: 本包由独立会话独立判定，不得参考另一份包的结论；"
                f"同一会话内跑两遍不构成双评。判定不一致将升级人工裁决。\n\n"
                f"## 提示词（来自 {source}）\n\n```text\n{prompt_text}\n```\n\n"
                f"## 待评审材料\n\n{materials}\n"
            )
            write_pkg(os.path.join(outdir, f"{pkg}-task.md"), f"任务包 {pkg}", body)
    print(f"\n下一步: A/B 两包分别开两个独立会话投喂；结果用 record_review.py 分别留痕"
          f"（--package A / --package B，双评=是）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
