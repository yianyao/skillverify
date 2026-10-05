"""review 回归测试（M5）。

**本文件守的是"评审到底有没有用"这件事**：
- 目录侧：29 条提示词必须条条带 PASS/FAIL 判据与证据要求（否则又回到"只有提示词"的旧状态）；
- 回写侧：只给结论、复述判据、FAIL 不写问题、NA 不写理由——全部要被拦下；
- 链路侧：任务包 → （模拟任意 LLM 填写）→ collect → 中央记录 → `deliver` 门禁读到结论。
  这条链路不依赖任何宿主：任务包是 Markdown + JSON，回写是同一个 JSON。

用法：
    python -m tests.test_review
    python -m tests.test_review --dogfood   # 可选：本地语料（默认 legacy/） 各技能跑一次 pack
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skillverify import cli, review  # noqa: E402
from skillverify.encoding import force_utf8_stdio  # noqa: E402
from skillverify.lint import lint_skill  # noqa: E402
from skillverify.report import FAIL, PASS, SKIP, WARN  # noqa: E402
from skillverify.spec import check_spec  # noqa: E402
from skillverify.watch import fingerprint  # noqa: E402

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


DESC = "A demo skill used by the semantic-review regression suite."

EXPECTED_IDS = (["D-01"] + [f"W-{i:02d}" for i in range(1, 17)]
                + [f"E-{i:02d}" for i in range(1, 11)] + ["R-01", "R-02"])


def write_skill(root: Path, name: str = "demo-skill", body: str = "# Demo\n") -> Path:
    target = root / name
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {DESC}\n---\n\n{body}",
        encoding="utf-8", newline="")
    return target


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


def statuses(report) -> dict[str, str]:
    return {r.rid: r.status for r in report.results}


def evidence_of(report, rid: str) -> str:
    return next((r.evidence for r in report.results if r.rid == rid), "")


def writeback(catalog: list[review.Prompt], ids: list[str], *, verdict: str = "PASS",
              evidence: str = "见 SKILL.md:12 的 description 字段", reviewer: str = "tester",
              skill: str = "demo-skill", tier: str = "pack") -> dict:
    return {
        "schema": review.WRITEBACK_SCHEMA,
        "skill": skill,
        "reviewer": reviewer,
        "tier": tier,
        "generated_at": "2026-10-04T10:00:00+08:00",
        "prompt_ids": list(ids),
        "results": [
            {"prompt_id": pid, "verdict": verdict, "evidence": evidence,
             "finding": "示例问题" if verdict == "FAIL" else "", "suggestion": ""}
            for pid in ids
        ],
    }


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="")


# --------------------------------------------------------------------------- #
# 目录
# --------------------------------------------------------------------------- #


def run_catalog(tmp: Path) -> None:
    print("[test_catalog]")
    catalog = review.load_catalog()
    ids = [p.id for p in catalog]
    # 旧体系 29 条**一条不少、编号不改**（M0 的约定）；但"只能有 29 条"不是约束：
    # 本项目允许新增（如 W-17 指令注入），前提是新增条目自己声明来历。
    legacy = [p.id for p in catalog if p.legacy_id]
    check(sorted(legacy) == sorted(EXPECTED_IDS),
          f"旧体系 29 条一一对应（缺: {sorted(set(EXPECTED_IDS) - set(legacy))}；"
          f"多: {sorted(set(legacy) - set(EXPECTED_IDS))}）")
    check(len(catalog) >= 29, f"目录至少含旧体系 29 条（实得 {len(catalog)}）")
    check(len(set(ids)) == len(ids), "id 无重复")

    added = [p for p in catalog if not p.legacy_id]
    bad_added = [p.id for p in added
                 if not p.legacy_source or "新增" not in p.legacy_source]
    check(not bad_added,
          f"新增条目必须自己声明来历（缺说明: {bad_added}）——"
          f"当前新增 {len(added)} 条: {', '.join(p.id for p in added)}")

    counts = {f: sum(1 for p in catalog if p.family == f) for f in review.FAMILY_ORDER}
    check(counts == {"D": 1, "W": 17, "E": 10, "R": 2},
          f"家族分布 = 旧体系 + 新增 W-17（实得 {counts}）")

    thin = [p.id for p in catalog if len(p.prompt) < 40]
    check(not thin, f"每条提示词都有实质指令（过于简短的: {thin}）")
    no_pass = [p.id for p in catalog if not p.pass_criteria]
    no_fail = [p.id for p in catalog if not p.fail_criteria]
    check(not no_pass and not no_fail, f"每条都有 PASS/FAIL 判据（缺: {no_pass + no_fail}）")
    weak_ev = [p.id for p in catalog if len(p.evidence_required) < 8]
    check(not weak_ev, f"每条都写了证据要求（缺: {weak_ev}）")
    no_when = [p.id for p in catalog if len(p.when) < 6]
    check(not no_when, f"每条都写了适用条件（缺: {no_when}）")
    bad_block = [p.id for p in catalog if not isinstance(p.blocking, bool)]
    check(not bad_block, f"blocking 均为布尔（异常: {bad_block}）")
    blocking = [p.id for p in catalog if p.blocking]
    check(0 < len(blocking) < len(catalog),
          f"阻断项既有又不过量（{len(blocking)} 条: {', '.join(blocking)}）")
    stages = {p.family: p.stage for p in catalog}
    check(stages == review.FAMILY_STAGE, "stage 与家族对应正确")

    md = review.render_prompts_md(catalog)
    missing = [p.id for p in catalog if f"### {p.id}" not in md]
    check(not missing, f"Markdown 渲染含全部条目（缺: {missing}）")
    check("PASS 判据" in md and "FAIL 判据" in md and "证据要求" in md,
          "Markdown 渲染含判据与证据要求小节")

    # runner 的指令模板必须与校验器同口径：早先它写 PASS|FAIL|NA|WARN，
    # 而 VERDICTS 只认三个——照文档填 WARN 的 runner 会被 REV-005 判 FAIL，
    # 档 1 流水线必然报错（"按文档写就会错"的硬伤）。
    from skillverify import runner
    check(runner.VERDICT_ENUM == "|".join(review.VERDICTS),
          f"runner 的 verdict 枚举从 VERDICTS 派生（实得 {runner.VERDICT_ENUM}）")
    check(f'"verdict": "{runner.VERDICT_ENUM}"' in runner._INSTRUCTION,
          "指令模板里出现的枚举与派生值一致（不是另写一份）")
    check("WARN" not in runner._INSTRUCTION.split("verdict")[1].split(",")[0],
          "指令模板的 verdict 取值里没有 WARN（校验器不认它）")

    # 选择器
    check(len(review.select_prompts(catalog, "W-01,W-13")) == 2, "--prompts 按 id 选择")
    check(len(review.select_prompts(catalog, None, ["W"])) == 17, "--family 按家族选择")
    try:
        review.select_prompts(catalog, "W-99")
        fail("未知 id 未报错")
    except review.CatalogError as exc:
        check("W-99" in str(exc), "未知 id 报错并点名")
    try:
        review.select_prompts(catalog, None, ["X"])
        fail("未知家族未报错")
    except review.CatalogError:
        ok("未知家族报错")

    # 目录损坏必须立刻炸，不得静默降级成空目录
    bad = tmp / "cat" / "bad.json"
    write_json(bad, {"prompts": [{"id": "W-01"}]})
    try:
        review.load_catalog(bad)
        fail("残缺目录未报错")
    except review.CatalogError as exc:
        check("缺字段" in str(exc), "残缺目录报错并说明缺什么")
    write_json(tmp / "cat" / "dup.json",
               {"prompts": [dict(review.load_catalog()[0].raw),
                            dict(review.load_catalog()[0].raw)]})
    try:
        review.load_catalog(tmp / "cat" / "dup.json")
        fail("重复 id 未报错")
    except review.CatalogError:
        ok("重复 id 报错")


# --------------------------------------------------------------------------- #
# 任务包
# --------------------------------------------------------------------------- #


def run_pack(tmp: Path) -> None:
    print("[test_pack]")
    root = tmp / "pk"
    skill = write_skill(root)
    catalog = review.load_catalog()
    chosen = review.select_prompts(catalog, "W-01,W-02,W-13")
    written = review.build_pack(skill, chosen, out_dir=root / "pack")
    names = sorted(p.name for p in written)
    check(names == ["demo-skill-review-manifest.json", "demo-skill-review-pack.md",
                    "demo-skill-review-template.json"],
          f"任务包含 md + 模板 + manifest（实得 {names}）")

    md = (root / "pack" / "demo-skill-review-pack.md").read_text(encoding="utf-8")
    check(all(f"### {p.id}" in md for p in chosen), "任务包含所选提示词")
    check("回写格式（必须遵守）" in md and review.WRITEBACK_SCHEMA in md,
          "任务包附了唯一的回写格式说明（不在每条提示词里重复）")
    check("不要复述判据" in md, "任务包写明了「不要复述判据」这条硬要求")

    manifest = json.loads((root / "pack" / "demo-skill-review-manifest.json")
                          .read_text(encoding="utf-8"))
    check(manifest["prompt_ids"] == [p.id for p in chosen], "manifest 记录本轮提示词")
    check(manifest["fingerprint"] == fingerprint(skill), "manifest 记录技能内容指纹")
    check(manifest["blocking_prompt_ids"] == [p.id for p in chosen if p.blocking],
          "manifest 记录哪些 FAIL 会阻断")

    template = json.loads((root / "pack" / "demo-skill-review-template.json")
                          .read_text(encoding="utf-8"))
    check([r["prompt_id"] for r in template["results"]] == [p.id for p in chosen],
          "模板预填了全部 prompt_id（评审者只需填结论）")
    check(template["reviewer"] == "" and template["schema"] == review.WRITEBACK_SCHEMA,
          "模板结构正确且 reviewer 待填")

    split_files = review.build_pack(skill, chosen, out_dir=root / "split", split=True)
    md_files = [p for p in split_files if p.suffix == ".md"]
    check(len(md_files) == len(chosen), f"--split 每条提示词一个文件（实得 {len(md_files)}）")


# --------------------------------------------------------------------------- #
# 回写校验
# --------------------------------------------------------------------------- #


def run_validate(tmp: Path) -> None:
    print("[test_validate]")
    catalog = review.load_catalog()

    good = writeback(catalog, ["W-01", "W-02"])
    results, normalized = review.validate_writeback(good, catalog)
    bad = [r.rid for r in results if r.status in (FAIL, WARN)]
    check(not bad and normalized["skill"] == "demo-skill",
          f"合格回写全通过（异常: {bad}）")

    def only(payload: dict, rid: str) -> str:
        st = statuses_of(review.validate_writeback(payload, catalog)[0])
        return st.get(rid, "")

    no_schema = dict(good)
    no_schema["schema"] = "something-else/1"
    check(only(no_schema, "REV-001") == FAIL, "schema 不符 → REV-001 FAIL")

    anon = dict(good)
    anon["reviewer"] = "  "
    check(only(anon, "REV-002") == FAIL, "reviewer 为空 → REV-002 FAIL（无签署=没评审）")

    empty = dict(good)
    empty["results"] = []
    check(only(empty, "REV-003") == FAIL, "results 为空 → REV-003 FAIL")

    unk = writeback(catalog, ["W-99"])
    check(only(unk, "REV-004") == FAIL, "未知 prompt_id → REV-004 FAIL")

    weird = writeback(catalog, ["W-01"], verdict="基本通过")
    check(only(weird, "REV-005") == FAIL, "verdict 非 PASS/FAIL/NA → REV-005 FAIL")

    thin = writeback(catalog, ["W-01"], evidence="符合要求")
    check(only(thin, "REV-006") == FAIL, "证据过短 → REV-006 FAIL")

    noloc = writeback(catalog, ["W-01"],
                      evidence="我逐条读过这个技能的说明文档并且认为它的写法是恰当的")
    check(only(noloc, "REV-006") == FAIL, "证据不可定位（无文件/行号/引用/计数）→ REV-006 FAIL")

    restate = writeback(catalog, ["W-01"],
                        evidence="见 SKILL.md:1 —— "
                                 + catalog[[p.id for p in catalog].index("W-01")].pass_criteria[0])
    check(only(restate, "REV-006") == WARN,
          "证据可定位但复述判据 → REV-006 WARN（不阻断但记下来）")

    # 判据里若自带 "SKILL.md" 这类可定位词，抄判据会落进复述分支（WARN）；
    # 判据里没有任何可定位词时，抄判据就是过于单薄（FAIL）。两条路径都要测。
    first = next(p for p in catalog if p.id == "D-01")
    copied = writeback(catalog, ["D-01"], evidence=first.pass_criteria[0])
    check(not review.LOCATABLE_RE.search(first.pass_criteria[0])
          and only(copied, "REV-006") == FAIL,
          "判据无可定位词时抄判据 → REV-006 FAIL")

    nofinding = writeback(catalog, ["W-01"], verdict="FAIL", evidence="见 SKILL.md:12 有问题")
    nofinding["results"][0]["finding"] = ""
    check(only(nofinding, "REV-007") == FAIL, "FAIL 未写问题 → REV-007 FAIL")

    na = writeback(catalog, ["W-01"], verdict="NA", evidence="")
    check(only(na, "REV-008") == FAIL, "NA 未写理由 → REV-008 FAIL")

    na_ok = writeback(catalog, ["W-01"], verdict="NA",
                      evidence="该技能没有 scripts/ 目录，本项不适用")
    check(only(na_ok, "REV-008") == PASS, "NA 写了理由 → REV-008 PASS")

    check(only({"schema": review.WRITEBACK_SCHEMA}, "REV-001") == PASS
          and only({"schema": review.WRITEBACK_SCHEMA}, "REV-003") == FAIL,
          "顶层对象但无 results → REV-003 FAIL（而非崩溃）")


def statuses_of(results: list) -> dict[str, str]:
    return {r.rid: r.status for r in results}


# --------------------------------------------------------------------------- #
# 汇总
# --------------------------------------------------------------------------- #


def run_collect(tmp: Path) -> None:
    print("[test_collect]")
    root = tmp / "co"
    skill = write_skill(root)
    catalog = review.load_catalog()
    ids = ["W-01", "W-02", "W-13"]
    good = root / "wb-good.json"
    write_json(good, writeback(catalog, ids))

    report, record = review.collect([good], catalog, skill_dir=skill, expected_ids=ids)
    check(report.exit_code() == 0 and record["verdict"] == "pass",
          f"覆盖完整的合格回写 → pass（实得 {record['verdict']}）")
    check(record["fingerprint"] == fingerprint(skill), "记录带上技能内容指纹")
    check(not record["uncovered_prompts"], "无未覆盖项")

    # 覆盖不完整
    report, record = review.collect([good], catalog, skill_dir=skill,
                                   expected_ids=ids + ["E-01"])
    check(record["uncovered_prompts"] == ["E-01"]
          and statuses(report)["REV-009"] == WARN, "声明的提示词没评 → 记未覆盖 + REV-009 WARN")

    # 阻断项 FAIL
    blocking_id = next(p.id for p in catalog if p.blocking)
    bad = root / "wb-blocking.json"
    write_json(bad, writeback(catalog, [blocking_id], verdict="FAIL",
                              evidence="见 SKILL.md:20 的破坏性命令"))
    report, record = review.collect([bad], catalog, skill_dir=skill, expected_ids=[blocking_id])
    check(report.exit_code() == 1 and record["verdict"] == "fail"
          and len(record["blocking_fails"]) == 1,
          f"阻断项 FAIL → fail 且计入 blocking_fails（实得 {record['verdict']}）")

    # 非阻断 FAIL → warn，不阻断
    nonblocking = next(p.id for p in catalog if not p.blocking)
    soft = root / "wb-soft.json"
    write_json(soft, writeback(catalog, [nonblocking], verdict="FAIL",
                               evidence="见 SKILL.md:8 的措辞"))
    _report, record = review.collect([soft], catalog, skill_dir=skill,
                                     expected_ids=[nonblocking])
    check(record["verdict"] == "warn" and not record["blocking_fails"],
          "非阻断 FAIL → warn 且不阻断交付")

    # 结论冲突（双评）
    a = root / "wb-a.json"
    b = root / "wb-b.json"
    write_json(a, writeback(catalog, ["W-01"], verdict="PASS",
                            evidence="见 SKILL.md:12", reviewer="甲"))
    write_json(b, writeback(catalog, ["W-01"], verdict="FAIL",
                            evidence="见 SKILL.md:12 描述过泛", reviewer="乙"))
    report, record = review.collect([a, b], catalog, skill_dir=skill, expected_ids=["W-01"])
    check(record["conflicts"] and statuses(report)["REV-010"] == WARN,
          "两份回写结论冲突 → 记冲突 + REV-010 WARN（须人工裁决）")
    check(sorted(record["reviewers"]) == ["乙", "甲"], "记录里保留双方签署")

    # 阻断项缺修复建议 → INFO（不阻断）
    _r, record_b = review.collect([bad], catalog, skill_dir=skill, expected_ids=[blocking_id])
    check(statuses(review.collect([bad], catalog, skill_dir=skill,
                                  expected_ids=[blocking_id])[0])["REV-011"] == WARN,
          "阻断项缺修复建议 → WARN（是缺口，但不必阻断交付）")

    # 落盘 + history 追加
    store = root / "store"
    first = review.write_record(store, record)
    review.write_record(store, record)
    history = (store / "history.jsonl").read_text(encoding="utf-8").strip().splitlines()
    check(first.is_file() and len(history) == 2, "记录落盘 + history.jsonl 逐次追加")
    check(json.loads(first.read_text(encoding="utf-8"))["schema"] == review.RECORD_SCHEMA,
          "记录 schema 正确")


# --------------------------------------------------------------------------- #
# REV-000：交付/检查流程读记录
# --------------------------------------------------------------------------- #


def run_check_review(tmp: Path) -> None:
    print("[test_check_review]")
    root = tmp / "cr"
    skill = write_skill(root)
    trace = root / "trace"
    catalog = review.load_catalog()
    ids = ["W-01", "W-02"]

    results = review.check_review(skill, trace)
    check(results[0].status == SKIP and results[0].optional,
          "无记录 → SKIP 且标 optional（记未覆盖项，默认不阻断）")
    results = review.check_review(skill, trace, skipped=True)
    check(results[0].status == SKIP and "显式" in results[0].evidence,
          "--skip-review → SKIP 且说明是显式跳过")

    wb = root / "wb.json"
    write_json(wb, writeback(catalog, ids))
    _report, record = review.collect([wb], catalog, skill_dir=skill, expected_ids=ids)
    review.write_record(trace / "review", record)
    results = review.check_review(skill, trace)
    check(results[0].status == PASS and "指纹" in results[0].evidence,
          f"新鲜且通过的记录 → PASS（实得 {results[0].status}: {results[0].evidence[:60]}）")

    # 技能改过 → 过期
    (skill / "SKILL.md").write_text(
        f"---\nname: demo-skill\ndescription: {DESC}\n---\n\n# Demo\n\n改过了。\n",
        encoding="utf-8", newline="")
    results = review.check_review(skill, trace)
    check(results[0].status == WARN and "过期" in results[0].evidence,
          "技能改过 → 记录过期 WARN（内容指纹比对，不看 mtime）")

    # 阻断项 FAIL
    blocking_id = next(p.id for p in catalog if p.blocking)
    wb2 = root / "wb2.json"
    write_json(wb2, writeback(catalog, [blocking_id], verdict="FAIL",
                              evidence="见 SKILL.md:5 有破坏性命令"))
    _report, record2 = review.collect([wb2], catalog, skill_dir=skill,
                                      expected_ids=[blocking_id])
    review.write_record(trace / "review", record2)
    results = review.check_review(skill, trace)
    check(results[0].status == FAIL and "阻断项" in results[0].evidence,
          "记录里有阻断项 FAIL → REV-000 FAIL（交付被拦）")

    # 覆盖不完整
    wb3 = root / "wb3.json"
    write_json(wb3, writeback(catalog, ids))
    _report, record3 = review.collect([wb3], catalog, skill_dir=skill,
                                      expected_ids=ids + ["E-05"])
    # 手工把未覆盖项保留进记录（collect 已按 expected_ids 算出）
    review.write_record(trace / "review", record3)
    results = review.check_review(skill, trace)
    check(results[0].status == WARN and "覆盖不完整" in results[0].evidence,
          "记录覆盖不完整 → WARN 并列出未评条目")


# --------------------------------------------------------------------------- #
# 独立技能包
# --------------------------------------------------------------------------- #


def run_emit_skill(tmp: Path) -> None:
    print("[test_emit_skill]")
    out = tmp / "sk"
    catalog = review.load_catalog()
    written = review.emit_skill(out, catalog)
    names = sorted(p.name for p in written)
    check(names == ["SKILL.md", "prompts.md", "review-prompts.json", "writeback.md"],
          f"技能包含 SKILL.md/参考文件/资产（实得 {names}）")

    target = out / "skillverify-review"
    skill_md = (target / "SKILL.md").read_text(encoding="utf-8")
    check(skill_md.startswith("---\nname: skillverify-review\n"), "frontmatter name 与目录名一致")
    check(len(skill_md.split("---")[1].split("description:")[1].split("\n")[0]) < 1024,
          "description 在官方长度上限内")
    asset = json.loads((target / "assets" / "review-prompts.json").read_text(encoding="utf-8"))
    check(len(asset["prompts"]) == len(review.load_catalog()),
          "资产里是同一份提示词目录（条数随目录走）")

    # 自洽性：我们产出的技能必须过我们自己的门禁
    _doc, spec_report = check_spec(target)
    lint_report = lint_skill(target)
    spec_fail = [r.rid for r in spec_report.results if r.status == FAIL]
    lint_fail = [r.rid for r in lint_report.results if r.status == FAIL]
    check(not spec_fail and not lint_fail,
          f"生成的技能包通过自己的 spec + lint（spec FAIL={spec_fail} lint FAIL={lint_fail}）")


# --------------------------------------------------------------------------- #
# CLI 全链路
# --------------------------------------------------------------------------- #


def run_cli_chain(tmp: Path) -> None:
    print("[test_cli_chain]")
    root = tmp / "cli"
    skill = write_skill(root, "chain-skill")
    home = root / "home"
    home.mkdir(parents=True, exist_ok=True)
    project = root / "proj"
    (project / ".agents" / "skills").mkdir(parents=True, exist_ok=True)
    shutil.copytree(skill, project / ".agents" / "skills" / "chain-skill")

    code, out, _err = run_cli(["review", "prompts", "--json"])
    payload = json.loads(out)
    check(code == 0 and len(payload["prompts"]) == len(review.load_catalog()),
          "`review prompts --json` 输出与目录一致")

    code, out, _err = run_cli(["review", "prompts", "--family", "W"])
    check(code == 0 and out.count("### W-") == 17, "`--family W` 只渲染 W 组 17 条")

    # ① 任务包
    pack_dir = root / "packout"
    code, out, _err = run_cli(["review", "pack", str(project / ".agents" / "skills" / "chain-skill"),
                               "--prompts", "W-01,W-02,W-13", "--out", str(pack_dir)])
    template = pack_dir / "chain-skill-review-template.json"
    check(code == 0 and template.is_file(), f"`review pack` 生成任务包（exit={code}）")

    # ② 模拟任意 LLM/人填写模板（这一步不依赖任何宿主）
    filled = json.loads(template.read_text(encoding="utf-8"))
    filled["reviewer"] = "示例 LLM"
    for item in filled["results"]:
        item["verdict"] = "PASS"
        item["evidence"] = "见 SKILL.md:12 的 description 字段，含具体关键词"
    filled_path = root / "filled.json"
    write_json(filled_path, filled)

    # ③ 汇总进中央记录
    code, out, err = run_cli(["review", "collect", str(filled_path),
                              "--skill-dir", str(project / ".agents" / "skills" / "chain-skill"),
                              "--project", str(project), "--user-home", str(home),
                              "--root", str(project / ".agents" / "skills"), "--quiet"])
    record_path = project / ".agents" / "skillverify" / "review" / "chain-skill.json"
    check(code == 0 and record_path.is_file(), f"`review collect` 落中央记录（exit={code}）")
    check("结论: pass" in err, "汇总结论输出到 stderr")

    # ④ status 能看到它
    code, out, _err = run_cli(["review", "status", "--project", str(project),
                               "--user-home", str(home),
                               "--root", str(project / ".agents" / "skills")])
    check(code == 0 and "chain-skill" in out and "pass" in out, "`review status` 列出记录与结论")

    # ⑤ deliver 读到记录 → REV-000 PASS（不再算未覆盖）
    code, out, err = run_cli(["deliver", "--project", str(project), "--user-home", str(home),
                              "--root", str(project / ".agents" / "skills"),
                              "--stages", "review", "--json"])
    gate = json.loads(out)["gate"]
    check(code == 0 and gate["result"] == "pass"
          and not any("REV-000" in x for x in gate["blockers"] + gate["uncovered"]),
          f"deliver 读到评审记录 → 门禁通过且不再算未覆盖（实得 {gate['result']}）")

    # ⑥ 阻断项 FAIL → deliver 拦住
    blocking_id = next(p.id for p in review.load_catalog() if p.blocking)
    bad = writeback(review.load_catalog(), [blocking_id], verdict="FAIL",
                    evidence="见 SKILL.md:20 直接 `rm -rf` 且无防护旗标",
                    skill="chain-skill")
    bad_path = root / "bad.json"
    write_json(bad_path, bad)
    run_cli(["review", "collect", str(bad_path),
             "--skill-dir", str(project / ".agents" / "skills" / "chain-skill"),
             "--project", str(project), "--user-home", str(home),
             "--root", str(project / ".agents" / "skills"), "--quiet"])
    code, out, err = run_cli(["deliver", "--project", str(project), "--user-home", str(home),
                              "--root", str(project / ".agents" / "skills"),
                              "--stages", "review", "--json"])
    gate = json.loads(out)["gate"]
    check(code == 1 and gate["result"] == "fail"
          and any("REV-000" in x for x in gate["blockers"]),
          f"阻断项 FAIL → deliver 门禁不通过（实得 {gate['result']}）")

    # ⑦ 一键跳过：记未覆盖项，默认不阻断，--strict 才阻断
    code, out, err = run_cli(["deliver", "--project", str(project), "--user-home", str(home),
                              "--root", str(project / ".agents" / "skills"),
                              "--stages", "review", "--skip-review", "--json"])
    gate = json.loads(out)["gate"]
    check(code == 0 and any("REV-000" in x for x in gate["uncovered"]),
          "`--skip-review` 一键跳过且留痕为未覆盖项")
    code, _out, _err = run_cli(["deliver", "--project", str(project), "--user-home", str(home),
                                "--root", str(project / ".agents" / "skills"),
                                "--stages", "review", "--skip-review", "--strict", "--quiet"])
    check(code == 1, "`--strict` 下未覆盖项阻断")

    # ⑧ review skill 生成独立技能包
    code, out, _err = run_cli(["review", "skill", "--out", str(root / "emitted")])
    check(code == 0 and (root / "emitted" / "skillverify-review" / "SKILL.md").is_file(),
          "`review skill` 生成可独立加载的技能包")

    # ⑨ 坏输入要有可诊断错误
    code, _out, err = run_cli(["review", "collect", str(root / "nope.json"),
                               "--project", str(project), "--user-home", str(home)])
    check(code == 1 and "文件不存在" in err, "采集不存在的文件 → exit 1 且说明原因")
    code, _out, err = run_cli(["review"])
    check(code == 1 and "用法" in err, "裸 `review` 打印用法")


# --------------------------------------------------------------------------- #
# 材料产出（E-02 / E-03 / E-06 / E-07 / E-08）
# --------------------------------------------------------------------------- #


def _mini_workspace(skill: Path) -> Path:
    """造一份最小可用工作区（一个 iteration、两个 arm、一份 benchmark）。"""
    ws = skill.parent / f"{skill.name}-workspace"
    it = ws / "iteration-1"
    for eval_name, arms in (("eval-one", {"with_skill": [True, False],
                                          "without_skill": [False, False]}),):
        for arm, flags in arms.items():
            d = it / eval_name / arm
            (d / "outputs").mkdir(parents=True, exist_ok=True)
            (d / "outputs" / "out.txt").write_text("x\n", encoding="utf-8", newline="")
            results = [{"text": f"断言 {i + 1}", "passed": f,
                        "evidence": "见 outputs/out.txt"} for i, f in enumerate(flags)]
            n_pass = sum(1 for f in flags if f)
            write_json(d / "grading.json", {
                "assertion_results": results,
                "summary": {"passed": n_pass, "failed": len(flags) - n_pass,
                            "total": len(flags), "pass_rate": round(n_pass / len(flags), 3)},
            })
            write_json(d / "timing.json", {"total_tokens": 100, "duration_ms": 2000})
    write_json(it / "benchmark.json", {
        "run_summary": {
            "with_skill": {"pass_rate": {"mean": 0.5, "stddev": 0.5},
                           "time_seconds": {"mean": 2.0, "stddev": 0.0},
                           "tokens": {"mean": 100, "stddev": 0.0}},
            "without_skill": {"pass_rate": {"mean": 0.0, "stddev": 0.0},
                              "time_seconds": {"mean": 2.0, "stddev": 0.0},
                              "tokens": {"mean": 100, "stddev": 0.0}},
            "delta": {"pass_rate": 0.5, "time_seconds": 0.0, "tokens": 0},
        }})
    write_json(ws / "feedback.json", {"eval-one": "图表缺少坐标轴标签"})
    return ws


def run_material(tmp: Path) -> None:
    print("[test_material]")
    from skillverify import material

    root = tmp / "mt"
    skill = write_skill(root, "mat-skill")

    # 什么都没有：四项都记 SKIP 并说明缺什么（而不是静默不产出）
    report, written = material.build_materials(skill, out_dir=root / "empty")
    st = statuses(report)
    check(st["MAT-001"] == SKIP and "git" in evidence_of(report, "MAT-001"),
          "非 git 仓库 → MAT-001 SKIP 并说明原因")
    check(st["MAT-004"] == SKIP and "工作区" in evidence_of(report, "MAT-004"),
          "没有工作区 → MAT-004 SKIP 并说明原因")
    check(st["MAT-003"] == SKIP and "--blind" in evidence_of(report, "MAT-003"),
          "没给两版产物 → MAT-003 SKIP 并说明怎么给")
    check(report.exit_code() == 2, f"材料都没产出 → exit=2（SKIP 计入，实得 {report.exit_code()}）")

    # 有工作区 → MAT-002/MAT-004 产出
    ws = _mini_workspace(skill)
    report, written = material.build_materials(skill, out_dir=root / "ws", workspace=ws)
    st = statuses(report)
    names = sorted(p.name for p in written)
    check(st["MAT-004"] == PASS and "workspace-digest.md" in names,
          f"有工作区 → 产出 workspace-digest.md（{names}）")
    check(st["MAT-002"] == PASS and "revision-signals.md" in names,
          "有工作区 → 产出 revision-signals.md")
    digest = (root / "ws" / "workspace-digest.md").read_text(encoding="utf-8")
    check("E-07、E-08" in digest and "0.5" in digest and "with_skill" in digest,
          "数字汇总写明了服务的提示词与实际数值")
    signals = (root / "ws" / "revision-signals.md").read_text(encoding="utf-8")
    check("E-03" in signals and "断言 2" in signals and "图表缺少坐标轴标签" in signals,
          "修订信号含失败断言与人工反馈")

    # 盲评：随机落到 A/B，映射封存
    left = root / "blind-src" / "old"
    right = root / "blind-src" / "new"
    for path, text in ((left, "旧版产物"), (right, "新版产物")):
        path.mkdir(parents=True, exist_ok=True)
        (path / "out.txt").write_text(text, encoding="utf-8", newline="")
    report, written = material.build_materials(
        skill, out_dir=root / "blind", blind=(left, right), blind_seed=7)
    st = statuses(report)
    blind_dir = root / "blind" / "blind"
    mapping = json.loads((blind_dir / "mapping.json").read_text(encoding="utf-8"))
    check(st["MAT-003"] == PASS and (blind_dir / "blind-A").is_dir()
          and (blind_dir / "blind-B").is_dir(),
          "给出两版产物 → 产出 blind-A/blind-B")
    check(sorted(mapping["mapping"]) == ["blind-A", "blind-B"]
          and set(mapping["mapping"].values()) == {str(left), str(right)},
          "映射封存在 mapping.json 且指向真实来源")
    check("不要打开" in (blind_dir / "README.md").read_text(encoding="utf-8"),
          "盲评说明里写明评审结束前不要看映射")

    # 同一种子可复现；不同种子允许不同（默认随机）
    report2, _w = material.build_materials(
        skill, out_dir=root / "blind2", blind=(left, right), blind_seed=7)
    mapping2 = json.loads((root / "blind2" / "blind" / "mapping.json").read_text(encoding="utf-8"))
    check(mapping2["mapping"] == mapping["mapping"], "--blind-seed 使 A/B 分配可复现")

    # git diff（E-02）：仓库里改了 SKILL.md 才有内容
    if shutil.which("git"):
        repo = root / "gitrepo"
        repo.mkdir(parents=True, exist_ok=True)
        gskill = write_skill(repo, "git-skill")
        subprocess.run(["git", "init", "-q"], cwd=repo, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "-m", "init"], capture_output=True)
        (gskill / "SKILL.md").write_text(
            f"---\nname: git-skill\ndescription: {DESC}（改过）\n---\n\n# D\n",
            encoding="utf-8", newline="")
        report, written = material.build_materials(gskill, out_dir=root / "diff")
        st = statuses(report)
        diff_file = root / "diff" / "description-diff.md"
        check(st["MAT-001"] == PASS and diff_file.is_file()
              and "改过" in diff_file.read_text(encoding="utf-8"),
              "git 仓库里有改动 → 产出 description-diff.md")
        # 没改动时明确说"没有改动"，而不是给个空文件
        subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "-m", "change"], capture_output=True)
        report, _w = material.build_materials(gskill, out_dir=root / "diff2")
        check(statuses(report)["MAT-001"] == SKIP
              and "没有改动" in evidence_of(report, "MAT-001"),
              "与基线无差异 → SKIP 并说明「没有改动」")
    else:
        ok("git 不可用：E-02 相关用例跳过")

    # CLI
    code, out, err = run_cli(["review", "material", str(skill), "--out", str(root / "cli"),
                              "--workspace", str(ws), "--json"])
    payload = json.loads(out)
    check(code == 2 and payload["stage"] == "material",
          f"`review material` 可用（有工作区但缺 diff/盲评 → exit=2，实得 {code}）")
    check("未能生成" in err, "未生成的材料在 stderr 有提示")


# --------------------------------------------------------------------------- #
# 档 1 执行器（review run --runner）
# --------------------------------------------------------------------------- #

#: 假评审命令的源码；用行列表拼装，避免多层引号互相截断
_RUNNER_SOURCES: dict[str, list[str]] = {
    "good": [
        "import json, re, sys",
        "payload = sys.stdin.read()",
        "m = re.search(r'提示词 (\\S+)：', payload)",
        "pid = m.group(1) if m else 'W-01'",
        "print('我来看看这个技能……')",
        "print('```json')",
        "print(json.dumps({'prompt_id': pid, 'verdict': 'PASS',",
        "                  'evidence': '见 SKILL.md:2 的 description 字段，含 CSV 与统计两个关键词',",
        "                  'finding': '', 'suggestion': ''}, ensure_ascii=False))",
        "print('```')",
    ],
    "bad_json": [
        "import sys",
        "sys.stdin.read()",
        "print('我觉得还行吧，没什么问题。')",
    ],
    "crash": [
        "import sys",
        "sys.stdin.read()",
        "sys.stderr.write('模型服务不可用')",
        "raise SystemExit(3)",
    ],
    "empty_evidence": [
        "import json, re, sys",
        "payload = sys.stdin.read()",
        "m = re.search(r'提示词 (\\S+)：', payload)",
        "pid = m.group(1) if m else 'W-01'",
        "print(json.dumps({'prompt_id': pid, 'verdict': 'PASS', 'evidence': ''}, ensure_ascii=False))",
    ],
}


def fake_runner(tmp: Path, mode: str) -> str:
    """写一个假的评审命令，返回可直接当 --runner 用的命令行。"""
    script = tmp / f"runner-{mode}.py"
    script.write_text("\n".join(_RUNNER_SOURCES[mode]) + "\n", encoding="utf-8", newline="")
    return f'"{sys.executable}" "{script}"'


def run_runner_suite(tmp: Path) -> None:
    print("[test_runner]")
    from skillverify import runner

    root = tmp / "run"
    skill = write_skill(root, "run-skill")

    # 正常：产出合法回写，且与档 2/档 3 走同一条校验
    good = fake_runner(tmp, "good")
    report, writeback = runner.run_runner(skill, good, prompt_ids=["W-01", "W-13"])
    check(statuses(report)["RUN-001"] == PASS and len(writeback["results"]) == 2,
          f"档 1 正常跑完（{len(writeback['results'])} 条；含围栏与寒暄的输出也能解析）")
    check(writeback["tier"] == "cli" and writeback["reviewer"].startswith("档 1 CLI："),
          "回写带 tier=cli，并以「实际跑的命令」作为签署")
    check(writeback["schema"] == "skillverify.review/1",
          "档 1 产出与档 2/档 3 完全相同的 schema")
    checks = runner.validate(writeback)
    bad = [r.rid for r in checks if r.status in (FAIL, WARN)]
    check(not bad, f"runner 产出通过同一条回写校验（异常：{bad}）")
    check(writeback["results"][0]["prompt_id"] == "W-01",
          "prompt_id 以我们的为准（runner 改不动归属）")

    # 结论再好也要过证据要求（三档共用同一条校验）
    empty = fake_runner(tmp, "empty_evidence")
    _rep, wb = runner.run_runner(skill, empty, prompt_ids=["W-01"])
    check(any(r.status == FAIL for r in runner.validate(wb)),
          "runner 的结论同样要过证据要求（空证据被拦下）")

    # 输出无法解析 → FAIL，且不写成 NA
    bad_json = fake_runner(tmp, "bad_json")
    report, writeback = runner.run_runner(skill, bad_json, prompt_ids=["W-01"])
    check(statuses(report)["RUN-001"] == FAIL and writeback["results"] == [],
          "输出不可解析 → RUN-001 FAIL（不伪装成 NA）")
    check(report.exit_code() == 1, "runner 失败时退出码非零")

    # runner 崩溃（非零退出）
    crash = fake_runner(tmp, "crash")
    report, _wb = runner.run_runner(skill, crash, prompt_ids=["W-01"])
    check(statuses(report)["RUN-001"] == FAIL
          and "退出码 3" in evidence_of(report, "RUN-001"),
          "runner 非零退出 → FAIL 且报出退出码")
    report, _wb = runner.run_runner(skill, crash, prompt_ids=["W-01"], allow_partial=True)
    check(statuses(report)["RUN-001"] == WARN, "--allow-partial 时只记 WARN")

    # CLI 端到端：产出可复核的回写文件 + --collect 写中央记录
    out_dir = root / "cli-out"
    code, out, err = run_cli(["review", "run", str(skill), "--runner", good,
                              "--prompts", "W-01,W-13", "--out", str(out_dir),
                              "--collect", "--project", str(root), "--json"])
    written = out_dir / "run-skill-review-cli.json"
    payload = json.loads(out)
    check(code == 0 and written.is_file(),
          f"`review run` 产出可复核的回写文件（exit={code}）")
    check(payload["stage"] == "review-run"
          and any(r["rid"].startswith("REV-") for r in payload["results"]),
          "CLI 把 collect 的校验结果一并汇总（档 1 不走捷径）")
    record = root / ".agents" / "skillverify" / "review" / "run-skill.json"
    check(record.is_file(), "`--collect` 把档 1 的结论写进中央记录")
    if record.is_file():
        stored = json.loads(record.read_text(encoding="utf-8"))
        check(stored["tiers"] == ["cli"] and stored["reviewers"][0].startswith("档 1 CLI："),
              f"中央记录里保留了档 1 的签署与来源（tiers={stored.get('tiers')}）")
    check("已生成" in err, "落盘提示走 stderr（不污染 --json 的 stdout）")

    # 缺 --runner 时明确报错，而不是静默什么都不做
    code, _out, err = run_cli(["review", "run", str(skill)])
    check(code == 1 and "--runner" in err, "缺 --runner → 明确报错")


# --------------------------------------------------------------------------- #
# dogfood
# --------------------------------------------------------------------------- #


def run_dogfood(repo: Path) -> None:
    print("[test_dogfood]")
    legacy = repo / "legacy"
    if not legacy.is_dir():
        ok("无 legacy/ 目录，跳过")
        return
    root = Path(tempfile.mkdtemp(prefix="sv_review_dog_"))
    try:
        catalog = review.load_catalog()
        count = 0
        for target in sorted(p for p in legacy.iterdir()
                             if p.is_dir() and (p / "SKILL.md").is_file()):
            written = review.build_pack(target, catalog, out_dir=root / target.name)
            count += 1
            print(f"  · {target.name}: 任务包 {len(written)} 个文件")
        check(count == 4, f"对 legacy/ 4 个技能都能生成任务包（实得 {count}）")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    force_utf8_stdio()
    parser = argparse.ArgumentParser(description="skillverify review 回归测试")
    parser.add_argument("--dogfood", action="store_true",
                        help="额外对 legacy/ 各技能生成任务包")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="sv_test_review_"))
    try:
        run_catalog(tmp)
        run_pack(tmp)
        run_validate(tmp)
        run_collect(tmp)
        run_check_review(tmp)
        run_emit_skill(tmp)
        run_cli_chain(tmp)
        run_material(tmp)
        run_runner_suite(tmp)
        if args.dogfood:
            run_dogfood(Path(__file__).resolve().parent.parent)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = len(_passed) + len(_failed)
    print(f"\n结果: PASS={len(_passed)} FAIL={len(_failed)} 合计={total}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
