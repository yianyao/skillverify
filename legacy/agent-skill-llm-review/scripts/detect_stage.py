#!/usr/bin/env python3
"""detect_stage.py — 检测目标技能的生命周期产物，推荐应跑的 LLM 评审提示词组。

定位：advisory（仅建议）。产物存在只说明"到过该阶段"，阶段完成以《验证 SOP》
出口判据 + 人工签认为准；本脚本输出不得作为门禁依据。

用法:
    python detect_stage.py <skill_dir>
退出码: 0=检测完成（无论检出哪些阶段，advisory 不阻断）; 1=用法错误/目录不存在。
"""
import os
import sys

RECOMMEND = {
    "D": ("D-01", "设计期：取材材料提炼辅助（d-prompts.md）"),
    "W": ("W-01~W-16", "编写期语义评审全跑；⚑ 双评：W-02/W-04/W-05/W-08/W-15（w-prompts.md）"),
    "E": ("E-01~E-10", "测试期：按实际测试项选跑；⚑ 双评：E-04/E-06（e-prompts.md）"),
    "M": ("（无）", "M 阶段产物已存在；M0 复核与 M1 审计属 H 类人工终审，无专属 L 类提示词（如需辅助可重跑 W 组）"),
    "R": ("R-01/R-02", "运行期：纠错归纳与增长性内容隔离；⚑ 双评：R-02（r-prompts.md）"),
}


def show_help() -> None:
    print(
        "detect_stage.py — 检测目标技能的生命周期产物，推荐应跑的 LLM 评审提示词组（advisory，不阻断）。\n"
        "\n"
        "用法: python detect_stage.py <skill_dir>\n"
        "标志: 无（仅一个位置参数 skill_dir）\n"
        "示例: python detect_stage.py /path/to/my-skill\n"
        "退出码: 0=检测完成（advisory 不阻断）; 1=用法错误/目录不存在。"
    )


def main() -> int:
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        show_help()
        return 0
    if len(sys.argv) != 2:
        print("错误: 缺少参数。\n用法: detect_stage.py <skill_dir>\n下一步: 传入目标技能目录后重试。", file=sys.stderr)
        return 1  # 用法错误须与"正常完成"可区分，供编排器识别
    skill_dir = os.path.abspath(sys.argv[1])
    if not os.path.isdir(skill_dir):
        print(f"错误: 目录不存在: {skill_dir}\n下一步: 确认技能目录路径后重试。", file=sys.stderr)
        return 1
    vdir = os.path.join(skill_dir, ".verification")

    def exists(*names: str) -> bool:
        return all(os.path.exists(os.path.join(vdir, n)) for n in names)

    def any_iteration() -> bool:
        return os.path.isdir(vdir) and any(
            n.startswith("iteration-") and os.path.isdir(os.path.join(vdir, n))
            for n in os.listdir(vdir)
        )

    print(f"目标技能: {skill_dir}")
    print(f".verification 目录: {'存在' if os.path.isdir(vdir) else '不存在（可能尚未立项或未留痕）'}")
    print()
    print("阶段产物检测（存在=到过该阶段，不等于阶段完成）:")
    rows = [
        ("D", "design.md + name-precheck.md", exists("design.md", "name-precheck.md")),
        ("W", "llm-review-log.md", exists("llm-review-log.md")),
        ("E", "iteration-N/ 目录", any_iteration()),
        ("M", ".iteration-baseline + acceptance-report.md",
         exists(".iteration-baseline") or exists("acceptance-report.md")),
        ("R", "run-log.md", exists("run-log.md")),
    ]
    for stage, marker, hit in rows:
        print(f"  [{'x' if hit else ' '}] {stage}  {marker}")
    print()
    print("提示词建议（仅建议，非门禁）:")
    for stage, marker, hit in rows:
        if hit:
            pid, desc = RECOMMEND[stage]
            print(f"  {stage}: {pid} — {desc}")
    if not any(hit for _, _, hit in rows):
        print("  未检测到任何阶段产物。若为全新技能，先走 D 阶段：填写设计说明后再运行本脚本。")
    print()
    print("提醒: ⚑ 提示词须双评（两个独立会话/不同模型），用 plan_dual_review.py 生成任务包。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
