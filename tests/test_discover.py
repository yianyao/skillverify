"""discover / check 回归测试（M2）。

**本文件的头号用例是"接入新宿主，0 行代码改动"**：造一个代码里从未出现过的宿主
布局，只在 hosts.toml 里加一段声明，然后走完整 CLI 路径把它跑通。旧体系
`tools/host_compat.py` 有 71 处宿主硬编码，因此这里额外加了一条不变量测试——
`skillverify/**/*.py` 里**不得出现任何宿主名**（宿主名只允许出现在数据文件里）。

用法：
    python -m tests.test_discover
    python -m tests.test_discover --dogfood   # 额外对 legacy/ 跑一遍整库 check
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
from skillverify.discover import (  # noqa: E402
    DEFAULT_PROFILE,
    ConfigError,
    discover_skills,
    load_config,
    render_config,
)
from skillverify.encoding import force_utf8_stdio  # noqa: E402
from skillverify.report import FAIL, PASS, SKIP, WARN, LibraryReport, Report, Result  # noqa: E402

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


DESC = "A demo skill used by the discovery regression suite."


def write_skill(root: Path, name: str, *, body: str = "# Demo\n") -> Path:
    target = root / name
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {DESC}\n---\n\n{body}",
        encoding="utf-8", newline="",
    )
    return target


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    """跑完整 CLI，返回 (退出码, stdout, stderr)。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


# --------------------------------------------------------------------------- #
# 配置层
# --------------------------------------------------------------------------- #


def run_config(tmp: Path) -> None:
    print("[test_config]")
    project = tmp / "cfg" / "proj"
    home = tmp / "cfg" / "home"
    project.mkdir(parents=True)
    home.mkdir(parents=True)

    base = load_config(project, home, use_discovered_files=False)
    check(DEFAULT_PROFILE in base.hosts and base.defaults.project_roots == [".agents/skills"],
          "内置配置可加载，默认档为官方跨宿主约定 .agents/skills")
    check("官方跨宿主约定" in render_config(base),
          "--show-config 渲染含档说明")

    # 覆盖顺序：用户级 < 项目级 < --config
    (home / ".agents" / "skillverify").mkdir(parents=True)
    (home / ".agents" / "skillverify" / "hosts.toml").write_text(
        '[defaults]\nproject_roots = ["from-user"]\n', encoding="utf-8", newline="")
    (project / ".agents" / "skillverify").mkdir(parents=True)
    (project / ".agents" / "skillverify" / "hosts.toml").write_text(
        '[defaults]\nproject_roots = ["from-project"]\n', encoding="utf-8", newline="")
    extra = tmp / "cfg" / "extra.toml"
    extra.write_text('[defaults]\nproject_roots = ["from-flag"]\ntrace_dir = "trace-here"\n',
                     encoding="utf-8", newline="")

    cfg = load_config(project, home, [extra])
    check(cfg.defaults.project_roots == ["from-flag"],
          f"覆盖顺序 用户<项目<--config（实得 {cfg.defaults.project_roots}）")
    check(cfg.defaults.trace_dir == "trace-here", "标量同样被 --config 覆盖")
    check(len(cfg.sources) == 4, f"来源记录完整（实得 {len(cfg.sources)} 个）")

    cfg_nodisc = load_config(project, home, [extra], use_discovered_files=False)
    check(cfg_nodisc.defaults.project_roots == ["from-flag"] and len(cfg_nodisc.sources) == 2,
          "--no-config 只用内置 + --config")

    # 列表整体替换而不是拼接（否则"只想查这两个根"表达不出来）
    merged = load_config(project, home, use_discovered_files=False, builtin=extra)
    check(merged.defaults.project_roots == ["from-flag"], "列表为整体替换，不做拼接")

    # 未知键必须报错（拼错键名静默发现 0 个技能是最坏的失败模式）
    bad = tmp / "cfg" / "bad-key.toml"
    bad.write_text('[hosts.x]\nproject_root = ["typo"]\n', encoding="utf-8", newline="")
    try:
        load_config(project, home, [bad], use_discovered_files=False)
        fail("未知键未报错")
    except ConfigError as exc:
        check("project_root" in str(exc) and "project_roots" in str(exc),
              "未知键报错并列出允许的键名")

    bad_type = tmp / "cfg" / "bad-type.toml"
    bad_type.write_text('[defaults]\nmax_depth = "2"\n', encoding="utf-8", newline="")
    try:
        load_config(project, home, [bad_type], use_discovered_files=False)
        fail("max_depth 类型错误未报错")
    except ConfigError as exc:
        check("max_depth" in str(exc), "max_depth 类型错误报错")

    bad_toml = tmp / "cfg" / "bad.toml"
    bad_toml.write_text("[defaults\nproject_roots = 1\n", encoding="utf-8", newline="")
    try:
        load_config(project, home, [bad_toml], use_discovered_files=False)
        fail("TOML 语法错误未报错")
    except ConfigError as exc:
        check("bad.toml" in str(exc), "TOML 语法错误报错并指名文件")

    missing = tmp / "cfg" / "nope.toml"
    try:
        load_config(project, home, [missing], use_discovered_files=False)
        fail("缺失配置文件未报错")
    except ConfigError as exc:
        check("不存在" in str(exc), "缺失配置文件报错")

    try:
        cfg.profile("does-not-exist")
        fail("未知宿主档未报错")
    except ConfigError as exc:
        check("可用" in str(exc), "未知宿主档报错并列出可用档名")


