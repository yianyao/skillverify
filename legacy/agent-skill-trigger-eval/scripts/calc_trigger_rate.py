#!/usr/bin/env python3
"""calc_trigger_rate.py — 触发评测 S 脚本：算触发率、按 §6.3.4 过门判定、出报告。

输入:
  --runs runs.json        原始运行记录，格式:
                          {"runs": [{"query_id": "P01", "run": 1, "loaded": true,
                                     "evidence": "Skill 工具调用了 xxx"}, ...]}
  --queryset queryset.json 冻结查询集（含 queries[].id / should_trigger / subset）
  --out trigger-report.md  报告落盘路径（可选）
  --min-runs 3             每条查询最少运行次数（§6.3.1）

判定口径（规范条目总表 §6.3.4）:
  应触发查询: 触发率 > 0.5 才 PASS
  不应触发查询: 触发率 < 0.5 才 PASS

退出码（v1.1 显式声明）: 0=全过；1=任一 FAIL 或输入错误；2=无 FAIL 但有 WARN。
  退出码仅供人工快速判读；编排器不得仅凭退出码作验收阻断（与工具族约定一致）。

版本: v1.1（2026-10-02 第七轮评审修订）— S-1 输入根类型校验（ValueError 入 except）；
      S-2 汇总 WARN 与 PASS 分开统计不混同；P-4 loaded 非 bool 告警；P-8 报告增加
      统计覆盖率行。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

POS_PASS = 0.5   # 正例须严格大于
NEG_PASS = 0.5   # 负例须严格小于


def load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        # S-1：合法 JSON 但根为 list/number/str 时，后续 .get 会抛 AttributeError
        # 且不在 except 列表——转成 ValueError 走统一错误通道（与 grade_ab.py 对齐）
        raise ValueError(f"{path.name} 根类型应为 dict，实为 {type(data).__name__}")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description="触发评测触发率计算与过门判定")
    ap.add_argument("--runs", required=True, help="runs.json（原始运行记录）")
    ap.add_argument("--queryset", required=True, help="queryset.json（冻结查询集）")
    ap.add_argument("--out", help="报告落盘路径（建议 trigger-report.md）")
    ap.add_argument("--min-runs", type=int, default=3, help="每条最少运行次数（默认 3）")
    a = ap.parse_args()

    try:
        qs = load_json(Path(a.queryset))
        runs_data = load_json(Path(a.runs))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
        print(f"错误: 输入读取/解析失败 — {e}", file=sys.stderr)
        return 1

    queries = {q["id"]: q for q in qs.get("queries", [])}
    if not queries:
        print("错误: queryset.json 无 queries 数组", file=sys.stderr)
        return 1

    # 按 query_id 聚合
    agg: dict[str, dict] = {}
    unknown: list[str] = []
    bad_loaded: list[str] = []
    all_runs = runs_data.get("runs", [])
    for r in all_runs:
        if not isinstance(r, dict):
            bad_loaded.append("非对象记录")
            continue
        qid = str(r.get("query_id", ""))
        if qid not in queries:
            unknown.append(qid)
            continue
        rec = agg.setdefault(qid, {"n": 0, "loaded": 0})
        rec["n"] += 1
        lv = r.get("loaded")
        if lv is True:
            rec["loaded"] += 1
        elif lv is not False and lv is not None:
            # P-4：非 bool（如 1 / "true"）静默当作未触发会误算——显式告警
            bad_loaded.append(f"{qid} run{r.get('run')}: loaded={lv!r}")

    rows: list[dict] = []
    has_fail = False
    has_warn = False
    for qid in sorted(queries):
        q = queries[qid]
        rec = agg.get(qid, {"n": 0, "loaded": 0})
        n, loaded = rec["n"], rec["loaded"]
        rate = (loaded / n) if n else 0.0
        expect = bool(q.get("should_trigger"))
        warn = ""
        if n == 0:
            verdict, warn = "WARN", "（未运行，数据缺失）"
            has_warn = True
        else:
            if expect:
                verdict = "PASS" if rate > POS_PASS else "FAIL"
            else:
                verdict = "PASS" if rate < NEG_PASS else "FAIL"
            if n < a.min_runs:
                # §6.3.1：每条 ≥3 次才有终判资格——次数不足时 FAIL 降级 WARN 交人工
                warn = f"（运行 {n} < {a.min_runs}，数据不足）"
                if verdict == "FAIL":
                    verdict = "WARN"
                has_warn = True
        if verdict == "FAIL":
            has_fail = True
        rows.append(dict(qid=qid, subset=q.get("subset", "?"), expect=expect,
                         n=n, loaded=loaded, rate=rate, verdict=verdict, warn=warn))

    if unknown:
        has_warn = True
        print(f"[WARN] runs.json 中 {len(unknown)} 条 query_id 不在查询集内: {sorted(set(unknown))[:5]}",
              file=sys.stderr)
    if bad_loaded:
        has_warn = True
        print(f"[WARN] {len(bad_loaded)} 条记录 loaded 字段非 bool，已按未触发计入: {bad_loaded[:5]}",
              file=sys.stderr)

    # P-8：统计覆盖率——被丢弃记录多时结论可能被误信，须在报告中显著展示
    total = len(all_runs)
    covered = total - len(unknown) - len(bad_loaded)
    coverage = (covered / total) if total else 1.0
    if total and coverage < 0.8:
        has_warn = True

    # train / validation 分列汇总
    def summary(subset: str) -> str:
        sub = [r for r in rows if r["subset"] == subset]
        pos = [r for r in sub if r["expect"]]
        neg = [r for r in sub if not r["expect"]]

        # S-2：WARN（数据不足/未运行）不与 PASS 混同，单列避免误读为"全部达标"
        def _cnt(items: list[dict]) -> str:
            p = sum(1 for r in items if r["verdict"] == "PASS")
            w = sum(1 for r in items if r["verdict"] == "WARN")
            return f"{p}/{len(items)} 过" + (f"（另 {w} WARN）" if w else "")

        return f"{_cnt(pos)} 正例、{_cnt(neg)} 负例"

    lines = [
        "# 触发率过门报告（calc_trigger_rate.py）",
        "",
        f"- 口径: §6.3.4（应触发 >{POS_PASS}，不应触发 <{NEG_PASS}）；每条 ≥{a.min_runs} 次",
        f"- 统计覆盖率: {covered}/{total} 条记录（{coverage:.0%}；丢弃: query_id 不在集内 {len(unknown)}、格式异常 {len(bad_loaded)}）",
        f"- train 汇总: {summary('train')}",
        f"- validation 汇总: {summary('validation')}",
        "",
        "| 查询 | 子集 | 应触发 | 运行 | 触发 | 触发率 | 结论 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['qid']} | {r['subset']} | {'是' if r['expect'] else '否'} "
                     f"| {r['n']} | {r['loaded']} | {r['rate']:.2f} "
                     f"| {r['verdict']}{r['warn']} |")
    lines += [
        "",
        f"- 总结论: {'FAIL（存在未过门查询）' if has_fail else ('PASS（附 WARN）' if has_warn else 'PASS 全过门')}",
        "",
        "> validation 子集结果不得参与 description 修改决策（§6.4.3 隔离纪律）；修订只依据 train 失败。",
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

    return 1 if has_fail else (2 if has_warn else 0)


if __name__ == "__main__":
    sys.exit(main())
