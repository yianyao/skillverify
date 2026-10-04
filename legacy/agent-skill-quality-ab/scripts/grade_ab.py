#!/usr/bin/env python3
"""grade_ab.py — 双跑对照 S 脚本：从 grading.json 统计两臂通过率、算 delta、出对比报告。

输入 grading.json 格式（summary 字段即使存在也被忽略，通过率一律由断言数组重算）:
{
  "with_skill":    {"report": "outputs/with-skill-report.md",
                    "assertions": [{"text": "...", "passed": true, "evidence": "..."}, ...]},
  "without_skill": {"report": "...", "assertions": [...]}
}

判定口径: delta = with通过率 - without通过率
  delta > 0  → PASS 候选；delta == 0 → 人工裁决（exit 2）；delta < 0 → FAIL
脚本结论一律为候选，最终判定人工签认。

可选: --cost-a/--cost-b 传两臂报告文件，按 字符数÷4 估算 token 成本（粗估口径）。

退出码（v1.1 S-3 显式声明）: 0=候选 PASS；1=delta<0 或输入错误；2=平局。
  退出码仅供人工快速判读；编排器不得仅凭退出码作验收阻断——脚本结论
  一律为候选，最终判定人工签认。（保持 0/1/2 与工具族约定一致）

版本: v1.1（2026-10-02 第五轮评审修订）— S-1 断言 text 集合校验 + 按 Arm-A 重排；
      P-1 cost label 入错 消息；P-4 report 字段 str 归一；P-5 单方优势项附证据摘录；
      P-7 grading.json 根类型校验。
      v1.2（2026-10-02 第六轮评审修订）— 2.1[S] 断言 text 唯一性校验（防 ab_map
      重复键静默错配）；2.2[S] arm_stats 子对象类型校验（非 dict 转 ValueError）；
      2.7 _ev 对 evidence=None 显式置空。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_grading(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"grading.json 根类型应为 dict，实为 {type(data).__name__}")
    return data


def arm_stats(arm: dict, label: str) -> tuple[float, int, int, list[dict], str]:
    if not isinstance(arm, dict):
        # 2.2：键存在但值非 dict（如 "with_skill": "foo"/null）时，arm.get 会抛
        # AttributeError 且不在 except 列表——转成 ValueError 走统一错误通道
        raise ValueError(f"{label}: 应为对象（dict），实为 {type(arm).__name__}")
    assertions = arm.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        raise ValueError(f"{label}: assertions 数组缺失或为空")
    for i, a in enumerate(assertions, 1):
        if not isinstance(a.get("passed"), bool):
            raise ValueError(f"{label}: 第 {i} 条断言缺布尔 passed 字段")
    passed = sum(1 for a in assertions if a["passed"])
    rate = passed / len(assertions)
    # P-4：report 字段 str 归一，防 None/数字污染 f-string 语义
    report = str(arm.get("report") or "(未记录)")
    return rate, passed, len(assertions), assertions, report


def cost_estimate(path_str: str, label: str) -> str:
    if not path_str:
        return "未提供"
    p = Path(path_str)
    if not p.is_file():
        return f"文件不存在（{label}: {path_str}）"
    try:
        n_chars = len(p.read_text(encoding="utf-8", errors="replace"))
    except OSError as e:
        return f"读取失败（{label}: {e}）"
    return f"≈{n_chars // 4} token（{n_chars} 字符 ÷4 粗估）"


def main() -> int:
    ap = argparse.ArgumentParser(description="双跑对照 delta 计算与判定（门 D S 脚本）")
    ap.add_argument("--grading", required=True, help="grading.json 路径")
    ap.add_argument("--out", help="报告落盘路径（建议 delta-report.md）")
    ap.add_argument("--cost-a", help="Arm-A 报告文件（估算 token 成本，字符÷4）")
    ap.add_argument("--cost-b", help="Arm-B 报告文件（同上）")
    a = ap.parse_args()

    try:
        data = load_grading(Path(a.grading))
        ra, pa, na, aa, report_a = arm_stats(data.get("with_skill", {}), "with_skill")
        rb, pb, nb, ab, report_b = arm_stats(data.get("without_skill", {}), "without_skill")
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1

    if na != nb:
        print(f"错误: 两臂断言数不一致（{na} vs {nb}），无法逐条对比。下一步: 核对断言清单是否同源", file=sys.stderr)
        return 1

    # S-1：数量一致不等于一一对应——text 集合必须相同（顺序无关），再按 Arm-A 顺序重排 Arm-B，
    # 防止人工填 grading.json 时顺序不同导致 zip 错配、单方优势项判定失真
    texts_a = [x["text"] for x in aa]
    texts_b = [x["text"] for x in ab]
    # 2.1：text 重复时 sorted 校验仍会通过，而 ab_map 后写覆盖前写会静默错配——先查唯一性
    if len(set(texts_a)) != len(texts_a) or len(set(texts_b)) != len(texts_b):
        print("错误: 断言清单含重复 text，无法一一对应。下一步: 每条断言 text 须唯一（SKILL.md 步骤 1）", file=sys.stderr)
        return 1
    if sorted(texts_a) != sorted(texts_b):
        print("错误: 两臂断言清单 text 不一致（数量相同但条目不同源），无法逐条对比。"
              "下一步: 核对两臂是否评自同一份冻结断言清单", file=sys.stderr)
        return 1
    ab_map = {x["text"]: x for x in ab}
    ab = [ab_map[t] for t in texts_a]

    delta = ra - rb
    if delta > 0:
        verdict, code = "PASS 候选——with_skill 通过率更高", 0
    elif delta < 0:
        verdict, code = "FAIL——with_skill 未体现增益（delta<0），交人工复核是否存在断言偏置", 1
    else:
        verdict, code = "平局——交人工裁决（结合单方优势项分析）", 2

    # P-5：单方优势项附通过臂证据摘录，读者可分辨"为何一臂过一臂不过"
    def _ev(d: dict) -> str:
        e = d.get("evidence")
        # 2.7：evidence 缺失/为 None 时不得显示成 "None"（像有证据实为缺失）
        e = (str(e) if e is not None else "").replace("\n", " ").strip()
        return (e[:48] + "…") if len(e) > 48 else e

    only_a = [f"{x['text']}（A 证据: {_ev(x)}）"
              for x, y in zip(aa, ab) if x["passed"] and not y["passed"]]
    only_b = [f"{y['text']}（B 证据: {_ev(y)}）"
              for x, y in zip(aa, ab) if y["passed"] and not x["passed"]]

    lines = [
        "# 双跑对照 delta 报告（grade_ab.py）",
        "",
        f"- with_skill: {pa}/{na} = {ra:.2f}（{report_a}）",
        f"- without_skill: {pb}/{nb} = {rb:.2f}（{report_b}）",
        f"- delta: {delta:+.2f}",
        f"- 成本估算: Arm-A {cost_estimate(a.cost_a, 'A')}；Arm-B {cost_estimate(a.cost_b, 'B')}",
        "",
        "## 单方优势断言",
        "",
    ]
    lines += [
        f"- 仅 with_skill 通过（{len(only_a)} 条）: " + ("; ".join(only_a) if only_a else "无"),
        f"- 仅 without_skill 通过（{len(only_b)} 条）: " + ("; ".join(only_b) if only_b else "无"),
        "",
        f"## 判定: {verdict}",
        "",
        "> 本结论为脚本候选，最终判定人工签认（E-04 断言评分须双评零分歧在先）。",
    ]
    report = "\n".join(lines) + "\n"

    print(report)
    if a.out:
        outp = Path(a.out)
        try:
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text(report, encoding="utf-8", newline="\n")
            print(f"[已落盘] {outp}")
        except OSError as e:
            print(f"[FAIL] 报告落盘失败: {outp} — {e}", file=sys.stderr)
            return 1

    return code


if __name__ == "__main__":
    sys.exit(main())