# --------------------------------------------------------------------------- #
# 发现
# --------------------------------------------------------------------------- #


def run_discovery(tmp: Path) -> None:
    print("[test_discovery]")
    project = tmp / "disc" / "proj"
    home = tmp / "disc" / "home"
    (project / ".agents" / "skills").mkdir(parents=True)
    (home / ".agents" / "skills").mkdir(parents=True)
    write_skill(project / ".agents" / "skills", "proj-skill")
    write_skill(home / ".agents" / "skills", "user-skill")

    profile = load_config(project, home, use_discovered_files=False).profile(None)
    disc = discover_skills(profile, project, home)
    got = {(s.name, s.scope) for s in disc.skills}
    check(got == {("proj-skill", "project"), ("user-skill", "user")},
          f"项目级与用户级技能均被发现（实得 {sorted(got)}）")
    check(str(disc.trace_dir).endswith(str(Path(".agents") / "skillverify")),
          "留痕目录解析为 <project>/.agents/skillverify")

    # 不存在的用户级根：跳过，不报错
    empty_home = tmp / "disc" / "empty-home"
    empty_home.mkdir(parents=True)
    disc2 = discover_skills(profile, project, empty_home)
    check([s.name for s in disc2.skills] == ["proj-skill"] and not disc2.results,
          "缺失的用户级根被跳过且不产生告警")

    # 显式 --root 不存在 → DISC-002
    disc3 = discover_skills(profile, project, home, roots=["no-such-root"])
    check(any(r.rid == "DISC-002" and r.status == WARN for r in disc3.results),
          "显式 --root 不存在 → DISC-002 WARN")

    # 空库 → DISC-003
    empty_proj = tmp / "disc" / "empty-proj"
    (empty_proj / "skills").mkdir(parents=True)
    disc4 = discover_skills(profile, empty_proj, home, roots=["skills"])
    check(any(r.rid == "DISC-003" for r in disc4.results) and not disc4.skills,
          "空技能根 → DISC-003")

    # 同名技能出现在两处 → DISC-001（不静默覆盖）
    write_skill(project / ".agents" / "skills", "proj-skill", body="# Demo 2\n")
    alt = project / "alt-skills"
    write_skill(alt, "proj-skill")
    disc5 = discover_skills(profile, project, home, roots=[".agents/skills", "alt-skills"])
    hits = [r for r in disc5.results if r.rid == "DISC-001"]
    check(len(hits) == 1 and len(disc5.skills) == 2,
          f"同名技能两处并存 → DISC-001 且两个都保留（实得 {len(disc5.skills)} 个技能）")
    check(len(hits) == 1 and "2 处" in hits[0].evidence,
          "DISC-001 证据里说清了两处位置")

    # 同一目录经两个根到达 → 去重，不算歧义
    disc6 = discover_skills(profile, project, home, roots=["alt-skills", "./alt-skills"])
    check(len(disc6.skills) == 1 and not [r for r in disc6.results if r.rid == "DISC-001"],
          "同一目录经不同路径写法到达 → 去重且不误报歧义")

    # max_depth=1 不下钻；=2 下钻
    nested = tmp / "disc" / "nested"
    write_skill(nested / "skills" / "category", "deep-skill")
    shallow = load_config(project, home, use_discovered_files=False)
    p1 = shallow.profile(None)
    check(not discover_skills(p1, nested, home, roots=["skills"]).skills,
          "max_depth=1 不发现 skills/<分类>/<技能>")
    deep_cfg = tmp / "disc" / "deep.toml"
    deep_cfg.write_text("[hosts.deep]\nproject_roots = [\"skills\"]\nmax_depth = 2\n",
                        encoding="utf-8", newline="")
    cfg2 = load_config(project, home, [deep_cfg], use_discovered_files=False)
    found = discover_skills(cfg2.profile("deep"), nested, home)
    check("deep-skill" in [s.name for s in found.skills],
          f"max_depth=2 发现按分类分组的技能（实得 {[s.name for s in found.skills]}）")

    # SKIP_DIRS 不下钻（node_modules 里的技能不算）
    skip = tmp / "disc" / "skip"
    write_skill(skip / "skills" / "node_modules", "vendored")
    write_skill(skip / "skills", "real")
    got2 = [s.name for s in discover_skills(p1, skip, home, roots=["skills"]).skills]
    check(got2 == ["real"], f"node_modules 不被下钻（实得 {got2}）")

    # 绝对路径写法（配置里直接给绝对路径）
    abs_cfg = tmp / "disc" / "abs.toml"
    abs_cfg.write_text(
        f'[hosts.abs]\nproject_roots = ["{alt.as_posix()}"]\n', encoding="utf-8", newline="")
    cfg3 = load_config(project, home, [abs_cfg], use_discovered_files=False)
    abs_names = [s.name for s in discover_skills(cfg3.profile("abs"), project, home).skills]
    check("proj-skill" in abs_names,
          f"配置里的绝对路径被原样使用（实得 {abs_names}）")

    # ~ 的指向由 --user-home 决定
    home2 = tmp / "disc" / "home2"
    (home2 / ".agents" / "skills").mkdir(parents=True)
    write_skill(home2 / ".agents" / "skills", "other-home-skill")
    got3 = [s.name for s in discover_skills(profile, project, home2).skills]
    check("other-home-skill" in got3, "~ 的指向由传入的 user_home 决定")


