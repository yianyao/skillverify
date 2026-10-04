"""evalx 回归测试（M4）。

**本文件的两类价值**：
1. **双向验证**（M4 验收口径）：按官方页面构造的样例必须全绿；
   本仓库 `legacy/` 下 4 个 `evals/evals.json` 是**旧体系方言**（顶层 `queries`），
   必须被识别为"需迁移"而不是被静默放过——这就是"现库错位样例"。
2. **旧体系后门回归**：把子代理提炼出的坑固化成用例，重点是四条——
   - 按文件名在**任意深度**抓 grading.json（会把 `side-effects/` 里的散落文件算进来）；
   - `grading.json` 缺 `summary` 时静默放过；
   - `pass_rate` 用 1e-9 精确比较（四舍五入过的 0.67 被误判）；
   - 布尔值冒充整数（`true` 当 `1`）。
   本实现还必须**做到旧体系从未做到的**：benchmark 的 delta 与聚合值要和逐次产物对账。

用法：
    python -m tests.test_evalx
    python -m tests.test_evalx --dogfood   # 额外对 legacy/ 跑一遍并打印结论
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skillverify import cli, evalx  # noqa: E402
from skillverify.encoding import force_utf8_stdio  # noqa: E402
from skillverify.report import FAIL, INFO, PASS, SKIP, WARN  # noqa: E402

_passed: list[str] = []
_failed: list[str] = []


def ok(msg: str) -> None:
    _passed.append(msg)
    print(f"  PASS {msg}")


def fail(msg: str) -> None:
    _failed.append(msg)
    print(f"  FAIL {msg}")


def check(cond: bool, msg: str) -> None:
    ok(msg) if cond else fail(msg)


DESC = "A demo skill used by the eval-asset regression suite."

#: 官方页面上的样例（逐字照抄结构，只改技能名以匹配目录名）
OFFICIAL_EVALS = {
    "skill_name": "csv-analyzer",
    "evals": [
        {
            "id": 1,
            "prompt": "I have a CSV of monthly sales data in data/sales_2025.csv. "
                      "Can you find the top 3 months by revenue and make a bar chart?",
            "expected_output": "A bar chart image showing the top 3 months by revenue, "
                              "with labeled axes and values.",
            "files": ["evals/files/sales_2025.csv"],
            "assertions": [
                "The output includes a bar chart image file",
                "The chart shows exactly 3 months",
                "Both axes are labeled",
            ],
        },
        {
            "id": 2,
            "prompt": "there's a csv in my downloads called customers.csv, some rows have "
                      "missing emails — can you clean it up and tell me how many were missing?",
            "expected_output": "A cleaned CSV with missing emails handled, plus a count.",
            "files": ["evals/files/customers.csv"],
            "assertions": [
                "A cleaned CSV is produced",
                "A count of missing emails is reported",
            ],
        },
    ],
}

#: 旧体系方言（本仓库 legacy/ 下 4 个文件的真实形状）
LEGACY_DIALECT = {
    "meta": {"target_skill": "demo-skill", "built_at": "2026-10-01",
             "counts": {"total": 8, "should_trigger": 4, "should_not_trigger": 4}},
    "queries": [
        {"id": "P01", "subset": "train", "should_trigger": True,
         "category": "positive-direct", "query": "帮我评审这个技能", "rationale": "直接触发"},
    ],
}


def write_skill(root: Path, name: str = "csv-analyzer", *, evals: object | None = None,
                files: dict[str, object] | None = None) -> Path:
    target = root / name
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {DESC}\n---\n\n# Demo\n", encoding="utf-8", newline="")
    if evals is not None:
        path = target / "evals" / "evals.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evals, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="")
    for rel, content in (files or {}).items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(str(content), encoding="utf-8", newline="")
    return target


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
    except BaseException:
        sys.stderr.write(f"[run_cli] argv={argv} 抛出异常，已捕获的输出如下：\n"
                         f"--- stdout ---\n{out.getvalue()}\n--- stderr ---\n{err.getvalue()}\n")
        raise
    return code, out.getvalue(), err.getvalue()


def statuses(report) -> dict[str, str]:
    return {r.rid: r.status for r in report.results}


def evidence_of(report, rid: str) -> str:
    return next((r.evidence for r in report.results if r.rid == rid), "")


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="")


def arm(base: Path, eval_name: str, arm_name: str, *, assertions: list[str],
        passed: list[bool], tokens: int, ms: int, evidence: str = "见 outputs/ 产物") -> None:
    d = base / eval_name / arm_name
    (d / "outputs").mkdir(parents=True, exist_ok=True)
    (d / "outputs" / "result.txt").write_text("x\n", encoding="utf-8", newline="")
    results = [
        {"text": text, "passed": flag, "evidence": evidence}
        for text, flag in zip(assertions, passed)
    ]
    n = len(results)
    n_pass = sum(1 for r in results if r["passed"])
    write_json(d / "grading.json", {
        "assertion_results": results,
        "summary": {"passed": n_pass, "failed": n - n_pass, "total": n,
                    "pass_rate": round(n_pass / n, 3) if n else 0.0},
    })
    write_json(d / "timing.json", {"total_tokens": tokens, "duration_ms": ms})


A1 = ["The output includes a bar chart image file", "The chart shows exactly 3 months"]
A2 = ["A cleaned CSV is produced", "A count of missing emails is reported"]


def build_workspace(root: Path, name: str = "csv-analyzer", *, second_iteration: bool = False,
                    skip_baseline: bool = False) -> Path:
    """按官方工作区结构造一份**正确**的产物。"""
    ws = root / f"{name}-workspace"
    it = ws / "iteration-1"
    arm(it, "eval-top-months-chart", "with_skill", assertions=A1, passed=[True, True],
        tokens=1000, ms=2000)
    arm(it, "eval-clean-missing-emails", "with_skill", assertions=A2, passed=[True, False],
        tokens=800, ms=1500)
    if not skip_baseline:
        arm(it, "eval-top-months-chart", "without_skill", assertions=A1, passed=[False, False],
            tokens=500, ms=1000)
        arm(it, "eval-clean-missing-emails", "without_skill", assertions=A2,
            passed=[False, False], tokens=400, ms=800)
    write_json(it / "benchmark.json", _benchmark(skip_baseline=skip_baseline))
    write_json(ws / "feedback.json", {
        "eval-top-months-chart": "横轴月份按字母序而不是时间序。",
        "eval-clean-missing-emails": "",
    })
    if second_iteration:
        it2 = ws / "iteration-2"
        arm(it2, "eval-top-months-chart", "with_skill", assertions=A1, passed=[True, True],
            tokens=900, ms=1800)
        arm(it2, "eval-top-months-chart", "without_skill", assertions=A1,
            passed=[False, False], tokens=480, ms=950)
        write_json(it2 / "benchmark.json", {
            "run_summary": {
                "with_skill": {"pass_rate": {"mean": 1.0, "stddev": 0.0},
                               "time_seconds": {"mean": 1.8, "stddev": 0.0},
                               "tokens": {"mean": 900, "stddev": 0.0}},
                "without_skill": {"pass_rate": {"mean": 0.0, "stddev": 0.0},
                                  "time_seconds": {"mean": 0.95, "stddev": 0.0},
                                  "tokens": {"mean": 480, "stddev": 0.0}},
                "delta": {"pass_rate": 1.0, "time_seconds": 0.85, "tokens": 420},
            }
        })
    return ws


def _benchmark(*, skip_baseline: bool = False) -> dict:
    """与 build_workspace 的逐次产物严格对账的聚合（population stddev）。"""
    summary = {
        "with_skill": {
            "pass_rate": {"mean": 0.75, "stddev": 0.25},
            "time_seconds": {"mean": 1.75, "stddev": 0.25},
            "tokens": {"mean": 900, "stddev": 100},
        },
        "delta": {"pass_rate": 0.75, "time_seconds": 0.85, "tokens": 450},
    }
    if not skip_baseline:
        summary["without_skill"] = {
            "pass_rate": {"mean": 0.0, "stddev": 0.0},
            "time_seconds": {"mean": 0.9, "stddev": 0.1},
            "tokens": {"mean": 450, "stddev": 50},
        }
    return {"run_summary": summary}


# --------------------------------------------------------------------------- #
# evals.json
# --------------------------------------------------------------------------- #


def run_evals_json(tmp: Path) -> None:
    print("[test_evals_json]")
    root = tmp / "ej"
    official = write_skill(root, files={"evals/files/sales_2025.csv": "a,b\n",
                                        "evals/files/customers.csv": "a,b\n"},
                           evals=OFFICIAL_EVALS)
    report = evalx.check_evals(official)
    bad = [r.rid for r in report.results if r.status == FAIL]
    check(report.exit_code() == 0 and not bad,
          f"官方样例全部通过（exit={report.exit_code()}，FAIL={bad}）")
    check(statuses(report)["EVAL-000"] == PASS, "有评测资产 → EVAL-000 PASS")

    # 现库错位样例：旧体系方言必须被指出来，而不是被静默放过
    legacy = write_skill(root, "legacy-dialect-skill", evals=LEGACY_DIALECT)
    report = evalx.check_evals(legacy)
    st = statuses(report)
    ev = evidence_of(report, "EVAL-002")
    check(st["EVAL-002"] == FAIL and "queries" in ev and "需迁移" in ev,
          "旧方言（顶层 queries）被判 FAIL 且证据给出迁移方向")
    check(st["EVAL-003"] == SKIP and "没有可校验的用例" in evidence_of(report, "EVAL-003"),
          "无官方用例时逐条规则记 SKIP（不重复报同一件事）")
    check(st["EVAL-008"] == SKIP, "方言样例不产生「没有任何用例」的重复 WARN")

    # 缺输入文件
    broken_files = json.loads(json.dumps(OFFICIAL_EVALS))
    broken_files["evals"][0]["files"] = ["evals/files/not-there.csv"]
    d = write_skill(root, "csv-analyzer2", evals=broken_files)
    (d / "evals" / "files").mkdir(parents=True, exist_ok=True)
    (d / "evals" / "files" / "customers.csv").write_text("x\n", encoding="utf-8", newline="")
    report = evalx.check_evals(d)
    check(statuses(report)["EVAL-005"] == FAIL
          and "not-there.csv" in evidence_of(report, "EVAL-005"),
          "files 里不存在的输入文件 → FAIL 并点名")

    # 形状错误
    cases = [
        ("empty-evals", {"skill_name": "x", "evals": []}, "EVAL-002", FAIL),
        ("evals-not-array", {"skill_name": "x", "evals": {}}, "EVAL-002", FAIL),
        ("skill-name-not-str", {"skill_name": 3, "evals": [{"id": 1}]}, "EVAL-002", FAIL),
    ]
    for name, payload, rid, want in cases:
        d = write_skill(root, f"shape-{name}", evals=payload)
        check(statuses(evalx.check_evals(d))[rid] == want, f"{name} → {rid} {want}")

    # 必填字段与类型
    d = write_skill(root, "missing-fields", evals={
        "skill_name": "missing-fields",
        "evals": [{"id": 1, "prompt": "p"}, {"id": 2, "prompt": "", "expected_output": "e"}],
    })
    report = evalx.check_evals(d)
    ev = evidence_of(report, "EVAL-003")
    check(statuses(report)["EVAL-003"] == FAIL and "expected_output" in ev and "prompt" in ev,
          "缺 expected_output 与空 prompt 都被点名")

    # 重复 id / skill_name 不一致 / 空洞与脆弱断言
    d = write_skill(root, "dupes", evals={
        "skill_name": "not-this-skill",
        "evals": [
            {"id": 1, "prompt": "p", "expected_output": "e",
             "assertions": ["The output is good", "It must use exactly the phrase 'Total: $1'"]},
            {"id": 1, "prompt": "p2", "expected_output": "e2"},
        ],
    })
    report = evalx.check_evals(d)
    st = statuses(report)
    check(st["EVAL-006"] == WARN and "id=1" in evidence_of(report, "EVAL-006"), "重复 id → WARN")
    check(st["EVAL-007"] == WARN and "not-this-skill" in evidence_of(report, "EVAL-007"),
          "skill_name 与技能名不一致 → WARN")
    ev9 = evidence_of(report, "EVAL-009")
    check(st["EVAL-009"] == WARN and "空洞" in ev9 and "脆弱" in ev9,
          "空洞断言与脆弱断言都被指出")

    # 合法但不推荐：只有 1 条用例
    d = write_skill(root, "one-case", evals={
        "skill_name": "one-case",
        "evals": [{"id": 1, "prompt": "p", "expected_output": "e"}],
    })
    check(statuses(evalx.check_evals(d))["EVAL-008"] == INFO, "只有 1 条用例 → INFO 而非 WARN")

    # 坏 JSON 与 BOM
    d = write_skill(root, "bad-json")
    (d / "evals").mkdir(parents=True, exist_ok=True)
    (d / "evals" / "evals.json").write_text("{ nope", encoding="utf-8", newline="")
    report = evalx.check_evals(d)
    check(statuses(report)["EVAL-001"] == FAIL
          and "JSON 语法错误" in evidence_of(report, "EVAL-001"), "JSON 语法错误 → FAIL 并给行列")
    check(statuses(report)["EVAL-003"] == SKIP, "解析失败时后续规则记 SKIP")

    d = write_skill(root, "bom")
    payload = json.dumps(OFFICIAL_EVALS, ensure_ascii=False).encode("utf-8")
    (d / "evals").mkdir(parents=True, exist_ok=True)
    (d / "evals" / "evals.json").write_bytes(b"\xef\xbb\xbf" + payload)
    check(statuses(evalx.check_evals(d))["EVAL-001"] == PASS,
          "带 BOM 的 JSON 被宽容读取（不报误导性的语法错误）")


# --------------------------------------------------------------------------- #
# grading.json
# --------------------------------------------------------------------------- #


def run_grading(tmp: Path) -> None:
    print("[test_grading]")
    root = tmp / "gr"

    # 缺 summary：旧体系静默放过；本实现必须报出来
    skill = write_skill(root, "csv-analyzer", evals=OFFICIAL_EVALS,
                        files={"evals/files/sales_2025.csv": "x",
                               "evals/files/customers.csv": "x"})
    ws = build_workspace(root)
    path = ws / "iteration-1" / "eval-top-months-chart" / "with_skill" / "grading.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["summary"]
    write_json(path, data)
    report = evalx.check_evals(skill)
    check(statuses(report)["GRAD-001"] == FAIL and "summary" in evidence_of(report, "GRAD-001"),
          "grading.json 缺 summary → FAIL（旧体系此处静默放过）")
    build_workspace(root)  # 复原

    # summary 与逐条不一致（手填的 summary 会骗人）
    data = json.loads(path.read_text(encoding="utf-8"))
    data["summary"] = {"passed": 1, "failed": 1, "total": 2, "pass_rate": 0.5}
    write_json(path, data)
    report = evalx.check_evals(skill)
    check(statuses(report)["GRAD-003"] == FAIL
          and "summary" in evidence_of(report, "GRAD-003"),
          "summary 与实际通过数不符 → FAIL")
    build_workspace(root)

    # 四舍五入过的 pass_rate 必须放过（旧体系用 1e-9 精确比较，0.67 vs 2/3 会误判）
    it = ws / "iteration-1" / "eval-three"
    arm(it.parent, "eval-three", "with_skill", assertions=["a", "b", "c"],
        passed=[True, True, False], tokens=100, ms=200)
    arm(it.parent, "eval-three", "without_skill", assertions=["a", "b", "c"],
        passed=[False, False, False], tokens=50, ms=100)
    data = json.loads((it / "with_skill" / "grading.json").read_text(encoding="utf-8"))
    data["summary"]["pass_rate"] = 0.67
    write_json(it / "with_skill" / "grading.json", data)
    report = evalx.check_evals(skill, iteration=1)
    check(statuses(report)["GRAD-003"] == PASS,
          "四舍五入的 pass_rate=0.67（2/3）被放过")

    # 布尔值冒充整数 / 非布尔 passed / PASS 无证据
    arm(root / "gr2" / "csv-analyzer-workspace-probe", "eval-x", "with_skill",
        assertions=["a"], passed=[True], tokens=1, ms=1)
    probe = root / "gr2" / "csv-analyzer-workspace-probe" / "eval-x" / "with_skill"
    write_json(probe / "timing.json", {"total_tokens": True, "duration_ms": 10})
    write_json(probe / "grading.json", {"assertion_results": [
        {"text": "a", "passed": "true", "evidence": ""},
    ], "summary": {"passed": 1, "failed": 0, "total": 1, "pass_rate": 1.0}})
    skill2 = write_skill(root / "gr2", "csv-analyzer", evals=OFFICIAL_EVALS)
    (root / "gr2" / "csv-analyzer" / "evals" / "files").mkdir(parents=True, exist_ok=True)
    (root / "gr2" / "csv-analyzer" / "evals" / "files" / "sales_2025.csv").write_text("x")
    (root / "gr2" / "csv-analyzer" / "evals" / "files" / "customers.csv").write_text("x")
    # 该工作区少一层 iteration-N：用显式 --workspace 指向它
    report = evalx.check_evals(skill2, workspace=root / "gr2" / "csv-analyzer-workspace-probe")
    check(statuses(report)["WS-001"] == WARN, "工作区没有 iteration-N 目录 → WS-001 WARN")

    # 单臂工作区：直接构造 iteration-1 结构来测类型与证据
    ws3 = root / "gr3" / "csv-analyzer-workspace"
    it3 = ws3 / "iteration-1"
    arm(it3, "eval-a", "with_skill", assertions=["a"], passed=[True], tokens=1, ms=1,
        evidence="引用 outputs/result.txt 第 3 行")
    arm(it3, "eval-a", "without_skill", assertions=["a"], passed=[False], tokens=1, ms=1,
        evidence="未产出该文件")
    write_json(it3 / "benchmark.json", {
        "run_summary": {
            "with_skill": {"pass_rate": {"mean": 1.0}, "time_seconds": {"mean": 0.001},
                           "tokens": {"mean": 1}},
            "without_skill": {"pass_rate": {"mean": 0.0}, "time_seconds": {"mean": 0.001},
                              "tokens": {"mean": 1}},
            "delta": {"pass_rate": 1.0, "time_seconds": 0.0, "tokens": 0},
        }})
    skill3 = write_skill(root / "gr3", "csv-analyzer", evals=OFFICIAL_EVALS)
    for ref in ("sales_2025.csv", "customers.csv"):
        p = root / "gr3" / "csv-analyzer" / "evals" / "files" / ref
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    path3 = it3 / "eval-a" / "with_skill" / "grading.json"
    d3 = json.loads(path3.read_text(encoding="utf-8"))
    d3["assertion_results"][0]["passed"] = "true"
    write_json(path3, d3)
    report = evalx.check_evals(skill3)
    check(statuses(report)["GRAD-002"] == FAIL and "passed" in evidence_of(report, "GRAD-002"),
          "passed 写成字符串 \"true\" → FAIL（不做真值转换）")

    d3 = json.loads(path3.read_text(encoding="utf-8"))
    d3["assertion_results"][0]["passed"] = True
    d3["assertion_results"][0]["evidence"] = ""
    write_json(path3, d3)
    report = evalx.check_evals(skill3)
    check(statuses(report)["GRAD-004"] == FAIL and "PASS 没有 evidence" in
          evidence_of(report, "GRAD-004"),
          "PASS 却没有 evidence → FAIL（官方要求 PASS 必须有具体证据）")

    d3["assertion_results"][0]["evidence"] = "有证据"
    d3["assertion_results"][0]["text"] = "一条 evals.json 里没有的断言"
    write_json(path3, d3)
    report = evalx.check_evals(skill3)
    check(statuses(report)["GRAD-005"] == WARN, "断言文本不在 evals.json 里 → WARN")

    # 同一 eval 目录两侧断言集合不一致
    d3["assertion_results"][0]["text"] = "a"
    write_json(path3, d3)
    other = it3 / "eval-a" / "without_skill" / "grading.json"
    d4 = json.loads(other.read_text(encoding="utf-8"))
    d4["assertion_results"][0]["text"] = "完全不同的断言"
    write_json(other, d4)
    report = evalx.check_evals(skill3)
    check(statuses(report)["WS-005"] == WARN, "两侧断言集合不一致 → WARN")


# --------------------------------------------------------------------------- #
# timing / benchmark
# --------------------------------------------------------------------------- #


def run_benchmark(tmp: Path) -> None:
    print("[test_benchmark]")
    root = tmp / "bm"
    skill = write_skill(root, "csv-analyzer", evals=OFFICIAL_EVALS)
    ref = root / "csv-analyzer" / "evals" / "files"
    ref.mkdir(parents=True, exist_ok=True)
    for name in ("sales_2025.csv", "customers.csv"):
        (ref / name).write_text("x")

    ws = build_workspace(root)
    report = evalx.check_evals(skill)
    interesting = {rid: st for rid, st in statuses(report).items()
                   if rid.startswith(("BENCH", "TIME", "WS"))}
    bad = {rid: st for rid, st in interesting.items() if st in (FAIL, WARN)}
    check(not bad, f"正确的工作区：BENCH/TIME/WS 全绿（异常：{bad}）")

    # delta 与两侧 mean 不符
    it = ws / "iteration-1"
    bench = json.loads((it / "benchmark.json").read_text(encoding="utf-8"))
    bench["run_summary"]["delta"]["tokens"] = 999
    write_json(it / "benchmark.json", bench)
    report = evalx.check_evals(skill)
    check(statuses(report)["BENCH-003"] == WARN and "999" in evidence_of(report, "BENCH-003"),
          "delta 与两侧 mean 之差不符 → WARN（旧体系从不做这个对账）")
    build_workspace(root)

    # 聚合值与逐次产物不符
    bench = json.loads((it / "benchmark.json").read_text(encoding="utf-8"))
    bench["run_summary"]["with_skill"]["tokens"]["mean"] = 5000
    write_json(it / "benchmark.json", bench)
    report = evalx.check_evals(skill)
    check(statuses(report)["BENCH-004"] == WARN and "tokens" in evidence_of(report, "BENCH-004"),
          "聚合 tokens.mean 与逐次 timing 不符 → WARN")
    build_workspace(root)

    # sample stddev（n-1）也必须被接受——官方没定义用哪种
    bench = json.loads((it / "benchmark.json").read_text(encoding="utf-8"))
    bench["run_summary"]["with_skill"]["tokens"]["stddev"] = 141.42  # sample stddev
    write_json(it / "benchmark.json", bench)
    report = evalx.check_evals(skill)
    check(statuses(report)["BENCH-004"] == PASS,
          "样本标准差（n-1）与总体标准差都被接受（官方未定义口径）")
    build_workspace(root)

    # 布尔冒充整数
    timing = it / "eval-top-months-chart" / "with_skill" / "timing.json"
    write_json(timing, {"total_tokens": True, "duration_ms": 2000})
    report = evalx.check_evals(skill)
    check(statuses(report)["TIME-001"] == FAIL and "total_tokens" in evidence_of(report, "TIME-001"),
          "timing 里 true 冒充整数 → FAIL（Python 里 bool 是 int 的子类）")
    build_workspace(root)

    # 负值
    write_json(timing, {"total_tokens": -1, "duration_ms": 2000})
    report = evalx.check_evals(skill)
    check(statuses(report)["TIME-001"] == FAIL and "不得为负" in evidence_of(report, "TIME-001"),
          "timing 负值 → FAIL")

    # 缺基线：技能价值无从判断
    shutil.rmtree(root / "csv-analyzer-workspace")
    build_workspace(root, skip_baseline=True)
    report = evalx.check_evals(skill)
    st = statuses(report)
    check(st["WS-002"] == WARN and "without_skill" in evidence_of(report, "WS-002"),
          "缺基线 arm → WS-002 WARN 并点名")
    check(st["BENCH-001"] == FAIL and "基线" in evidence_of(report, "BENCH-001"),
          "benchmark 缺基线 → BENCH-001 FAIL")
    build_workspace(root)

    # 增益方向：with < without
    bench = json.loads((it / "benchmark.json").read_text(encoding="utf-8"))
    bench["run_summary"]["with_skill"]["pass_rate"] = {"mean": 0.1, "stddev": 0.0}
    bench["run_summary"]["without_skill"]["pass_rate"] = {"mean": 0.9, "stddev": 0.0}
    bench["run_summary"]["delta"]["pass_rate"] = -0.8
    write_json(it / "benchmark.json", bench)
    report = evalx.check_evals(skill)
    check(statuses(report)["BENCH-006"] == WARN, "with_skill 低于基线 → BENCH-006 WARN")
    build_workspace(root)

    # delta 为空对象：结构上存在，不算缺
    bench = json.loads((it / "benchmark.json").read_text(encoding="utf-8"))
    bench["run_summary"]["delta"] = {}
    write_json(it / "benchmark.json", bench)
    report = evalx.check_evals(skill)
    check(statuses(report)["BENCH-003"] == WARN
          and "delta.tokens 缺失" in evidence_of(report, "BENCH-003"),
          "空 delta → 逐项报缺失（不是「对象不存在」）")
    build_workspace(root)


# --------------------------------------------------------------------------- #
# 工作区结构
# --------------------------------------------------------------------------- #


def run_workspace(tmp: Path) -> None:
    print("[test_workspace]")
    root = tmp / "ws"
    skill = write_skill(root, "csv-analyzer", evals=OFFICIAL_EVALS)
    ref = root / "csv-analyzer" / "evals" / "files"
    ref.mkdir(parents=True, exist_ok=True)
    for name in ("sales_2025.csv", "customers.csv"):
        (ref / name).write_text("x")

    ws = build_workspace(root)
    report = evalx.check_evals(skill)
    st = statuses(report)
    check(st["WS-001"] == PASS and st["WS-003"] == PASS and st["WS-006"] == PASS,
          "正确工作区：WS-001/003/006 全 PASS")
    check(st["WS-007"] == PASS and "1 条为空" in evidence_of(report, "WS-007"),
          "feedback.json 官方形状被接受并统计空反馈数")

    # 缺 outputs/ 与 timing.json
    shutil.rmtree(ws / "iteration-1" / "eval-clean-missing-emails" / "with_skill" / "outputs")
    (ws / "iteration-1" / "eval-clean-missing-emails" / "with_skill" / "timing.json").unlink()
    report = evalx.check_evals(skill)
    ev = evidence_of(report, "WS-003")
    check(statuses(report)["WS-003"] == WARN and "outputs/" in ev and "timing.json" in ev,
          "缺 outputs/ 与 timing.json → WS-003 WARN 并点名缺什么")
    build_workspace(root)

    # 迭代编号缺号
    it = ws / "iteration-1"
    (ws / "iteration-3").mkdir(parents=True, exist_ok=True)
    shutil.copytree(it / "eval-top-months-chart", ws / "iteration-3" / "eval-top-months-chart")
    write_json(ws / "iteration-3" / "benchmark.json", _benchmark())
    report = evalx.check_evals(skill)
    check(statuses(report)["WS-004"] == WARN and "缺 iteration-2" in evidence_of(report, "WS-004"),
          "iteration 缺号 → WS-004 WARN 并指出缺哪一号")
    shutil.rmtree(ws / "iteration-3")

    # 缺 benchmark
    (ws / "iteration-1" / "benchmark.json").unlink()
    report = evalx.check_evals(skill)
    check(statuses(report)["WS-006"] == WARN and statuses(report)["BENCH-001"] == SKIP,
          "缺 benchmark.json → WS-006 WARN + BENCH 记 SKIP（未执行）")
    build_workspace(root)

    # feedback.json 是数组（旧体系方言）
    write_json(ws / "feedback.json", [{"text": "x", "passed": True}])
    report = evalx.check_evals(skill)
    check(statuses(report)["WS-007"] == WARN and "旧体系方言" in evidence_of(report, "WS-007"),
          "feedback.json 数组方言 → WARN 并说明官方形状")

    # --iteration 过滤 + 第二轮
    shutil.rmtree(root / "csv-analyzer-workspace")
    build_workspace(root, second_iteration=True)
    report = evalx.check_evals(skill)
    check(statuses(report)["WS-004"] == PASS and statuses(report)["BENCH-006"] == PASS,
          "两轮迭代齐备时编号连续、增益为正")
    report = evalx.check_evals(skill, iteration=2)
    check("iteration-2" in evidence_of(report, "WS-001") or statuses(report)["WS-001"] == PASS,
          "--iteration 过滤生效")
    report = evalx.check_evals(skill, iteration=9)
    check(statuses(report)["WS-001"] == INFO and "没有 iteration-9" in evidence_of(report, "WS-001"),
          "指定的 iteration 不存在 → 全部记 INFO（不适用）")

    # 显式 --workspace
    other = root / "elsewhere"
    other.mkdir(parents=True, exist_ok=True)
    report = evalx.check_evals(skill, workspace=other)
    check(statuses(report)["WS-001"] == WARN and statuses(report)["WS-002"] == SKIP,
          "空工作区 → WS-001 WARN + 其余 SKIP")

    # 后门回归：references/ 下的散落 grading.json 不得被当成产物
    build_workspace(root)
    stray = skill / "references" / "gate-d" / "grading.json"
    write_json(stray, {"assertion_results": [{"text": "散落", "passed": "no", "evidence": ""}],
                       "summary": {}})
    report = evalx.check_evals(skill)
    check(statuses(report)["GRAD-001"] == PASS,
          "references/ 下的散落 grading.json 不参与校验（旧体系按文件名任意深度抓取）")


# --------------------------------------------------------------------------- #
# 没有评测资产 / 阶段整合
# --------------------------------------------------------------------------- #


def run_no_evals_and_stages(tmp: Path) -> None:
    print("[test_no_evals_and_stages]")
    root = tmp / "ne"
    bare = write_skill(root, "bare-skill")
    report = evalx.check_evals(bare)
    st = statuses(report)
    check(st["EVAL-000"] == WARN and report.exit_code() == 2,
          f"没有评测资产 → EVAL-000 WARN，exit=2（不是 0）")
    check(all(v == INFO for k, v in st.items() if k != "EVAL-000"),
          "其余规则记 INFO（不适用），不冒充 PASS")

    # CLI：evals 命令 + check/deliver 的 --stages
    skill = write_skill(root, "csv-analyzer", evals=OFFICIAL_EVALS)
    ref = root / "csv-analyzer" / "evals" / "files"
    ref.mkdir(parents=True, exist_ok=True)
    for name in ("sales_2025.csv", "customers.csv"):
        (ref / name).write_text("x")
    code, out, _err = run_cli(["evals", str(skill), "--json"])
    payload = json.loads(out)
    rids = {r["rid"] for r in payload["results"]}
    check(code == 2 and payload["stage"] == "evals"
          and any(r.startswith("EVAL-") for r in rids)
          and any(r.startswith("TRIG-") for r in rids),
          f"`evals` 命令同时跑官方资产与触发资产（官方绿、无触发资产 → TRIG-000 WARN → "
          f"exit=2，实得 {code}）")

    code, out, _err = run_cli(["evals", str(bare), "--json"])
    check(code == 2, "`evals` 对无评测资产的技能返回 2（提示而非静默通过）")

    home = tmp / "ne-home"
    home.mkdir(parents=True, exist_ok=True)
    code, out, _err = run_cli(["check", "--project", str(root), "--root", str(root), "--user-home", str(home),
                               "--stages", "evals", "--json"])
    payload = json.loads(out)
    rids = {r["rid"] for s in payload["skills"] for r in s["results"]}
    check(any(rid.startswith("EVAL-") for rid in rids) and not any(
        rid.startswith("HYG-") for rid in rids), "--stages evals 只含评测规则")

    code, out, _err = run_cli(["check", "--project", str(root), "--root", str(root), "--user-home", str(home),
                               "--stages", "all", "--json"])
    payload = json.loads(out)
    rids = {r["rid"] for s in payload["skills"] for r in s["results"]}
    check(any(rid.startswith("SKILL-") for rid in rids) and any(rid.startswith("HYG-") for rid in rids)
          and any(rid.startswith("EVAL-") for rid in rids), "--stages all 覆盖三个阶段")

    code, out, _err = run_cli(["check", "--project", str(root), "--root", str(root), "--user-home", str(home),
                               "--stages", "both", "--json"])
    payload = json.loads(out)
    rids = {r["rid"] for s in payload["skills"] for r in s["results"]}
    check(not any(rid.startswith("EVAL-") for rid in rids),
          "--stages both 保持 spec+lint（向后兼容）")

    # deliver 门禁：无评测资产只是 WARN，不阻断；旧方言是 FAIL，阻断
    code, _out, err = run_cli(["deliver", "--project", str(root), "--root", str(root), "--user-home", str(home)])
    check(code == 0, f"deliver：无评测资产仅 WARN、不阻断（exit={code}）")
    check("待书面甄别" in err, "deliver 把无评测资产计入「待书面甄别」")

    dialect = write_skill(root, "dialect-skill", evals=LEGACY_DIALECT)
    code, _out, err = run_cli(["deliver", "--project", str(root), "--root", str(root), "--user-home", str(home),
                               "--stages", "evals", "--quiet"])
    check(code == 1 and "阻断 dialect-skill · EVAL-002" in err,
          f"deliver：旧方言评测资产阻断交付（exit={code}）")


# --------------------------------------------------------------------------- #
# dogfood
# --------------------------------------------------------------------------- #


def run_dogfood(repo: Path) -> None:
    print("[test_dogfood]")
    legacy = repo / "legacy"
    if not legacy.is_dir():
        ok("无 legacy/ 目录，跳过")
        return
    dialect = 0
    for target in sorted(p for p in legacy.iterdir()
                         if p.is_dir() and (p / "evals" / "evals.json").is_file()):
        report = evalx.check_evals(target)
        st = statuses(report)
        ev = evidence_of(report, "EVAL-002")
        dialect += 1 if st["EVAL-002"] == FAIL and "需迁移" in ev else 0
        print(f"  · {target.name}: exit={report.exit_code()} EVAL-002={st['EVAL-002']}")
    check(dialect == 4, f"legacy/ 下 4 个 evals.json 全部被识别为需迁移的旧方言（实得 {dialect}）")


# --------------------------------------------------------------------------- #


def main() -> int:
    force_utf8_stdio()
    parser = argparse.ArgumentParser(description="skillverify evalx 回归测试")
    parser.add_argument("--dogfood", action="store_true",
                        help="额外对 legacy/ 跑一遍并打印结论")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="sv_test_evalx_"))
    try:
        run_evals_json(tmp)
        run_grading(tmp)
        run_benchmark(tmp)
        run_workspace(tmp)
        run_no_evals_and_stages(tmp)
        if args.dogfood:
            run_dogfood(Path(__file__).resolve().parent.parent)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = len(_passed) + len(_failed)
    print(f"\n结果: PASS={len(_passed)} FAIL={len(_failed)} 合计={total}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
