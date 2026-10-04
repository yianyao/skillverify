#!/usr/bin/env python3
"""summarize_reviews.py — 汇总 llm-review-log.md：判定统计、双评缺口、分歧项。

用法:
    python summarize_reviews.py <skill_dir>
退出码: 0=成功; 1=日志不存在或格式无法解析。
输出仅为汇总建议，最终放行由人工裁决。
"""
import os
import re
import sys

DUAL_REQUIRED = ["W-02", "W-04", "W-05", "W-08", "W-15", "E-04", "E-06", "R-02"]
ROW_RE = re.compile(r"^\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*(PASS|FAIL)\s*\|\s*(是|否|不适用)\s*\|")


def show_help() -> None:
    print(
        "summarize_reviews.py — 汇总 llm-review-log.md：判定统计、双评缺口、分歧项。\n"
        "\n"
        "用法: python summarize_reviews.py <skill_dir>\n"
        "标志: 无（仅一个位置参数 skill_dir）\n"
        "示例: python summarize_reviews.py /path/to/my-skill\n"
        "退出码: 0=成功; 1=日志不存在或格式无法解析。输出仅为汇总建议，最终放行由人工裁决。"
    )


def main() -> int:
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        show_help()
        return 0
    if len(sys.argv) != 2:
        print("错误: 缺少参数。\n用法: summarize_reviews.py <skill_dir>\n下一步: 传入目标技能目录后重试。", file=sys.stderr)
        return 1
    log = os.path.join(os.path.abspath(sys.argv[1]), ".verification", "llm-review-log.md")
    if not os.path.exists(log):
        print(f"错误: 日志不存在: {log}\n下一步: 先用 record_review.py 留痕。", file=sys.stderr)
        return 1

    entries = []  # (prompt_id, verdict, dual, evidence, model)
    with open(log, encoding="utf-8") as f:
        for line in f:
            m = ROW_RE.match(line.strip())
            if m:
                entries.append((m.group(2).strip(), m.group(5), m.group(6),
                                m.group(4).strip(), m.group(3).strip()))
    if not entries:
        print("错误: 日志中未解析到有效记录行（列数/判定/双评字段须符合模板）。\n下一步: 检查日志表格式。", file=sys.stderr)
        return 1

    print(f"日志: {log}")
    print(f"总记录数: {len(entries)}")
    fails = [e for e in entries if e[1] == "FAIL"]
    print(f"FAIL 数: {len(fails)}")
    for pid, verdict, dual, evidence, model in fails:
        print(f"  FAIL {pid} (dual={dual}, {model}): {evidence[:80]}")

    print("\n双评缺口（⚑ 项须 ≥2 条记录且全部 dual=是，对应两个独立会话）:")
    gaps = []
    for pid in DUAL_REQUIRED:
        recs = [e for e in entries if e[0] == pid]
        if not recs:
            gaps.append(f"  缺记录: {pid}")
        elif len(recs) < 2:
            gaps.append(f"  记录不足: {pid}（双评须 ≥2 条独立会话记录，现 {len(recs)} 条；补齐第二条后才能判定是否分歧）")
        elif not all(e[2] == "是" for e in recs):
            gaps.append(f"  未双评: {pid}（存在 dual≠是 的记录: {'/'.join(sorted({e[2] for e in recs if e[2] != '是'}))}）")
    print("\n".join(gaps) if gaps else "  无")

    print("\n双评分歧（同编号判定不一致，须人工裁决）:")
    conflicts = []
    for pid in DUAL_REQUIRED:
        verdicts = {e[1] for e in entries if e[0] == pid}
        if len(verdicts) > 1:
            conflicts.append(f"  {pid}: {' vs '.join(sorted(verdicts))} → 升级人工裁决")
    print("\n".join(conflicts) if conflicts else "  无")

    print("\n提醒: 本汇总为建议输出；PASS/FAIL 最终放行由人工签认，[M] 级 FAIL 不得自动放行。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