# --------------------------------------------------------------------------- #
# 核心验收：接入新宿主，0 行代码改动
# --------------------------------------------------------------------------- #

#: 一个代码里从未出现过的宿主名与布局
NEW_HOST = "brand-new-host-xyz"
NEW_LAYOUT = f".{NEW_HOST}/agent-skills"


def run_new_host_zero_code_change(tmp: Path) -> None:
    print("[test_new_host_zero_code_change]")
    project = tmp / "newhost" / "proj"
    home = tmp / "newhost" / "home"
    home.mkdir(parents=True)
    write_skill(project / NEW_LAYOUT, "fresh-skill")

    # ① 用内置配置（不认识这个宿主）→ 发现不到
    code, out, _err = run_cli([
        "discover", "--project", str(project), "--user-home", str(home), "--json",
    ])
    before = json.loads(out)
    check(before["skills"] == [], "内置配置不认识新宿主布局（发现 0 个技能）")

    # ② 只加一段声明，不改任何代码
    cfg = tmp / "newhost" / "hosts.toml"
    cfg.write_text(
        f'[hosts.{NEW_HOST}]\n'
        f'description = "临时接入的宿主"\n'
        f'project_roots = ["{NEW_LAYOUT}", ".agents/skills"]\n'
        f'user_roots = []\n'
        f'max_depth = 1\n',
        encoding="utf-8", newline="",
    )
    code, out, err = run_cli([
        "check", "--project", str(project), "--user-home", str(home),
        "--config", str(cfg), "--host", NEW_HOST, "--json",
    ])
    result = json.loads(out)
    names = [s["skill"] for s in result["skills"]]
    check(names == ["fresh-skill"], f"仅加 TOML 声明即可发现新宿主技能（实得 {names}）")
    check(code == 0 and result["verdict"] == "PASS",
          f"新宿主技能检查通过（exit={code}, verdict={result['verdict']}）")
    check(not err.strip() or "提示" in err, "无错误输出（退出码不需要额外解释）")

    # ③ discover 也能列出（同一套声明）
    code2, out2, _ = run_cli([
        "discover", "--project", str(project), "--user-home", str(home),
        "--config", str(cfg), "--host", NEW_HOST, "--json",
    ])
    check([s["name"] for s in json.loads(out2)["skills"]] == ["fresh-skill"],
          "discover 用同一份声明列出新宿主技能")

    # ④ 不变量：代码里不得出现任何宿主名（宿主名只允许出现在数据文件里）
    pkg = Path(__file__).resolve().parent.parent / "skillverify"
    sources = {p: p.read_text(encoding="utf-8") for p in pkg.rglob("*.py")}
    offenders = [
        f"{p.name}:{name}"
        for p, text in sources.items()
        for name in (NEW_HOST, "workbuddy", "codebuddy", "claude", "cursor")
        if name in text.lower()
    ]
    check(not offenders, f"skillverify/**/*.py 内无宿主名硬编码（实得 {offenders}）")

    # ⑤ 内置配置里的宿主名只在数据文件中，且被 --show-config 如实呈现
    data = (pkg / "data" / "hosts.toml").read_text(encoding="utf-8")
    check("workbuddy" in data and "workbuddy" not in "".join(sources.values()).lower(),
          "宿主名只存在于 data/hosts.toml，不出现在代码里")


