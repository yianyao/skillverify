"""触发评测资产回归测试（M7 补的计划外项）。

**为什么这一层必须有测试**：触发评测是本项目**自己**的口径（官方不覆盖），
而且旧体系在这上面踩过真实的计分错误——非布尔的 `loaded` 会被悄悄当成"未触发"。
本文件把口径（正负各 8–10、约 20 条、train 60%、每条 3 次、阈值 0.5）
与那些坑都固化成断言。

用法：
    python -m tests.test_trigger
    python -m tests.test_trigger --dogfood   # 额外确认旧库资产被识别为「需迁移」
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import sys
from pathlib import Path
from typing import Callable

if __package__ == "" or __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skillverify import cli, trigger  # noqa: E402
from skillverify.encoding import force_utf8_stdio  # noqa: E402
from skillverify.tmpdir import new_temp_dir  # noqa: E402
from skillverify.report import FAIL, INFO, PASS, SKIP, WARN  # noqa: E402

_passed: list[str] = []
_failed: list[str] = []
_skipped: list[str] = []


def ok(msg: str) -> None:
    _passed.append(msg)
    print(f"  PASS {msg}")


def fail(msg: str) -> None:
    _failed.append(msg)
    print(f"  FAIL {msg}")


def skip(msg: str) -> None:
    """本项**未执行**（环境或前置条件缺失）：既不算通过、也不算失败。"""
    _skipped.append(msg)
    print(f"  SKIP {msg}")


def check(cond: bool, msg: str) -> None:
    ok(msg) if cond else fail(msg)


DESC = "A demo skill used by the trigger-asset regression suite."


def interleave(positives: int, negatives: int) -> list[tuple[str, bool]]:
    """正负例**交替**排列（P,N,P,N,…）。

    **为什么不能"正例全在前、负例全在后"再按下标切分**：那样 train 会拿走几乎所有正例、
    validation 只剩负例——而 validation 的用途正是"修订后测泛化"，只有负例就永远测不出
    "该触发时不触发"。`TRIG-005` 会（正确地）报出这种偏斜；夹具本身必须是像样的资产，
    否则注入自测的基线会被自己的 WARN 染脏（"切分全在 train"那处变异就失去信号）。
    """
    out: list[tuple[str, bool]] = []
    pi = ni = 0
    while pi < positives or ni < negatives:
        if pi < positives:
            out.append((f"P{pi + 1:02d}", True))
            pi += 1
        if ni < negatives:
            out.append((f"N{ni + 1:02d}", False))
            ni += 1
    return out


def make_queries(*, positives: int = 8, negatives: int = 8, train_share: float = 0.625,
                 near_miss: bool = True, categories: bool = True,
                 subset_of: Callable[[dict], str] | None = None) -> list[dict]:
    """造一份符合口径的查询集（正负各 8 条 = 16 条，train 占 62.5%）。

    `subset_of` 给出时按它决定每条的子集（用来构造"配比偏斜"这类反例）。
    """
    queries: list[dict] = []
    items = interleave(positives, negatives)
    train_count = round(len(items) * train_share)
    for idx, (pid, should) in enumerate(items):
        item = {
            "id": pid,
            "query": f"（示例查询 {pid}）帮我处理一下这份数据",
            "should_trigger": should,
            "subset": "train" if idx < train_count else "validation",
            "rationale": f"{pid} 的判定理由",
        }
        if categories:
            item["category"] = "positive-direct" if should else (
                "negative-near-miss" if near_miss else "negative-unrelated")
        queries.append(item)
    if subset_of is not None:
        for item in queries:
            item["subset"] = subset_of(item)
    return queries


def make_runs(queries: list[dict], *, runs: int = 3, pos_loaded: int | None = None,
              neg_loaded: int | None = None, bool_type: bool = True) -> list[dict]:
    records: list[dict] = []
    for item in queries:
        default = runs if item["should_trigger"] else 0
        loaded_count = (pos_loaded if item["should_trigger"] else neg_loaded)
        n_loaded = default if loaded_count is None else loaded_count
        for i in range(runs):
            records.append({
                "query_id": item["id"],
                "run": i + 1,
                "loaded": (i < n_loaded) if bool_type else ("true" if i < n_loaded else "false"),
                "evidence": f"第 {i + 1} 次运行的观察记录",
            })
    return records


def write_skill(root: Path, name: str = "demo-skill", *, queries: list[dict] | None = None,
                runs: list[dict] | None = None, skill_name: str | None = None) -> Path:
    target = root / name
    (target / "evals").mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {DESC}\n---\n\n# Demo\n",
        encoding="utf-8", newline="")
    if queries is not None:
        (target / "evals" / trigger.QUERYSET_NAME).write_text(json.dumps(
            {"skill_name": skill_name or name, "queries": queries},
            ensure_ascii=False, indent=2), encoding="utf-8", newline="")
    if runs is not None:
        (target / "evals" / trigger.RUNS_NAME).write_text(json.dumps(
            {"runs": runs}, ensure_ascii=False, indent=2), encoding="utf-8", newline="")
    return target


def statuses(report) -> dict[str, str]:
    return {r.rid: r.status for r in report.results}


def evidence_of(report, rid: str) -> str:
    return next((r.evidence for r in report.results if r.rid == rid), "")


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
    except BaseException:
        sys.stderr.write(f"[run_cli] argv={argv} 抛出异常，已捕获输出：\n"
                         f"--- stdout ---\n{out.getvalue()}\n--- stderr ---\n{err.getvalue()}\n")
        raise
    return code, out.getvalue(), err.getvalue()


# --------------------------------------------------------------------------- #
# 资产有无
# --------------------------------------------------------------------------- #


def run_presence(tmp: Path) -> None:
    print("[test_presence]")
    bare = write_skill(tmp / "bare", "bare-skill")
    report = trigger.check_trigger(bare)
    st = statuses(report)
    check(st["TRIG-000"] == WARN and report.exit_code() == 2,
          f"没有触发资产 → TRIG-000 WARN，exit=2（不是 0）")
    check(all(v == INFO for k, v in st.items() if k != "TRIG-000"),
          "其余规则记 INFO（不适用），不冒充 PASS")
    check(len(st) == len(trigger.RULES), f"全部 {len(trigger.RULES)} 条规则都产生记录")

    # 旧落点：要给迁移指引，而不是静默「没有资产」
    legacy = write_skill(tmp / "legacy-loc", "legacy-skill")
    legacy_dir = legacy / trigger.LEGACY_DIR
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / trigger.LEGACY_QUERYSET_NAME).write_text("{}", encoding="utf-8", newline="")
    ev = evidence_of(trigger.check_trigger(legacy), "TRIG-000")
    check("旧落点" in ev and trigger.QUERYSET_NAME in ev and "迁移" in ev,
          "检测到旧落点 → TRIG-000 给出迁移指引")

    good = write_skill(tmp / "good", queries=make_queries(),
                       runs=make_runs(make_queries()))
    report = trigger.check_trigger(good)
    bad = [r.rid for r in report.results if r.status in (FAIL, WARN)]
    check(report.exit_code() == 0 and not bad,
          f"口径内的资产全绿（异常: {bad}）")
    rids = [r.rid for r in report.results]
    dupes = sorted({rid for rid in rids if rids.count(rid) > 1})
    check(not dupes, f"报告里每条规则只出一行（重复: {dupes}）")
    check(statuses(report)["TRIG-000"] == PASS, "有资产 → TRIG-000 PASS")


# --------------------------------------------------------------------------- #
# 查询集
# --------------------------------------------------------------------------- #


def run_queryset(tmp: Path) -> None:
    print("[test_queryset]")
    root = tmp / "qs"

    broken = write_skill(root, "broken")
    (broken / "evals" / trigger.QUERYSET_NAME).write_text("{ nope", encoding="utf-8", newline="")
    report = trigger.check_trigger(broken)
    check(statuses(report)["TRIG-001"] == FAIL
          and "JSON 语法错误" in evidence_of(report, "TRIG-001"), "坏 JSON → TRIG-001 FAIL")
    check(statuses(report)["TRIG-002"] == SKIP, "解析失败时后续规则记 SKIP")

    d = write_skill(root, "no-name", queries=make_queries())
    data = json.loads((d / "evals" / trigger.QUERYSET_NAME).read_text(encoding="utf-8"))
    del data["skill_name"]
    (d / "evals" / trigger.QUERYSET_NAME).write_text(json.dumps(data), encoding="utf-8",
                                                    newline="")
    check(statuses(trigger.check_trigger(d))["TRIG-001"] == FAIL, "缺 skill_name → FAIL")

    # 字段类型：should_trigger 必须是严格布尔
    d = write_skill(root, "bool", queries=make_queries())
    data = json.loads((d / "evals" / trigger.QUERYSET_NAME).read_text(encoding="utf-8"))
    data["queries"][0]["should_trigger"] = "true"
    data["queries"][1]["subset"] = "testing"
    del data["queries"][2]["query"]
    (d / "evals" / trigger.QUERYSET_NAME).write_text(json.dumps(data), encoding="utf-8",
                                                    newline="")
    ev = evidence_of(trigger.check_trigger(d), "TRIG-002")
    check(statuses(trigger.check_trigger(d))["TRIG-002"] == FAIL
          and "should_trigger" in ev and "subset" in ev and "query" in ev,
          "字符串冒充布尔 / 非法 subset / 缺 query 都被点名")

    d = write_skill(root, "dupes", queries=make_queries())
    data = json.loads((d / "evals" / trigger.QUERYSET_NAME).read_text(encoding="utf-8"))
    data["queries"][1]["id"] = data["queries"][0]["id"]
    (d / "evals" / trigger.QUERYSET_NAME).write_text(json.dumps(data), encoding="utf-8",
                                                    newline="")
    check(statuses(trigger.check_trigger(d))["TRIG-003"] == FAIL, "重复 id → FAIL")

    # 规模与配比
    small = write_skill(root, "small", queries=make_queries(positives=5, negatives=3))
    check(statuses(trigger.check_trigger(small))["TRIG-004"] == WARN,
          "只有 8 条（每侧不足 8）→ TRIG-004 WARN")
    none_neg = write_skill(root, "none-neg", queries=make_queries(negatives=0))
    ev = evidence_of(trigger.check_trigger(none_neg), "TRIG-004")
    check("没有负例" in ev, "没有负例 → 明确指出")

    # 切分：口径**按条数**判（|实得 − 期望| ≤ 1 条），且两个子集的正负配比要与全集一致
    no_val = write_skill(root, "no-val", queries=make_queries(train_share=1.0))
    check(statuses(trigger.check_trigger(no_val))["TRIG-005"] == WARN
          and "validation" in evidence_of(trigger.check_trigger(no_val), "TRIG-005"),
          "全在 train（没有 validation）→ TRIG-005 WARN")
    skewed = write_skill(root, "skewed", queries=make_queries(train_share=0.9))
    check(statuses(trigger.check_trigger(skewed))["TRIG-005"] == WARN
          and "期望" in evidence_of(trigger.check_trigger(skewed), "TRIG-005"),
          "train 14/16 远超期望 10 条（差 4 条）→ WARN，证据里给出期望条数")
    check(statuses(trigger.check_trigger(
        write_skill(root, "ok-split", queries=make_queries())))["TRIG-005"] == PASS,
        "train 10/16（62.5%）与期望 10 条一致 → PASS")

    # 这条是"按条数"口径的**判别性**断言：12 条样本里 train=8 是 66.7%，
    # 落在旧的 ±0.05 比例带（55–65%）之外会被误报；差 1 条在容差内，必须放过。
    edge = write_skill(root, "edge", queries=make_queries(positives=6, negatives=6,
                                                          train_share=8 / 12))
    check(statuses(trigger.check_trigger(edge))["TRIG-005"] == PASS,
          "12 条里 train=8（差 1 条，比例 66.7% 在旧比例口径带外）→ PASS：容差是按条数的")

    # 配比偏斜：train 条数合格，但正例全在 train、validation 只剩负例
    seen = {"neg": 0}

    def biased_subset(item: dict) -> str:
        if item["should_trigger"]:
            return "train"
        seen["neg"] += 1
        return "train" if seen["neg"] <= 2 else "validation"

    biased = write_skill(root, "biased", queries=make_queries(subset_of=biased_subset))
    report = trigger.check_trigger(biased)
    check(statuses(report)["TRIG-005"] == WARN
          and "validation 的正例 0/" in evidence_of(report, "TRIG-005"),
          "正例全堆进 train（validation 只剩负例）→ WARN：泛化终测测不出漏触发")

    # near-miss 标注
    no_cat = write_skill(root, "no-cat", queries=make_queries(categories=False))
    check(statuses(trigger.check_trigger(no_cat))["TRIG-006"] == WARN,
          "负例没标 category → TRIG-006 WARN")
    unrel = write_skill(root, "unrelated", queries=make_queries(near_miss=False))
    check(statuses(trigger.check_trigger(unrel))["TRIG-006"] == WARN,
          "负例都不是 near-miss → WARN")
    check(statuses(trigger.check_trigger(
        write_skill(root, "near", queries=make_queries())))["TRIG-006"] == PASS,
        "负例标为 near-miss → PASS")


# --------------------------------------------------------------------------- #
# 运行记录与触发率
# --------------------------------------------------------------------------- #


def run_runs(tmp: Path) -> None:
    print("[test_runs]")
    root = tmp / "rn"
    queries = make_queries()

    bad_runs = write_skill(root, "bad-runs", queries=queries)
    (bad_runs / "evals" / trigger.RUNS_NAME).write_text("{ nope", encoding="utf-8", newline="")
    check(statuses(trigger.check_trigger(bad_runs))["TRIG-007"] == FAIL,
          "运行记录坏 JSON → TRIG-007 FAIL")

    no_runs = write_skill(root, "no-runs", queries=queries)
    report = trigger.check_trigger(no_runs)
    check(statuses(report)["TRIG-007"] == SKIP and "尚未跑过" in evidence_of(report, "TRIG-007"),
          "没跑过 → 运行相关规则记 SKIP（未执行，不当通过）")

    # 非布尔 loaded：旧体系会静默当成"未触发"，必须报出来
    mixed = make_runs(queries, bool_type=False)
    d = write_skill(root, "mixed", queries=queries, runs=mixed)
    report = trigger.check_trigger(d)
    check(statuses(report)["TRIG-007"] == FAIL
          and "loaded" in evidence_of(report, "TRIG-007"), "loaded 非布尔 → TRIG-007 FAIL")

    # 未知 query_id
    runs = make_runs(queries)
    runs.append({"query_id": "X99", "run": 1, "loaded": True, "evidence": "孤儿记录"})
    d = write_skill(root, "orphan", queries=queries, runs=runs)
    report = trigger.check_trigger(d)
    check(statuses(report)["TRIG-010"] == WARN
          and "X99" in evidence_of(report, "TRIG-010"), "running 记录里有未知 query_id → WARN")

    # 运行次数不足
    d = write_skill(root, "thin", queries=queries, runs=make_runs(queries, runs=2))
    report = trigger.check_trigger(d)
    check(statuses(report)["TRIG-008"] == WARN, "每条只跑 2 次 → TRIG-008 WARN")
    check(statuses(report)["TRIG-009"] == WARN
          and "数据不足" in evidence_of(report, "TRIG-009"),
          "次数不足时不给阈值结论（WARN「数据不足」）")

    # 触发率：正例不触发 / 负例乱触发
    d = write_skill(root, "low-pos", queries=queries,
                    runs=make_runs(queries, pos_loaded=1, neg_loaded=0))
    report = trigger.check_trigger(d)
    check(statuses(report)["TRIG-009"] == FAIL
          and "正例" in evidence_of(report, "TRIG-009"),
          "正例触发率 33%（≤50%）→ TRIG-009 FAIL")

    d = write_skill(root, "hot-neg", queries=queries,
                    runs=make_runs(queries, pos_loaded=3, neg_loaded=3))
    report = trigger.check_trigger(d)
    check(statuses(report)["TRIG-009"] == FAIL
          and "负例" in evidence_of(report, "TRIG-009"),
          "负例触发率 100% → TRIG-009 FAIL")

    d = write_skill(root, "ok", queries=queries, runs=make_runs(queries))
    report = trigger.check_trigger(d)
    check(statuses(report)["TRIG-009"] == PASS and statuses(report)["TRIG-008"] == PASS,
          "正例 100% / 负例 0% / 每条 3 次 → 通过")

    # 边界：恰好 50% 不算通过（口径是 >0.5 / <0.5）
    mixed_runs = make_runs(queries, runs=4, pos_loaded=2, neg_loaded=2)
    d = write_skill(root, "boundary", queries=queries, runs=mixed_runs)
    report = trigger.check_trigger(d)
    check(statuses(report)["TRIG-009"] == FAIL,
          "恰好 50% 触发 → 不给通过（口径为严格大于/小于）")


# --------------------------------------------------------------------------- #
# 与 CLI / 阶段调度的整合
# --------------------------------------------------------------------------- #


def run_integration(tmp: Path) -> None:
    print("[test_integration]")
    root = tmp / "cl"
    good = write_skill(root, "good-skill", queries=make_queries(),
                       runs=make_runs(make_queries()))
    # 官方资产也补上：这样 `evals` 命令的两条线（官方 + 触发）都是绿的
    (good / "evals" / "files").mkdir(parents=True, exist_ok=True)
    (good / "evals" / "files" / "input.csv").write_text("a,b\n", encoding="utf-8", newline="")
    (good / "evals" / "evals.json").write_text(json.dumps({
        "skill_name": "good-skill",
        "evals": [{"id": 1, "prompt": "处理这份数据", "expected_output": "一份汇总结果",
                   "files": ["evals/files/input.csv"],
                   "assertions": ["输出包含汇总结果"]}],
    }, ensure_ascii=False, indent=2), encoding="utf-8", newline="")
    home = root / "home"
    home.mkdir(parents=True, exist_ok=True)

    code, out, _err = run_cli(["evals", str(good), "--json"])
    payload = json.loads(out)
    rids = {r["rid"] for r in payload["results"]}
    check(code == 0 and any(r.startswith("TRIG-") for r in rids)
          and payload["stage"] == "evals",
          f"`evals` 命令同时校验官方资产与触发资产（exit={code}）")

    # 只有官方 evals、没有触发资产 → TRIG-000 WARN → exit 2（可见的提示，不是静默通过）
    official_only = root / "official-only" / "demo-skill"
    (official_only / "evals" / "files").mkdir(parents=True)
    (official_only / "SKILL.md").write_text(
        f"---\nname: demo-skill\ndescription: {DESC}\n---\n\n# D\n",
        encoding="utf-8", newline="")
    (official_only / "evals" / "evals.json").write_text(json.dumps({
        "skill_name": "demo-skill",
        "evals": [{"id": 1, "prompt": "做点事", "expected_output": "结果",
                   "files": ["evals/files/x.csv"],
                   "assertions": ["输出包含结果文件"]}],
    }, ensure_ascii=False), encoding="utf-8", newline="")
    (official_only / "evals" / "files" / "x.csv").write_text("a,b\n", encoding="utf-8",
                                                             newline="")
    code, out, _err = run_cli(["evals", str(official_only), "--json"])
    payload = json.loads(out)
    st = {r["rid"]: r["status"] for r in payload["results"]}
    check(code == 2 and st["EVAL-000"] == PASS and st["TRIG-000"] == WARN,
          f"有官方资产但没触发资产 → TRIG-000 WARN 且 exit=2（实得 {code}）")

    code, out, _err = run_cli(["check", "--project", str(root), "--user-home", str(home),
                               "--root", str(root), "--stages", "evals", "--json"])
    payload = json.loads(out)
    rids = {r["rid"] for s in payload["skills"] for r in s["results"]}
    check(any(r.startswith("TRIG-") for r in rids),
          "--stages evals 包含触发评测规则")

    code, _out, err = run_cli(["deliver", "--project", str(root), "--user-home", str(home),
                               "--root", str(root), "--stages", "evals", "--quiet", "--verbose"])
    check(code == 0, f"触发资产的 WARN 不阻断交付（gate 只看 FAIL，实得 {code}）")


def run_dogfood(repo: Path) -> None:
    print("[test_dogfood]")
    legacy = repo / "legacy"
    if not legacy.is_dir():
        skip("无 legacy/ 目录：dogfood 未执行")
        return
    migrated = 0
    for target in sorted(p for p in legacy.iterdir()
                         if p.is_dir() and (p / trigger.LEGACY_DIR /
                                            trigger.LEGACY_QUERYSET_NAME).is_file()):
        report = trigger.check_trigger(target)
        ev = evidence_of(report, "TRIG-000")
        migrated += 1 if ("旧落点" in ev and "迁移" in ev) else 0
        print(f"  · {target.name}: TRIG-000={statuses(report)['TRIG-000']}")
    check(migrated >= 2,
          f"旧库里的触发资产被识别为旧落点并给出迁移指引（{migrated} 个技能）")


def main() -> int:
    force_utf8_stdio()
    parser = argparse.ArgumentParser(description="skillverify 触发评测资产回归测试")
    parser.add_argument("--dogfood", action="store_true",
                        help="额外确认旧库资产被识别为需迁移")
    args = parser.parse_args()

    tmp = new_temp_dir(prefix="sv_test_trigger_")
    try:
        run_presence(tmp)
        run_queryset(tmp)
        run_runs(tmp)
        run_integration(tmp)
        if args.dogfood:
            run_dogfood(Path(__file__).resolve().parent.parent)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = len(_passed) + len(_failed)
    print(f"\n结果: PASS={len(_passed)} FAIL={len(_failed)} SKIP={len(_skipped)} 合计={total}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
