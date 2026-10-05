"""watch / deliver / git hook 回归测试（M3）。

**本文件的头号用例是"hook 真的能拦住提交"**：不是断言"我们生成了正确的 hook 文本"，
而是在临时 git 仓库里装好 hook、`git add` 一个坏技能、真的跑 `git commit`，
断言提交被拒且仓库历史里没有这次提交；修好后再提交，断言放行。
（实测：本机 `sh` 不在 PATH，但 git 用自带 sh 执行 hook，因此端到端可跑。）

用法：
    python -m tests.test_automation
    python -m tests.test_automation --dogfood   # 可选：本地语料（默认 legacy/） 跑一次 deliver
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

from skillverify import cli, deliver, watch  # noqa: E402
from skillverify.discover import discover_skills, load_config  # noqa: E402
from skillverify.encoding import force_utf8_stdio  # noqa: E402
from skillverify.report import FAIL, PASS, SKIP, WARN, LibraryEntry, LibraryReport, Report, Result  # noqa: E402

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


DESC = "A demo skill used by the automation regression suite."


def write_skill(root: Path, name: str, *, body: str = "# Demo\n\nRead `references/guide.md`.\n",
                with_guide: bool = True) -> Path:
    target = root / name
    (target / "references").mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {DESC}\n---\n\n{body}",
        encoding="utf-8", newline="",
    )
    if with_guide:
        (target / "references" / "guide.md").write_text("# Guide\n", encoding="utf-8", newline="")
    return target


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    """跑完整 CLI 并捕获两条流。

    异常时**先把已捕获的输出打到真实 stderr 再抛出**——否则 `redirect_*` 会把
    回溯也吞进 StringIO，表现为"测试静默中断、没有任何线索"（本文件真踩过这个坑）。
    """
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
    except BaseException:
        sys.stderr.write(f"[run_cli] argv={argv} 抛出异常，已捕获的输出如下：\n"
                         f"--- stdout ---\n{out.getvalue()}\n--- stderr ---\n{err.getvalue()}\n")
        raise
    return code, out.getvalue(), err.getvalue()


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def make_repo(root: Path, name: str = "repo") -> Path:
    repo = root / name
    (repo / ".agents" / "skills").mkdir(parents=True)
    git(repo, "init", "-q")
    return repo


# --------------------------------------------------------------------------- #
# watch 纯函数部分
# --------------------------------------------------------------------------- #


def run_watch_helpers(tmp: Path) -> None:
    print("[test_watch_helpers]")
    root = tmp / "wh" / ".agents" / "skills"
    a = write_skill(root, "alpha")
    b = write_skill(root, "beta")
    refs = [
        type("R", (), {"name": "alpha", "path": a})(),
        type("R", (), {"name": "beta", "path": b})(),
    ]
    snap = watch.snapshot(refs)
    check(set(snap) == {"alpha", "beta"}, "快照覆盖全部技能")

    changes = watch.diff_snapshots(snap, snap)
    check(changes.empty and changes.describe() == "无变化", "无改动 → 空变更集")

    (a / "SKILL.md").write_text("---\nname: alpha\ndescription: " + DESC + "\n---\n\n# A2\n",
                                encoding="utf-8", newline="")
    snap2 = watch.snapshot(refs)
    changes2 = watch.diff_snapshots(snap, snap2)
    check(changes2.changed == ["alpha"] and changes2.targets() == ["alpha"],
          f"内容改动被指纹捕获（实得 changed={changes2.changed}）")

    (root / "gamma").mkdir(parents=True)
    (root / "gamma" / "SKILL.md").write_text(
        f"---\nname: gamma\ndescription: {DESC}\n---\n\n# G\n", encoding="utf-8", newline="")
    refs3 = refs + [type("R", (), {"name": "gamma", "path": root / "gamma"})()]
    changes3 = watch.diff_snapshots(snap2, watch.snapshot(refs3))
    check(changes3.added == ["gamma"], "新增技能被检出")

    changes4 = watch.diff_snapshots(watch.snapshot(refs3), snap2)
    check(changes4.removed == ["gamma"] and changes4.targets() == [],
          "移除的技能只报告、不进复跑目标")

    # 指纹只看 stat，不读内容：改 mtime 即视为变化（watch 的取舍，必须明说）
    import os
    os.utime(a / "references" / "guide.md", (0, 0))
    check(watch.diff_snapshots(snap2, watch.snapshot(refs)).changed == ["alpha"],
          "仅 mtime 变化也触发复跑（指纹不读内容，宁可多跑）")


# --------------------------------------------------------------------------- #
# watch 循环
# --------------------------------------------------------------------------- #


def run_watch_loop(tmp: Path) -> None:
    print("[test_watch_loop]")
    repo = tmp / "wl"
    skill = write_skill(repo / ".agents" / "skills", "demo-skill")
    profile = load_config(repo, tmp / "wl-home", use_discovered_files=False).profile(None)

    output = io.StringIO()
    state = {"mutated": False}

    def on_cycle(index: int, changes) -> None:
        if index == 1 and not state["mutated"]:
            # 第 1 轮之后把引用改成断链
            (skill / "SKILL.md").write_text(
                f"---\nname: demo-skill\ndescription: {DESC}\n---\n\n"
                "# Demo\n\nSee `references/missing.md`.\n",
                encoding="utf-8", newline="",
            )
            state["mutated"] = True

    code = watch.run_watch(
        repo, tmp / "wl-home", profile, stages="lint", interval=0.01, cycles=3,
        stream=output, on_cycle=on_cycle,
    )
    text = output.getvalue()
    check("首轮全量（1 个技能）" in text, "首轮输出标明全量")
    check("变更 1: demo-skill" in text, "第 2 轮检出错链改动并只复跑该技能")
    check("REF-001" in text and "FAIL" in text, "改动后立即报出 REF-001 FAIL")
    check("本轮复跑 1 个技能" in text, "增量复跑（不是整库重跑）")
    check("第 3 轮 · 无变化" in text, "第 3 轮无改动则不重跑")
    check(code == 1, f"退出码反映最后一轮结果（实得 {code}）")

    # JSON 模式：每轮一行
    output2 = io.StringIO()
    watch.run_watch(repo, tmp / "wl-home", profile, stages="lint", interval=0.01,
                    cycles=1, stream=output2, as_json=True)
    lines = [ln for ln in output2.getvalue().splitlines() if ln.strip()]
    payload = json.loads(lines[0])
    check(len(lines) == 1 and payload["first"] is True and payload["skills"][0]["verdict"] == FAIL,
          "--json 每轮输出一行且含判定")

    # 未发现技能时不报错
    empty = tmp / "wl-empty"
    empty.mkdir(parents=True, exist_ok=True)
    output3 = io.StringIO()
    code3 = watch.run_watch(empty, tmp / "wl-home", profile, stages="lint",
                            interval=0.01, cycles=1, stream=output3)
    check(code3 == 0 and "首轮全量（0 个技能）" in output3.getvalue(),
          "空库时 watch 不报错")

    # 单轮异常不致命（把检查函数换成必然抛异常的实现）
    original = watch._check_skills
    watch._check_skills = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("注入的故障"))
    try:
        output4 = io.StringIO()
        code4 = watch.run_watch(repo, tmp / "wl-home", profile, stages="lint",
                                interval=0.01, cycles=2, stream=output4)
        text4 = output4.getvalue()
        check("检查异常" in text4 and text4.count("第 1 轮") + text4.count("第 2 轮") == 2,
              "单轮异常被打印且不终止监听")
        check(code4 == 1, "异常轮次体现在退出码上")
    finally:
        watch._check_skills = original


# --------------------------------------------------------------------------- #
# deliver 门禁
# --------------------------------------------------------------------------- #


def _library(*results: tuple[str, str, bool]) -> LibraryReport:
    """(rid, status, optional) -> 单技能库报告。"""
    report = Report(target="x", stage="deliver")
    for rid, status, optional in results:
        report.add(Result(rid, rid, status, "HOUSE", f"{rid} 证据", "", optional=optional))
    lib = LibraryReport(stage="deliver", target="t")
    lib.add_entry(LibraryEntry("demo", "project", "/demo", report))
    return lib


def run_gate(tmp: Path) -> None:
    print("[test_gate]")
    check(deliver.evaluate(_library(("A-1", PASS, False))).passed, "全 PASS → 门禁通过")

    gate = deliver.evaluate(_library(("A-1", FAIL, False), ("A-2", WARN, False)))
    check(not gate.passed and len(gate.blockers) == 1 and len(gate.warnings) == 1,
          "FAIL 阻断、WARN 只记账不阻断")

    gate = deliver.evaluate(_library(("A-1", SKIP, True)))
    check(gate.passed and len(gate.uncovered) == 1 and not gate.blockers,
          "可选项未覆盖 → 默认放行但列入未覆盖项")

    gate = deliver.evaluate(_library(("A-1", SKIP, True)), strict=True)
    check(not gate.passed and gate.blockers and "strict" in gate.blockers[0],
          "--strict 下未覆盖项也阻断")

    gate = deliver.evaluate(_library(("A-1", SKIP, False)))
    check(not gate.passed, "非可选项的 SKIP（本项确实未执行）阻断交付")

    lib = _library(("A-1", PASS, False))
    lib.add(Result("DISC-001", "同名", WARN, "HOUSE", "两处", ""))
    check(deliver.evaluate(lib).passed and len(deliver.evaluate(lib).warnings) == 1,
          "库级 WARN 计入待甄别且不阻断")
    lib2 = _library(("A-1", PASS, False))
    lib2.add(Result("DISC-002", "根不可用", SKIP, "HOUSE", "缺", ""))
    check(not deliver.evaluate(lib2).passed, "库级 SKIP 阻断")

    summary = deliver.evaluate(_library(("A-1", WARN, False))).summary()
    check("未通过" not in summary and "待书面甄别 1" in summary, "摘要文字如实反映计数")
    check(deliver.rules_hash().startswith("sha256:"), "规则集指纹可计算")


def run_deliver_command(tmp: Path) -> None:
    print("[test_deliver_command]")
    repo = make_repo(tmp / "dl")
    home = tmp / "dl-home"
    home.mkdir(parents=True, exist_ok=True)
    write_skill(repo / ".agents" / "skills", "good-skill")

    code, _out, err = run_cli([
        "deliver", "--project", str(repo), "--user-home", str(home),
        "--stages", "spec", "--quiet",
    ])
    check(code == 0 and "交付门禁通过" in err, f"干净库交付通过（exit={code}）")
    record_path = repo / ".agents" / "skillverify" / "deliver" / "latest.json"
    check(record_path.is_file(), "交付记录已落盘")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    check(record["schema"] == deliver.RECORD_SCHEMA and record["gate"]["result"] == "pass",
          "交付记录含 schema 与门禁结论")
    check(record["rules_hash"].startswith("sha256:") and record["git"]["repo"],
          "交付记录含规则集指纹与 git 锚点")
    check(record["skills"][0]["skill"] == "good-skill", "交付记录含逐技能结论")

    # 坏技能 → 阻断 + 退出码 1
    bad = write_skill(repo / ".agents" / "skills", "bad-skill", with_guide=False)
    code, _out, err = run_cli([
        "deliver", "--project", str(repo), "--user-home", str(home),
        "--stages", "lint", "--quiet", "--verbose",
    ])
    check(code == 1 and "阻断 bad-skill · REF-001" in err,
          f"断链技能被交付门禁阻断（exit={code}）")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    check(record["gate"]["result"] == "fail" and record["gate"]["blockers"],
          "未通过也写记录（留痕比好看重要）")
    check((repo / ".agents" / "skillverify" / "deliver" / "history.jsonl").read_text(
        encoding="utf-8").count("\n") >= 2, "history.jsonl 逐次追加")

    # 有脚本但未开 --scripts → 可选项未覆盖，默认放行
    script_skill = write_skill(repo / ".agents" / "skills", "scripted-skill")
    (script_skill / "scripts").mkdir()
    (script_skill / "scripts" / "tool.py").write_text(
        "import argparse\n\np = argparse.ArgumentParser()\np.parse_args()\n",
        encoding="utf-8", newline="")
    (script_skill / "SKILL.md").write_text(
        f"---\nname: scripted-skill\ndescription: {DESC}\n---\n\n"
        "- `scripts/tool.py` — demo\n\nRead `references/guide.md`.\n",
        encoding="utf-8", newline="")
    shutil.rmtree(bad)
    code, _out, err = run_cli([
        "deliver", "--project", str(repo), "--user-home", str(home),
        "--stages", "lint", "--quiet", "--verbose",
    ])
    check(code == 0 and "未覆盖" in err and "SCRIPT-004" in err,
          f"未开启的可选批次记未覆盖但不阻断（exit={code}）")
    code, _out, _err = run_cli([
        "deliver", "--project", str(repo), "--user-home", str(home),
        "--stages", "lint", "--quiet", "--strict",
    ])
    check(code == 1, f"--strict 下未覆盖项阻断（exit={code}）")

    # 没有技能受影响 → 不阻断、不记账
    empty = make_repo(tmp / "dl-empty")
    before = list((empty / ".agents").rglob("*"))
    code, _out, err = run_cli([
        "deliver", "--project", str(empty), "--user-home", str(home),
        "--stages", "spec", "--quiet",
    ])
    check(code == 0 and "没有需要检查的技能" in err, "无技能可查时放行并说明")
    check(not (empty / ".agents" / "skillverify").exists(), "无技能可查时不生成记录")

    # 前置失败（frontmatter 不可解析）→ 全项 SKIP → 阻断
    broken = make_repo(tmp / "dl-broken")
    skill = broken / ".agents" / "skills" / "broken-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# 没有 frontmatter\n", encoding="utf-8", newline="")
    code, _out, err = run_cli([
        "deliver", "--project", str(broken), "--user-home", str(home),
        "--stages", "lint", "--quiet",
    ])
    check(code == 1 and "阻断" in err, f"前置失败导致的全项未执行阻断交付（exit={code}）")


# --------------------------------------------------------------------------- #
# git hook
# --------------------------------------------------------------------------- #


def run_hook_fallback(tmp: Path) -> None:
    """hook 的兜底调用不许依赖 PYTHONPATH（嵌入式解释器会忽略它），且安装时要自测。

    早先兜底是 `PYTHONPATH=... exec "$PY" -m skillverify.cli`：在带 `._pth` 的嵌入式发行版上
    PYTHONPATH 被忽略 → 兜底静默失效，hook 只打印告警就放行（等于空转）。
    """
    print("[test_hook_fallback]")
    content = deliver.hook_content(sys.executable, Path("/checkout"))
    check("PYTHONPATH=" not in content and "export PYTHONPATH" not in content,
          "hook 不再用 PYTHONPATH 注入路径（注释里提到它没关系）")
    check("sys.path.insert" in content, "hook 用 sys.path.insert 把 checkout 放进路径")
    check("skillverify.cli" in content, "hook 仍然调用同一个入口")

    checkout = Path(__file__).resolve().parent.parent
    # cwd 用临时目录：真实 hook 的 cwd 是「被提交的那个项目」，不是本工具的 checkout
    with tempfile.TemporaryDirectory(prefix="sv_hookprobe_") as neutral:
        neutral_dir = Path(neutral)
        ok, why = deliver.probe_hook_fallback(sys.executable, checkout, cwd=neutral_dir)
        check(ok, f"兜底自测在非 checkout 目录下也能导入（实得 {ok}：{why}）")
        bad_ok, bad_why = deliver.probe_hook_fallback(sys.executable,
                                                     Path("/nonexistent-checkout"),
                                                     cwd=neutral_dir)
        check(not bad_ok and bool(bad_why), f"自测能失败（假 checkout → {bad_why[:40]}）")


def run_hook(tmp: Path) -> None:
    print("[test_hook]")
    repo = make_repo(tmp / "hk")
    home = tmp / "hk-home"
    home.mkdir(parents=True, exist_ok=True)

    state, path = deliver.hook_status(repo)
    check(state == "未安装", f"初始状态为未安装（实得 {state}）")

    code, out, _err = run_cli(["hook", "install", "--project", str(repo)])
    hook_file = deliver.hook_path(repo)
    check(code == 0 and hook_file.is_file(), "hook 安装成功")
    content = hook_file.read_text(encoding="utf-8")
    check(deliver.HOOK_MARKER in content and "deliver --staged" in content,
          "hook 内容含标记行与 deliver --staged 调用")
    check(str(Path(sys.executable).resolve()).replace("\\", "/") in content,
          "hook 记录了当前解释器路径（未安装为命令时的兜底）")

    state, _path = deliver.hook_status(repo)
    check("已安装" in state and deliver.HOOK_VERSION in state, f"状态可识别（实得 {state}）")

    code, out, _err = run_cli(["hook", "install", "--project", str(repo)])
    check(code == 0 and "已更新" in out, "重复安装幂等")

    # 他人 hook → 拒绝；--force → 备份后覆盖
    foreign = repo / "foreign-marker"
    hook_file.write_text("#!/bin/sh\necho foreign\n", encoding="utf-8", newline="")
    code, _out, err = run_cli(["hook", "install", "--project", str(repo)])
    check(code == 1 and "不是 skillverify 的 hook" in err and "foreign" in hook_file.read_text(
        encoding="utf-8"), "存在他人 hook 时拒绝改动且不破坏原文件")
    code, out, _err = run_cli(["hook", "install", "--project", str(repo), "--force"])
    backup = hook_file.with_name("pre-commit.bak")
    check(code == 0 and backup.is_file() and "foreign" in backup.read_text(encoding="utf-8"),
          "--force 覆盖前先备份原 hook")
    foreign.unlink(missing_ok=True)

    # 非 git 仓库 → 明确报错
    plain = tmp / "hk" / "not-a-repo"
    plain.mkdir(parents=True, exist_ok=True)
    code, _out, err = run_cli(["hook", "install", "--project", str(plain)])
    check(code == 1 and "不是 git 仓库" in err, "非 git 仓库安装被拒绝")

    # 裸 `hook` 子命令给出用法
    code, _out, err = run_cli(["hook"])
    check(code == 1 and "用法" in err, "裸 `hook` 打印用法并返回 1")

    # 端到端：坏技能提交被拦，修好后放行
    e2e = make_repo(tmp / "hk" / "e2e")
    skill = write_skill(e2e / ".agents" / "skills", "demo-skill",
                        body="# Demo\n\nSee `references/missing.md`.\n", with_guide=False)
    run_cli(["hook", "install", "--project", str(e2e)])
    git(e2e, "add", "-A")
    proc = git(e2e, "commit", "-m", "坏技能应被拦截")
    log = git(e2e, "log", "--oneline").stdout.strip()
    check(proc.returncode != 0 and "交付门禁未通过" in proc.stderr,
          f"端到端：坏技能提交被 hook 拦截（exit={proc.returncode}）")
    check(log == "", "端到端：仓库历史里确实没有这次提交")

    (skill / "references").mkdir(parents=True, exist_ok=True)
    (skill / "references" / "guide.md").write_text("# Guide\n", encoding="utf-8", newline="")
    (skill / "SKILL.md").write_text(
        f"---\nname: demo-skill\ndescription: {DESC}\n---\n\n"
        "# Demo\n\nRead `references/guide.md`.\n", encoding="utf-8", newline="")
    git(e2e, "add", "-A")
    proc = git(e2e, "commit", "-m", "修好后应放行")
    check(proc.returncode == 0 and git(e2e, "log", "--oneline").stdout.strip() != "",
          f"端到端：修好后提交放行（exit={proc.returncode}）")

    # 只改非技能文件时 hook 不应阻断
    (e2e / "README.md").write_text("# repo\n", encoding="utf-8", newline="")
    git(e2e, "add", "-A")
    proc = git(e2e, "commit", "-m", "只改非技能文件")
    check(proc.returncode == 0 and "没有需要检查的技能" in proc.stderr,
          f"端到端：非技能文件改动不阻断（exit={proc.returncode}）")

    # 逃生阀
    (skill / "SKILL.md").write_text(
        f"---\nname: demo-skill\ndescription: {DESC}\n---\n\n"
        "# Demo\n\nSee `references/gone.md`.\n", encoding="utf-8", newline="")
    git(e2e, "add", "-A")
    proc = git(e2e, "commit", "--no-verify", "-m", "显式绕过门禁")
    check(proc.returncode == 0, "`git commit --no-verify` 可绕过（git 既有语义，不假装防得住）")


# --------------------------------------------------------------------------- #
# --staged 归属判定
# --------------------------------------------------------------------------- #


def run_staged_filter(tmp: Path) -> None:
    print("[test_staged_filter]")
    repo = make_repo(tmp / "st")
    home = tmp / "st-home"
    home.mkdir(parents=True, exist_ok=True)
    target = write_skill(repo / ".agents" / "skills", "demo-skill")
    write_skill(repo / ".agents" / "skills", "other-skill")
    profile = load_config(repo, home, use_discovered_files=False).profile(None)
    discovery = discover_skills(profile, repo, home)

    git(repo, "add", "-A")
    git(repo, "commit", "-m", "init")
    (target / "references" / "guide.md").write_text("# changed\n", encoding="utf-8", newline="")
    (repo / "README.md").write_text("x\n", encoding="utf-8", newline="")
    git(repo, "add", "-A")

    affected, unrelated, note = deliver.filter_staged_skills(repo, discovery)
    check([s.name for s in affected] == ["demo-skill"] and note is None,
          f"暂存改动只映射到受影响的技能（实得 {[s.name for s in affected]}）")
    check(unrelated == ["README.md"], f"无关注文件被单独列出（实得 {unrelated}）")

    non_repo = tmp / "st" / "plain"
    (non_repo / ".agents" / "skills").mkdir(parents=True)
    disc2 = discover_skills(profile, non_repo, home)
    affected2, _unrelated2, note2 = deliver.filter_staged_skills(non_repo, disc2)
    check(note2 is not None and "非 git" in note2,
          "非 git 仓库时退化为全量并说明原因")

    code, out, _err = run_cli([
        "deliver", "--project", str(repo), "--user-home", str(home), "--staged",
        "--stages", "spec", "--json",
    ])
    payload = json.loads(out)
    checked = [s["skill"] for s in payload["skills"]]
    check(code == 0 and checked == ["demo-skill"],
          f"--staged 只查受影响技能（实得 {checked}，exit={code}）")
    check(payload["scope"] == "staged" and payload["unrelated_staged"] == ["README.md"],
          "--staged 记录里写明范围与无关注文件")


# --------------------------------------------------------------------------- #
# dogfood
# --------------------------------------------------------------------------- #



def run_deliver_previous(tmp: Path) -> None:
    """V29 的仓库侧：**写入前**与上一轮比对，退步要当场说出来。

    旧体系用 `.iteration-baseline` 快照防覆盖（含绝对路径、换机即误报，已舍弃）；
    这里改用「覆盖前对比 + 追加式 history」：既不丢历史，又能看出「这次改动把它改坏了」。
    """
    print("[test_deliver_previous]")
    repo = make_repo(tmp)
    skill = write_skill(repo / ".agents" / "skills", "demo-skill")
    (skill / "references").mkdir(exist_ok=True)
    (skill / "references" / "guide.md").write_text("# 指南\n", encoding="utf-8", newline="")
    home = tmp / "home"
    home.mkdir(parents=True, exist_ok=True)
    # 不要加 --quiet：它会把 --json 的报告一起静音（本项目已知的坑）
    common = ["--project", str(repo), "--user-home", str(home), "--stages", "both", "--json"]

    code1, out1, _err1 = run_cli(["deliver", *common])
    rec1 = json.loads(out1)
    check(code1 == 0 and rec1["previous"]["found"] is False,
          f"第一次交付：没有可比的上一轮（实得 {rec1['previous']['note'][:40]}）")

    _code2, out2, _e2 = run_cli(["deliver", *common])
    rec2 = json.loads(out2)
    check(rec2["previous"]["found"] is True and rec2["previous"]["worse"] is False,
          "第二次交付（内容未变）：有上一轮可比，且未退步")
    check("无实质变化" in rec2["previous"]["note"], "note 写清了对比结论")

    # 把技能改坏 → 下一次交付必须标记退步，并列出变化的技能
    (skill / "SKILL.md").write_text(
        (skill / "SKILL.md").read_text(encoding="utf-8")
        + "\n引用不存在的文件：`references/missing.md`\n", encoding="utf-8", newline="")
    code3, out3, _e3 = run_cli(["deliver", *common])
    rec3 = json.loads(out3)
    check(code3 == 1 and rec3["previous"]["worse"] is True,
          "改坏之后：标记为退步（这是「这次的改动让它变差了」的唯一自动信号）")
    check("退步" in rec3["previous"]["note"] and "→" in rec3["previous"]["note"],
          f"note 给出前后对比（{rec3['previous']['note'][:80]}）")
    check(any("demo-skill" in item for item in rec3["previous"]["changed_skills"]),
          f"列出发生变化的技能（实得 {rec3['previous']['changed_skills']}）")

    history = repo / ".agents" / "skillverify" / "deliver" / "history.jsonl"
    lines = [ln for ln in history.read_text(encoding="utf-8").splitlines() if ln.strip()]
    check(len(lines) == 3, f"history.jsonl 是追加式的（三轮各一行，实得 {len(lines)}）")

def run_dogfood(repo: Path) -> None:
    print("[test_dogfood]")
    legacy = repo / "legacy"
    if not legacy.is_dir():
        ok("无 legacy/ 目录，跳过")
        return
    with tempfile.TemporaryDirectory(prefix="sv_auto_home_") as home:
        code, out, err = run_cli([
            "deliver", "--project", str(repo), "--user-home", home,
            "--root", str(legacy), "--stages", "lint", "--json",
        ])
    payload = json.loads(out)
    for item in payload["gate"]["blockers"]:
        print(f"  · 阻断 {item[:110]}")
    print(f"  · 未覆盖 {len(payload['gate']['uncovered'])} 项；"
          f"待甄别 {len(payload['gate']['warnings'])} 项")
    check(code == 1 and payload["gate"]["result"] == "fail",
          "legacy/ 交付未通过（REF-003 宿主绝对路径，属预期真阳性）")
    check(payload["gate"]["checked_skills"] == 4, "legacy/ 4 个技能全部参与交付门禁")


# --------------------------------------------------------------------------- #


def main() -> int:
    force_utf8_stdio()
    parser = argparse.ArgumentParser(description="skillverify watch/deliver/hook 回归测试")
    parser.add_argument("--dogfood", action="store_true",
                        help="额外对 legacy/ 跑一次 deliver 并打印阻断项")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="sv_test_automation_"))
    try:
        run_watch_helpers(tmp)
        run_watch_loop(tmp)
        run_gate(tmp)
        run_deliver_command(tmp)
        run_deliver_previous(tmp)
        if shutil.which("git"):
            run_hook(tmp)
            run_hook_fallback(tmp)
            run_staged_filter(tmp)
        else:
            ok("git 不可用：hook / --staged 用例跳过")
        if args.dogfood:
            run_dogfood(Path(__file__).resolve().parent.parent)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = len(_passed) + len(_failed)
    print(f"\n结果: PASS={len(_passed)} FAIL={len(_failed)} 合计={total}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