# --------------------------------------------------------------------------- #
# check 命令
# --------------------------------------------------------------------------- #


def run_check_command(tmp: Path) -> None:
    print("[test_check_command]")
    project = tmp / "chk" / "proj"
    home = tmp / "chk" / "home"
    home.mkdir(parents=True)
    write_skill(project / ".agents" / "skills", "good-skill")

    code, out, _err = run_cli([
        "check", "--project", str(project), "--user-home", str(home), "--stages", "spec",
    ])
    check(code == 0 and "总结论: **PASS**" in out, f"干净库 check 通过（exit={code}）")

    # 坏技能 → FAIL
    bad = write_skill(project / ".agents" / "skills", "bad-skill")
    (bad / "SKILL.md").write_text(
        "---\nname: Bad-Skill\ndescription: x\n---\n\n# X\n", encoding="utf-8", newline="")
    code, out, err = run_cli([
        "check", "--project", str(project), "--user-home", str(home), "--stages", "spec",
    ])
    check(code == 1 and "bad-skill" in out, f"含坏技能时 exit=1（实得 {code}）")
    check("FAIL bad-skill" in err, "FAIL 明细同步到 stderr")

    # lint 阶段可单跑
    code, out, _ = run_cli([
        "check", "--project", str(project), "--user-home", str(home), "--stages", "lint",
        "--json",
    ])
    payload = json.loads(out)
    rids = {r["rid"] for skill in payload["skills"] for r in skill["results"]}
    check(not any(rid.startswith("SKILL-") for rid in rids), "--stages lint 不含 spec 规则")
    check(any(rid.startswith("HYG-") for rid in rids), "--stages lint 含 lint 规则")

    # 空库：什么都没检查 ≠ 通过
    empty = tmp / "chk" / "empty"
    write_skill(empty / "somewhere-else", "not-discovered")
    code, _out, err = run_cli([
        "check", "--project", str(empty), "--user-home", str(home), "--quiet",
    ])
    check(code == 1 and "未发现任何技能" in err,
          f"未发现技能时 exit=1 并说明原因（实得 {code}）")

    # --trace 写入配置的留痕目录（md + json）
    trace_project = tmp / "chk" / "trace"
    write_skill(trace_project / ".agents" / "skills", "good-skill")
    code, _out, err = run_cli([
        "check", "--project", str(trace_project), "--user-home", str(home), "--trace",
        "--stages", "spec",
    ])
    trace_dir = trace_project / ".agents" / "skillverify"
    check((trace_dir / "check.md").is_file() and (trace_dir / "check.json").is_file(),
          f"`--trace` 在 trace_dir 落盘 check.md + check.json（{err.strip()[:60]}）")
    payload = json.loads((trace_dir / "check.json").read_text(encoding="utf-8"))
    check(payload["counts"]["PASS"] > 0, "落盘的 JSON 含完整结果")

    # --quiet 时汇总走 stderr
    code, out, err = run_cli([
        "check", "--project", str(trace_project), "--user-home", str(home),
        "--stages", "spec", "--quiet",
    ])
    check(out.strip() == "" and "汇总" in err, "--quiet 时正文不打印、汇总走 stderr")

    # 只有 WARN 时 exit=2
    warn_project = tmp / "chk" / "warn"
    write_skill(warn_project / ".agents" / "skills", "warn-skill")
    (warn_project / ".agents" / "skills" / "warn-skill" / "docs").mkdir(parents=True)
    (warn_project / ".agents" / "skills" / "warn-skill" / "docs" / "n.md").write_text(
        "# n\n", encoding="utf-8", newline="")
    code, _out, _err = run_cli([
        "check", "--project", str(warn_project), "--user-home", str(home), "--stages", "lint",
    ])
    check(code == 2, f"仅有 WARN 时 exit=2（实得 {code}）")

    # 四个子命令都必须支持 --out（`_add_common` 是共用的，别只给新命令加）
    for argv, name in (
        (["spec", str(trace_project / ".agents" / "skills" / "good-skill")], "spec"),
        (["lint", str(trace_project / ".agents" / "skills" / "good-skill")], "lint"),
        (["discover", "--project", str(trace_project), "--user-home", str(home)], "discover"),
        (["check", "--project", str(trace_project), "--user-home", str(home),
          "--stages", "spec"], "check"),
    ):
        out_file = tmp / "chk" / f"out-{name}.md"
        code, _out, _err = run_cli([*argv, "--out", str(out_file), "--quiet"])
        check(out_file.is_file() and out_file.stat().st_size > 0,
              f"`{name} --out` 落盘成功（exit={code}）")


