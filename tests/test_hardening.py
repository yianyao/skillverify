"""A 组 8 项的回归断言（集中一套，避免在四个套件里各打一次补丁）。

覆盖：
- A1 许可：license 字段过长 / 声明了却没有随包许可文件 → WARN（`HYG-006/007`）
- A2 隐写：代码里的双向控制符 → FAIL；正文里的零宽字符 → WARN（`SEC-008`）
- A3 豁免通道：`deliver --accept RID --because 理由` 把阻断项记为「已豁免」并落盘；
  缺理由直接拒绝（`REQ`：豁免必须留书面理由）
- A4 评委校准：判错校准样本 → `REV-012` FAIL；判对 → PASS；没做 → INFO
- A5 断言区分度：跨轮次恒真的断言 → `EVAL-010` WARN；有区分度 → PASS
- A6 dry-run：声明了 `--dry-run` 却仍然改动目录 → `SCRIPT-009` FAIL；不改 → PASS
- A7 工作区历史：同名 iteration 内容变了 → 交付记录里报「历史被改动」
- A8 记录维度：交付记录里有 `environment` 与 `reviewers`（出问题能定位是谁、在什么环境判的）
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

from skillverify import cli  # noqa: E402
from skillverify.encoding import force_utf8_stdio  # noqa: E402
from skillverify.lint import lint_skill  # noqa: E402

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


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(argv)
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
    except BaseException:
        print("  ---- stdout ----\n" + out.getvalue()[-1500:])
        print("  ---- stderr ----\n" + err.getvalue()[-1500:])
        raise
    return code, out.getvalue(), err.getvalue()


def make_skill(root: Path, name: str, *, description: str = "A probe skill for hardening.",
               extra: dict[str, str] | None = None, license_value: str | None = None) -> Path:
    target = root / name
    target.mkdir(parents=True, exist_ok=True)
    fm = [f"name: {name}", f"description: {description}"]
    if license_value is not None:
        fm.append(f"license: {license_value}")
    (target / "SKILL.md").write_text(
        "---\n" + "\n".join(fm) + "\n---\n\n# Demo\n\n"
        "- **`scripts/tool.py`** —— 演示（`python scripts/tool.py --help`）\n",
        encoding="utf-8", newline="")
    for rel, content in (extra or {}).items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="")
    return target


def status_of(report, rid: str) -> str | None:
    for res in report.results:
        if res.rid == rid:
            return res.status
    return None


def evidence_of(report, rid: str) -> str:
    for res in report.results:
        if res.rid == rid:
            return res.evidence
    return ""


# --------------------------------------------------------------------------- #
# A1 许可（HYG-006/007）
# --------------------------------------------------------------------------- #
def run_license(tmp: Path) -> None:
    print("[test_license_v15]")
    plain = make_skill(tmp / "lic-a", "lic-a")
    report = lint_skill(plain)
    check(status_of(report, "HYG-006") == "INFO" and status_of(report, "HYG-007") == "INFO",
          "没声明 license → 两条都记 INFO（不适用）")

    long_lic = make_skill(tmp / "lic-b", "lic-b", license_value="MIT " + "x" * 260)
    report = lint_skill(long_lic)
    check(status_of(report, "HYG-006") == "WARN",
          f"license 字段过长 → HYG-006 WARN（实得 {status_of(report, 'HYG-006')}）")
    check(status_of(report, "HYG-007") == "WARN",
          "没有随包许可文件 → HYG-007 WARN")

    with_file = make_skill(tmp / "lic-c", "lic-c", license_value="MIT",
                           extra={"LICENSE": "MIT License\n"})
    report = lint_skill(with_file)
    check(status_of(report, "HYG-006") == "PASS" and status_of(report, "HYG-007") == "PASS",
          f"简短 license + 随包 LICENSE → 两条 PASS"
          f"（实得 {status_of(report, 'HYG-006')}/{status_of(report, 'HYG-007')}）")


# --------------------------------------------------------------------------- #
# A2 隐写（SEC-008）
# --------------------------------------------------------------------------- #
def run_steganography(tmp: Path) -> None:
    print("[test_steganography]")
    bidi = make_skill(tmp / "steg-a", "steg-a", extra={
        "scripts/tool.py": "import argparse\n\n# 隐藏\u202e的注释\n"
                           "p = argparse.ArgumentParser()\np.parse_args()\n"})
    report = lint_skill(bidi)
    check(status_of(report, "SEC-008") == "FAIL",
          f"代码里的双向控制符 → FAIL（实得 {status_of(report, 'SEC-008')}）")
    check("U+202E" in evidence_of(report, "SEC-008"), "证据里给出码位（便于定位与删除）")

    zero = make_skill(tmp / "steg-b", "steg-b", extra={
        "references/note.md": "正常文字\u200b里夹了一个零宽空格\n"})
    report = lint_skill(zero)
    check(status_of(report, "SEC-008") == "WARN",
          f"正文里的零宽字符 → WARN（实得 {status_of(report, 'SEC-008')}）")

    clean = make_skill(tmp / "steg-c", "steg-c", extra={
        "references/note.md": "普通正文，没有隐藏字符。\n"})
    report = lint_skill(clean)
    check(status_of(report, "SEC-008") == "PASS", "干净内容 → PASS")


# --------------------------------------------------------------------------- #
# A6 dry-run（SCRIPT-009）
# --------------------------------------------------------------------------- #
DRY_OK = """import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-runnable.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run:
        Path("written.txt").write_text("done", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""

DRY_BAD = """import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run that still writes.")
    parser.add_argument("--dry-run", action="store_true")
    parser.parse_args()
    Path("written.txt").write_text("oops", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""


def run_dry_run(tmp: Path) -> None:
    print("[test_dry_run]")
    good = make_skill(tmp / "dry-a", "dry-a", extra={"scripts/tool.py": DRY_OK})
    report = lint_skill(good, run_scripts=True)
    check(status_of(report, "SCRIPT-009") == "PASS",
          f"dry-run 真的只预览 → PASS（实得 {status_of(report, 'SCRIPT-009')}）")
    check(not (good / "written.txt").exists(),
          "试跑发生在临时副本里：原技能目录没有被改动")

    bad = make_skill(tmp / "dry-b", "dry-b", extra={"scripts/tool.py": DRY_BAD})
    report = lint_skill(bad, run_scripts=True)
    check(status_of(report, "SCRIPT-009") == "FAIL",
          f"dry-run 仍写文件 → FAIL（实得 {status_of(report, 'SCRIPT-009')}）")
    check("written.txt" in evidence_of(report, "SCRIPT-009"),
          "证据点出被改动的文件")
    check(not (bad / "written.txt").exists(),
          "同样没碰原目录（被改的是副本）")

    off = lint_skill(bad)
    check(status_of(off, "SCRIPT-009") == "SKIP", "未开 --scripts → SKIP（未执行）")
    no_script = make_skill(tmp / "dry-c", "dry-c")
    report = lint_skill(no_script)
    check(status_of(report, "SCRIPT-009") == "INFO",
          "没有 scripts/ → INFO（不适用，别让纯文档技能恒返回 2）")


# --------------------------------------------------------------------------- #
# A4 评委校准（REV-012）
# --------------------------------------------------------------------------- #
def _writeback(skill: str, *, calibration=None) -> str:
    data = {
        "schema": "skillverify.review/1",
        "skill": skill,
        "reviewer": "校准探针",
        "tier": "pack",
        "generated_at": "2026-10-05T10:00:00+08:00",
        "prompt_ids": ["W-01"],
        "results": [{"prompt_id": "W-01", "verdict": "PASS",
                     "evidence": "见 SKILL.md:2 的 description 字段", "finding": ""}],
    }
    if calibration is not None:
        data["calibration"] = calibration
    return json.dumps(data, ensure_ascii=False)


def run_calibration(tmp: Path) -> None:
    print("[test_judge_calibration]")
    from skillverify.review import check_calibration, load_calibration

    samples = load_calibration()
    check(len(samples) >= 4, f"校准样本已随包分发（{len(samples)} 个）")
    expected = {str(s["id"]): str(s["expected"]).upper() for s in samples}
    check(set(expected.values()) <= {"PASS", "FAIL"} and len(set(expected.values())) == 2,
          "样本同时含「应过」与「应挂」两类（否则校准没意义）")

    # 判错的评委 → FAIL
    wrong = [{ "sample_id": sid, "verdict": ("FAIL" if want == "PASS" else "PASS")}
             for sid, want in expected.items()]
    result = check_calibration({"calibration": wrong}, label="探针")
    check(result.status == "FAIL", f"判错校准样本 → FAIL（实得 {result.status}）")
    check("不可用" in result.evidence, "证据说清后果：本轮结论不可用")

    right = [{"sample_id": sid, "verdict": want} for sid, want in expected.items()]
    check(check_calibration({"calibration": right}).status == "PASS", "全部判对 → PASS")
    check(check_calibration({}).status == "INFO", "没做校准 → INFO（增强项，不阻断）")

    # 端到端：走 review collect 也会带上这条判定
    skill = make_skill(tmp / "cal-proj" / ".agents" / "skills", "cal-skill")
    home = tmp / "cal-home"
    home.mkdir(parents=True, exist_ok=True)
    wb = tmp / "cal-writeback.json"
    wb.write_text(_writeback("cal-skill", calibration=wrong), encoding="utf-8", newline="")
    code, out, _err = run_cli(["review", "collect", str(wb), "--skill-dir", str(skill),
                               "--project", str(skill.parents[2]), "--user-home", str(home),
                               "--json"])
    payload = json.loads(out)
    row = next((r for r in payload["results"] if r["rid"] == "REV-012"), None)
    check(code == 1 and row is not None and row["status"] == "FAIL",
          f"`review collect` 会让判错校准的回写不通过（exit={code}）")


# --------------------------------------------------------------------------- #
# A5 断言区分度（EVAL-010）
# --------------------------------------------------------------------------- #
def _grading(assertions: list[tuple[str, bool]]) -> str:
    return json.dumps({"assertion_results": [
        {"text": text, "passed": passed, "evidence": "见 outputs/out.md"}
        for text, passed in assertions],
        "summary": {"passed": sum(1 for _t, p in assertions if p),
                    "failed": sum(1 for _t, p in assertions if not p),
                    "total": len(assertions),
                    "pass_rate": (sum(1 for _t, p in assertions if p) / max(len(assertions), 1))}},
        ensure_ascii=False)


def run_discrimination(tmp: Path) -> None:
    print("[test_assertion_discrimination]")
    from skillverify import evalx

    skill = make_skill(tmp / "disc" / ".agents" / "skills", "disc-skill")
    (skill / "evals").mkdir(exist_ok=True)
    (skill / "evals" / "evals.json").write_text(json.dumps({
        "skill_name": "disc-skill",
        "evals": [{"id": 1, "prompt": "p", "expected_output": "o", "assertions": ["输出是好的"]}],
    }, ensure_ascii=False), encoding="utf-8", newline="")
    ws = skill.parent / "disc-skill-workspace"
    for index in (1, 2):
        for arm in ("with_skill", "without_skill"):
            d = ws / f"iteration-{index}" / "eval-1" / arm
            d.mkdir(parents=True, exist_ok=True)
            # 同一条断言四次全过 → 恒真；另一条有区分度
            (d / "grading.json").write_text(
                _grading([("输出是好的", True), ("输出列出 3 个月份", arm == "with_skill")]),
                encoding="utf-8", newline="")
            (d / "outputs").mkdir(exist_ok=True)
            (d / "outputs" / "out.md").write_text("x\n", encoding="utf-8", newline="")
            (d / "timing.json").write_text('{"total_tokens": 10, "duration_ms": 100}',
                                           encoding="utf-8", newline="")
    report = evalx.check_evals(skill)
    row = next((r for r in report.results if r.rid == "EVAL-010"), None)
    check(row is not None and row.status == "WARN",
          f"跨轮次恒真的断言 → WARN（实得 {row.status if row else '缺'}）")
    check(row is not None and "恒真" in row.evidence, "证据点名「恒真」")
    check(row is not None and "输出列出 3 个月份" not in row.evidence,
          "有区分度的断言不被误报")

    _doc, repo_ok = None, True
    single = make_skill(tmp / "disc2", "disc2")
    (single / "evals").mkdir(exist_ok=True)
    (single / "evals" / "evals.json").write_text(json.dumps({
        "skill_name": "disc2", "evals": [{"id": 1, "prompt": "p", "expected_output": "o",
                                           "assertions": ["x"]}]}, ensure_ascii=False),
        encoding="utf-8", newline="")
    report = evalx.check_evals(single)
    row = next(r for r in report.results if r.rid == "EVAL-010")
    check(row.status == "INFO" and "不适用" in row.evidence,
          f"没有足够观测 → INFO 并说明（实得 {row.status}）")


# --------------------------------------------------------------------------- #
# A3/A7/A8 交付侧
# --------------------------------------------------------------------------- #
def run_deliver_hardening(tmp: Path) -> None:
    print("[test_deliver_hardening]")
    proj = tmp / "dlv"
    skill = make_skill(proj / ".agents" / "skills", "dlv-skill")
    (skill / "references").mkdir(exist_ok=True)
    (skill / "references" / "guide.md").write_text("# 指南\n", encoding="utf-8", newline="")
    (skill / "SKILL.md").write_text(
        (skill / "SKILL.md").read_text(encoding="utf-8")
        + "\n引用不存在的文件：`references/missing.md`\n", encoding="utf-8", newline="")
    home = tmp / "dlv-home"
    home.mkdir(parents=True, exist_ok=True)
    common = ["--project", str(proj), "--user-home", str(home), "--stages", "both", "--json"]

    code, out, _err = run_cli(["deliver", *common])
    record = json.loads(out)
    check(code == 1 and record["gate"]["blockers"], "断链技能 → 门禁不通过（对照组）")
    blocker_rid = record["gate"]["blockers"][0].split("·")[1].strip()
    check(blocker_rid.startswith("REF-"), f"阻断项来自 REF-*（实得 {blocker_rid}）")

    check("environment" in record and record["environment"].get("python"),
          "A8：交付记录里含 environment（python/platform/工具版本/规则集指纹）")
    check("reviewers" in record, "A8：交付记录里含 reviewers（Judge 身份，来自评审记录）")
    # 光"键存在"骗过人：真缺陷是键名对不上导致值恒为 None（评审记录写复数键）。
    # 这里造一份真实形状的评审记录，要求值真的取到。
    from skillverify import deliver as _deliver
    trace_dir = Path(record["trace_dir"])
    (trace_dir / "review").mkdir(parents=True, exist_ok=True)
    (trace_dir / "review" / "dlv-skill.json").write_text(json.dumps({
        "schema": "skillverify.review/1", "skill": "dlv-skill",
        "reviewers": ["探针评委"], "tiers": ["pack"],
        "collected_at": "2026-10-05T12:00:00+08:00", "verdict": "PASS",
    }, ensure_ascii=False), encoding="utf-8", newline="")
    got = _deliver._reviewers(trace_dir, ["dlv-skill"]).get("dlv-skill", {})
    check(got.get("reviewer") and got.get("tier") and got.get("generated_at"),
          f"A8：Judge 三项真的取到值（不是 None）——实得 {got}")
    check("workspaces" in record, "A7：交付记录里含每个技能的工作区迭代指纹")

    # A3：不带理由 → 直接拒绝
    code, _out, err = run_cli(["deliver", *common, "--accept", blocker_rid])
    check(code == 1 and "because" in err, "A3：--accept 缺 --because 直接拒绝")
    # A3：带理由 → 记「已豁免」并通过
    code, out, err = run_cli(["deliver", *common, "--accept", blocker_rid,
                              "--because", "该引用是外部文档，随交付附上"])
    record = json.loads(out)
    check(code == 0, f"A3：豁免后门禁通过（实得 {code}）")
    check(record["gate"]["waivers"] and "豁免理由" in record["gate"]["waivers"][0],
          "A3：豁免写进了记录，且带理由")
    check("已豁免" in err, "A3：stderr 明确告知豁免了什么")

    # A7：改动同名 iteration 的内容 → 下一轮记录里报「历史被改动」
    ws = skill.parent / "dlv-skill-workspace" / "iteration-1"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "note.md").write_text("第一版\n", encoding="utf-8", newline="")
    run_cli(["deliver", *common])
    (ws / "note.md").write_text("被覆盖的第二版\n", encoding="utf-8", newline="")
    _code, out, err = run_cli(["deliver", *common])
    record = json.loads(out)
    rewritten = record["previous"].get("history_rewritten") or []
    check(any("iteration-1" in item for item in rewritten),
          f"A7：同名 iteration 内容变了 → 报「历史被改动」（实得 {rewritten}）")
    check("历史被改动" in err, "A7：stderr 也提示历史被改动")


def run_examples(tmp: Path) -> None:
    """P3b：执行器样例模板（examples/）——它们坏掉的话，使用者照着抄就是坏的。"""
    print("[test_executor_examples]")
    import subprocess as _sp

    repo = Path(__file__).resolve().parent.parent
    scripts = sorted((repo / "examples").glob("*.py"))
    check(len(scripts) == 3, f"examples/ 里有三个模板（实得 {[s.name for s in scripts]}）")
    for script in scripts:
        proc = _sp.run([sys.executable, str(script), "--help"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
        check(proc.returncode == 0 and "usage" in (proc.stdout or ""),
              f"{script.name} --help 可用（退出码 {proc.returncode}）")
        check("不做什么" in script.read_text(encoding="utf-8"),
              f"{script.name} 写明了「它不做什么」")

    skill = make_skill(tmp / "ex" / ".agents" / "skills", "ex-skill")
    (skill / "evals").mkdir(exist_ok=True)
    evals_json = skill / "evals" / "evals.json"
    evals_json.write_text(json.dumps({"skill_name": "ex-skill", "evals": []},
                                     ensure_ascii=False), encoding="utf-8", newline="")
    badcase = repo / "examples" / "badcase_to_evals.py"
    before = evals_json.read_text(encoding="utf-8")
    _sp.run([sys.executable, str(badcase), "--skill", str(skill), "--dry-run",
             "--prompt", "把这份表按月汇总", "--expected", "按月汇总的表",
             "--assertion", "输出含 month 与 total 两列"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
    check(evals_json.read_text(encoding="utf-8") == before, "--dry-run 不写盘（evals.json 未变）")

    proc = _sp.run([sys.executable, str(badcase), "--skill", str(skill),
                    "--prompt", "把这份表按月汇总", "--expected", "按月汇总的表",
                    "--assertion", "输出含 month 与 total 两列"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
    data = json.loads(evals_json.read_text(encoding="utf-8"))
    added = data.get("evals") or []
    check(proc.returncode == 0 and len(added) == 1 and added[0]["id"] == 1,
          f"回流脚本追加了一条用例（id={added[0]['id'] if added else None}）")
    check(bool(added) and added[0]["assertions"] == ["输出含 month 与 total 两列"],
          "断言原样写进用例（没有替使用者发明断言）")
    from skillverify import evalx as _evalx
    report = _evalx.check_evals(skill)
    check(not [r for r in report.results if r.status == "FAIL"],
          "追加后的 evals.json 能被工具解析（没有 FAIL）")

    (skill / "evals" / "trigger-queryset.json").write_text(json.dumps({
        "skill_name": "ex-skill",
        "queries": [{"id": "q1", "query": "把这个 csv 按月汇总", "should_trigger": True,
                     "subset": "train"}],
    }, ensure_ascii=False), encoding="utf-8", newline="")
    fake_cmd = '"' + sys.executable + '" -c "print(1)"'
    runs_path = skill / "evals" / "trigger-runs.json"
    # 用一个必定回答 yes 的假命令：python -c 打印 yes
    fake_cmd = '"' + sys.executable + '" -c "print(chr(121)+chr(101)+chr(115))"'
    proc = _sp.run([sys.executable, str(repo / "examples" / "run_triggers.py"),
                    "--skill", str(skill), "--cmd", fake_cmd, "--runs", "2"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
    check(proc.returncode == 0 and runs_path.is_file(),
          f"触发集执行器写出了运行记录（退出码 {proc.returncode}）")
    runs = (json.loads(runs_path.read_text(encoding="utf-8")).get("runs") or [])
    check(len(runs) == 2 and all(r.get("loaded") is True for r in runs),
          f"两条运行记录都记成「会触发」（实得 {[r.get('loaded') for r in runs]}）")


def run_run_inputs(tmp: Path) -> None:
    """WS-006：执行轮次自证——做不到隔离必须写出来，那一轮只能算参考级证据。"""
    print("[test_run_inputs]")
    from skillverify import evalx

    skill = make_skill(tmp / "ri" / ".agents" / "skills", "ri-skill")
    (skill / "evals").mkdir(exist_ok=True)
    (skill / "evals" / "evals.json").write_text(json.dumps({
        "skill_name": "ri-skill",
        "evals": [{"id": 1, "prompt": "p", "expected_output": "o", "assertions": ["x"]}],
    }, ensure_ascii=False), encoding="utf-8", newline="")
    ws = skill.parent / "ri-skill-workspace"

    def build(iteration: int, run_inputs: dict | None) -> None:
        for arm in ("with_skill", "without_skill"):
            d = ws / f"iteration-{iteration}" / "eval-1" / arm
            d.mkdir(parents=True, exist_ok=True)
            (d / "outputs").mkdir(exist_ok=True)
            (d / "outputs" / "out.md").write_text("x\n", encoding="utf-8", newline="")
        if run_inputs is not None:
            (ws / f"iteration-{iteration}" / "run-inputs.json").write_text(
                json.dumps(run_inputs, ensure_ascii=False), encoding="utf-8", newline="")

    build(1, None)
    row = next(r for r in evalx.check_evals(skill).results if r.rid == "WS-008")
    check(row.status == "INFO" and "执行自证" in row.evidence,
          f"完全没提供自证 → INFO（增强项，不阻断；实得 {row.status}）")

    build(1, {"isolation": "隔离", "executor": "claude -p --disallowedTools Skill",
              "input_hash": "sha256:aaa", "prompt_hashes": {"with_skill": "a",
                                                            "without_skill": "b"}})
    row = next(r for r in evalx.check_evals(skill).results if r.rid == "WS-008")
    check(row.status == "PASS", f"字段齐备且真隔离 → PASS（实得 {row.status}）")

    build(1, {"isolation": "降级", "executor": "同会话顺序执行", "input_hash": "sha256:aaa",
              "prompt_hashes": {"with_skill": "a", "without_skill": "b"}})
    row = next(r for r in evalx.check_evals(skill).results if r.rid == "WS-008")
    check(row.status == "WARN" and "参考级证据" in row.evidence,
          f"写明降级 → WARN 且点明「参考级证据」（实得 {row.status}）")

    build(1, {"isolation": "隔离", "executor": "x"})
    row = next(r for r in evalx.check_evals(skill).results if r.rid == "WS-008")
    check(row.status == "WARN" and "缺字段" in row.evidence,
          f"字段缺失 → WARN 并点名缺哪些（实得 {row.status}：{row.evidence[:60]}）")


def run_endpoint_boundary(tmp: Path) -> None:
    """③：端点声明的边界匹配（声明 example.com，用 api.example.com 不该误报）。"""
    print("[test_endpoint_boundary]")
    declared = make_skill(
        tmp / "ep" / ".agents" / "skills", "ep-skill",
        description="Fetch monthly reports from example.com when the user asks for them.",
        extra={"scripts/fetch.py": "import urllib.request\n"
                                   "urllib.request.urlopen('https://api.example.com/v1/reports')\n"})
    row = next(r for r in lint_skill(declared).results if r.rid == "SEC-007")
    check("api.example.com" not in (row.evidence or ""),
          f"声明了 example.com，子域 api.example.com 不误报（实得 {row.status}："
          f"{(row.evidence or '')[:70]}）")

    undeclared = make_skill(
        tmp / "ep2" / ".agents" / "skills", "ep2-skill",
        extra={"scripts/fetch.py": "import urllib.request\n"
                                   "urllib.request.urlopen('https://evil.example.net/x')\n"})
    row = next(r for r in lint_skill(undeclared).results if r.rid == "SEC-007")
    # SEC-007 对"未声明的外部端点"是 WARN（仅作提示：声明≠可信），不是 FAIL
    check(row.status in ("WARN", "FAIL") and "evil.example.net" in (row.evidence or ""),
          f"未声明的主机仍然被抓（实得 {row.status}：{(row.evidence or '')[:70]}）")


def run_destructive_scope(tmp: Path) -> None:
    """④：破坏性操作不只在 scripts/ 里找——assets/ 下的代码文件一样要看。"""
    print("[test_destructive_scope]")
    skill = make_skill(tmp / "ds" / ".agents" / "skills", "ds-skill", extra={
        "assets/deploy.sh": "#!/bin/sh\nrm -rf build/ dist/\n"})
    row = next(r for r in lint_skill(skill).results if r.rid == "SCRIPT-005")
    check(row.status in ("FAIL", "WARN") and "assets/deploy.sh" in (row.evidence or ""),
          f"assets/deploy.sh 里的 rm -rf 被看见（实得 {row.status}：{(row.evidence or '')[:70]}）")

    guarded = make_skill(tmp / "ds2" / ".agents" / "skills", "ds2-skill", extra={
        "assets/deploy.sh": "#!/bin/sh\ncase \"$1\" in --dry-run) exit 0;; esac\nrm -rf build/\n"})
    row = next(r for r in lint_skill(guarded).results if r.rid == "SCRIPT-005")
    check(row.status == "PASS" or "assets/deploy.sh" not in (row.evidence or ""),
          f"带 --dry-run 防护的不再算「未防护」（实得 {row.status}）")


def main() -> int:
    force_utf8_stdio()
    argparse.ArgumentParser(description="A 组加固项的回归断言").parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="sv_test_hardening_"))
    try:
        run_license(tmp)
        run_steganography(tmp)
        run_dry_run(tmp)
        run_calibration(tmp)
        run_discrimination(tmp)
        run_deliver_hardening(tmp)
        run_examples(tmp)
        run_run_inputs(tmp)
        run_endpoint_boundary(tmp)
        run_destructive_scope(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    total = len(_passed) + len(_failed)
    print(f"\n结果: PASS={len(_passed)} FAIL={len(_failed)} 合计={total}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