# --------------------------------------------------------------------------- #
# LibraryReport
# --------------------------------------------------------------------------- #


def run_library_report(tmp: Path) -> None:
    print("[test_library_report]")
    good = Report(target="a", stage="check")
    good.add(Result("X-001", "t", PASS, "HOUSE", ""))
    bad = Report(target="b", stage="check")
    bad.add(Result("X-002", "t", FAIL, "HOUSE", "坏了", "修"))
    bad.add(Result("X-003", "t", SKIP, "HOUSE", "未执行", ""))

    lib = LibraryReport(stage="check", target="lib")
    lib.add(Result("DISC-001", "同名", WARN, "HOUSE", "两处", "删一处"))
    from skillverify.report import LibraryEntry
    lib.add_entry(LibraryEntry("a", "project", "/a", good))
    lib.add_entry(LibraryEntry("b", "project", "/b", bad))

    counts = lib.counts()
    check(counts[PASS] == 1 and counts[FAIL] == 1 and counts[SKIP] == 1 and counts[WARN] == 1,
          f"库级计数汇总技能结果 + 库级结果（实得 {counts}）")
    check(lib.exit_code() == 1, "有 FAIL 时库级 exit=1（优先于 WARN/SKIP）")
    md = lib.to_markdown()
    check("## 技能清单" in md and "| b |" in md and "X-002" in md,
          "汇总 markdown 含技能清单与需关注判定")
    check("DISC-001" in md, "库级结果出现在汇总里")
    payload = json.loads(lib.to_json())
    check(payload["skill_verdicts"]["FAIL"] == 1 and len(payload["skills"]) == 2,
          "库级 JSON 含逐技能判定与技能数")

    lib2 = LibraryReport(stage="check", target="lib")
    lib2.add_entry(LibraryEntry("a", "project", "/a", good))
    check(lib2.exit_code() == 0 and "无：" in lib2.to_markdown(),
          "全 PASS 时 exit=0 且明确写出「无」需关注项")


# --------------------------------------------------------------------------- #
# dogfood
# --------------------------------------------------------------------------- #


def run_dogfood(repo: Path) -> None:
    print("[test_dogfood]")
    legacy = repo / "legacy"
    if not legacy.is_dir():
        ok("无 legacy/ 目录，跳过")
        return
    with tempfile.TemporaryDirectory(prefix="sv_disc_home_") as home:
        code, out, _err = run_cli([
            "check", "--project", str(repo), "--user-home", home,
            "--root", str(legacy), "--scripts", "--json",
        ])
    payload = json.loads(out)
    for skill in payload["skills"]:
        counts = skill["counts"]
        print(f"  · {skill['skill']}: {skill['verdict']} "
              f"PASS={counts['PASS']} WARN={counts['WARN']} FAIL={counts['FAIL']}")
    check(len(payload["skills"]) == 4 and code in (0, 1, 2),
          f"legacy/ 整库 check 完成（{len(payload['skills'])} 个技能，exit={code}）")
    check(payload["counts"]["FAIL"] >= 2,
          "旧技能的宿主绝对路径仍被抓出（REF-003，属预期真阳性）")


# --------------------------------------------------------------------------- #


def main() -> int:
    force_utf8_stdio()
    parser = argparse.ArgumentParser(description="skillverify discover/check 回归测试")
    parser.add_argument("--dogfood", action="store_true",
                        help="额外对 legacy/ 跑一遍整库 check 并打印摘要")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="sv_test_discover_"))
    try:
        run_config(tmp)
        run_discovery(tmp)
        run_new_host_zero_code_change(tmp)
        run_check_command(tmp)
        run_library_report(tmp)
        if args.dogfood:
            run_dogfood(Path(__file__).resolve().parent.parent)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = len(_passed) + len(_failed)
    print(f"\n结果: PASS={len(_passed)} FAIL={len(_failed)} 合计={total}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
