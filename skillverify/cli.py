"""cli —— skillverify 命令行入口。

约定（全族统一，便于任何宿主/CI 消费）：
- 退出码：0=全 PASS；1=有 FAIL；2=无 FAIL 但有 WARN/SKIP。
- 报告默认打到 stdout；`--out` 可落盘；`--json` 输出机读结构。
- 参数错误一律 stderr + 用法 + 退出码 1（不撞 WARN 码 2）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .deliver import (
    build_record,
    evaluate,
    filter_staged_skills,
    hook_status,
    install_hook,
    is_git_repo,
    write_record,
)
from .discover import Config, ConfigError, Discovery, load_config, discover_skills, render_config
from .encoding import force_utf8_stdio, write_text
from .evalx import check_evals
from .review import (
    CatalogError,
    build_pack,
    check_review,
    collect as collect_reviews,
    emit_skill,
    load_catalog,
    render_prompts_md,
    select_prompts,
    status as review_status,
    write_record as write_review_record,
)
from .lint import lint_skill
from .report import FAIL, PASS, SKIP, WARN, LibraryEntry, LibraryReport, Report, Result
from .spec import check_spec, find_official_cli, run_official
from .watch import run_watch

PROG = "skillverify"


class _ArgParser(argparse.ArgumentParser):
    """参数错误统一走退出码 1（argparse 默认是 2，会与 WARN 码冲突）。"""

    def error(self, message: str) -> None:  # type: ignore[override]
        print(f"参数错误: {message}", file=sys.stderr)
        print(f"用法: {PROG} <命令> [选项]；详见 {PROG} --help", file=sys.stderr)
        raise SystemExit(1)


def _looks_like_workspace(path: Path) -> list[Path]:
    """判断传入的是否是"技能集合目录"而非单个技能。

    常见误用：把仓库根或技能库根传进来，然后得到"缺少 SKILL.md"的误导性 FAIL。
    这里扫描一层子目录，找出其中含 SKILL.md 的，用于给出可操作提示。
    """
    found: list[Path] = []
    try:
        for child in sorted(path.iterdir()):
            if not child.is_dir():
                continue
            if (child / "SKILL.md").is_file() or (child / "skill.md").is_file():
                found.append(child)
    except OSError:
        return []
    return found


def cmd_spec(args: argparse.Namespace) -> int:
    """官方规范校验（离线，纯标准库复刻官方校验器行为）。"""
    path = Path(args.path)
    if not path.exists():
        print(f"FAIL: 路径不存在: {path}", file=sys.stderr)
        return 1

    # 友好纠错：传了技能集合目录而不是单个技能
    if path.is_dir() and not (path / "SKILL.md").is_file() and not (path / "skill.md").is_file():
        candidates = _looks_like_workspace(path)
        if candidates:
            print(
                f"该路径下没有 SKILL.md，但发现 {len(candidates)} 个技能子目录：",
                file=sys.stderr,
            )
            for cand in candidates:
                print(f"  - {cand}", file=sys.stderr)
            print(
                "请对具体技能目录运行，或用 `skillverify check` 对整库批量运行"
                "（该命令在后续版本提供）。",
                file=sys.stderr,
            )
            return 1

    doc, report = check_spec(path)
    report.meta["工具版本"] = f"{PROG} {__version__}"
    report.meta["实现口径"] = "纯标准库复刻 skills-ref 0.1.1 行为（离线可用）"

    if args.official:
        cli = find_official_cli()
        report.add(run_official(path, cli))
        report.meta["官方校验器"] = cli or "未找到（已记 SKIP）"

    _emit(report, args)
    return report.exit_code()


def cmd_lint(args: argparse.Namespace) -> int:
    """官方校验器留白的补检（引用/预算/卫生/脚本契约/依赖/安全/编码）。"""
    path = Path(args.path)
    if not path.exists():
        print(f"FAIL: 路径不存在: {path}", file=sys.stderr)
        return 1

    report = lint_skill(
        path,
        run_scripts=args.scripts,
        script_timeout_s=args.script_timeout,
    )
    report.meta["工具版本"] = f"{PROG} {__version__}"

    _emit(report, args)

    if not args.scripts:
        skipped = [r for r in report.results if r.status == SKIP and "--scripts" in r.evidence]
        if skipped:
            print(
                f"提示：{len(skipped)} 项脚本契约实测未执行（因此退出码为 2 而非 0）；"
                f"加 --scripts 开启（注意：会以 `--help` 调用技能自带脚本）。",
                file=sys.stderr,
            )
    return report.exit_code()


def _status_exit(results: list[Result]) -> int:
    """按一组结果算退出码（与 Report/LibraryReport 同口径）。"""
    if any(r.status == FAIL for r in results):
        return 1
    if any(r.status in (WARN, SKIP) for r in results):
        return 2
    return 0


def _wants(stages: str, name: str) -> bool:
    """`--stages` 的选择语义：all=全跑；both=spec+lint（M2/M3 的既有默认，保留兼容）；
    其余为单阶段。"""
    if stages == "all":
        return True
    if stages == "both":
        return name in ("spec", "lint")
    return stages == name


def _stage_results(skill_path: Path, args: argparse.Namespace,
                   trace_dir: Path | None = None) -> list[Result]:
    """按 --stages 依次跑各阶段，返回合并后的结果列表。"""
    results: list[Result] = []
    if _wants(args.stages, "spec"):
        _doc, rep = check_spec(skill_path)
        results.extend(rep.results)
        if getattr(args, "official", False):
            results.append(run_official(skill_path, getattr(args, "_official_cli", None)))
    if _wants(args.stages, "lint"):
        rep = lint_skill(skill_path, run_scripts=getattr(args, "scripts", False),
                         script_timeout_s=getattr(args, "script_timeout", 10.0))
        results.extend(rep.results)
    if _wants(args.stages, "evals"):
        rep = check_evals(skill_path, workspace=getattr(args, "workspace", None),
                          iteration=getattr(args, "iteration", None))
        results.extend(rep.results)
    if _wants(args.stages, "review") and trace_dir is not None:
        results.extend(check_review(skill_path, trace_dir,
                                    skipped=getattr(args, "skip_review", False)))
    return results


def _load_discovery(args: argparse.Namespace) -> tuple[Discovery, Config]:
    """按命令行参数加载配置并发现技能。"""
    project = Path(args.project).expanduser()
    user_home = Path(args.user_home).expanduser() if args.user_home else Path.home()
    config = load_config(
        project,
        user_home,
        [Path(p) for p in (args.config or [])],
        use_discovered_files=not args.no_config,
    )
    profile = config.profile(args.host)
    discovery = discover_skills(
        profile, project, user_home, roots=args.root or None
    )
    return discovery, config


def _render_discovery(discovery: Discovery, project: Path, config: Config) -> str:
    lines = [
        "# skillverify 发现结果",
        "",
        f"- 项目根: {project}",
        f"- 宿主档: {discovery.profile.name}（{discovery.profile.description or '无说明'}）",
        f"- 配置来源: {' < '.join(config.sources)}",
        f"- 留痕目录: {discovery.trace_dir}",
        f"- 发现技能: {len(discovery.skills)} 个",
        "",
        "## 技能根",
        "",
        "| 根 | 作用域 | 存在 | 命中 | 说明 |",
        "|---|---|---|---|---|",
    ]
    for info in discovery.roots:
        note = info.note or ""
        lines.append(
            f"| {info.label} | {info.scope} | {'是' if info.exists else '否'} "
            f"| {info.found} | {note} |"
        )
    lines += ["", "## 技能", ""]
    if discovery.skills:
        lines += ["| 技能 | 作用域 | 路径 |", "|---|---|---|"]
        for ref in discovery.skills:
            lines.append(f"| {ref.name} | {ref.scope} | {ref.path} |")
    else:
        lines.append("（无）")
    if discovery.results:
        lines += ["", "## 库级结果", "", "| 规则 | 级别 | 判定 | 说明 | 证据 |", "|---|---|---|---|---|"]
        for res in discovery.results:
            lines.append(
                f"| {res.rid} | {res.level} | {res.status} | {res.title} | {res.evidence} |"
            )
    lines += [
        "",
        "> 未发现技能不等于通过：`discover` 只报告发现了什么，"
        "`check` 才会对发现的技能逐条判定。",
        "",
    ]
    return "\n".join(lines)


def cmd_discover(args: argparse.Namespace) -> int:
    """列出技能发现结果（含每个根的命中情况），不执行任何检查。"""
    try:
        discovery, config = _load_discovery(args)
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 1

    if args.show_config:
        print(render_config(config))
        return 0

    text = discovery.to_json() if args.json else _render_discovery(
        discovery, Path(args.project).expanduser().resolve(), config
    )
    if args.out:
        write_text(Path(args.out), text if text.endswith("\n") else text + "\n")
        print(f"结果已落盘: {args.out}")
    if not args.quiet:
        print(text if text.endswith("\n") else text + "\n")

    if not discovery.skills and not args.quiet:
        print(
            f"提示：未发现任何技能。用 `{PROG} discover --show-config` 核对根列表，"
            f"或用 `--root <目录>` 直接指定技能根。",
            file=sys.stderr,
        )
    return _status_exit(discovery.results)


def cmd_check(args: argparse.Namespace) -> int:
    """对整库批量执行 spec + lint，并输出汇总报告。"""
    try:
        discovery, config = _load_discovery(args)
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 1

    project = Path(args.project).expanduser().resolve()
    library = LibraryReport(stage="check", target=str(project))
    library.meta["工具版本"] = f"{PROG} {__version__}"
    library.meta["宿主档"] = f"{discovery.profile.name}（max_depth={discovery.profile.max_depth}）"
    library.meta["配置来源"] = " < ".join(config.sources)
    library.meta["检查阶段"] = args.stages
    for res in discovery.results:
        library.add(res)

    official = find_official_cli() if args.official else None
    if args.official:
        library.meta["官方校验器"] = official or "未找到（对账项记 SKIP）"
    args._official_cli = official

    for ref in discovery.skills:
        merged = Report(target=str(ref.path), stage="check")
        merged.results = _stage_results(ref.path, args, discovery.trace_dir)
        library.add_entry(
            LibraryEntry(skill=ref.name, scope=ref.scope, path=str(ref.path), report=merged)
        )

    text = library.to_json() if args.json else library.to_markdown()

    if args.trace or args.out:
        targets: list[tuple[Path, str]] = []
        if args.out:
            targets.append((Path(args.out), text))
        if args.trace:
            assert discovery.trace_dir is not None
            targets.append((discovery.trace_dir / (f"check{'.json' if args.json else '.md'}"), text))
            if not args.json:
                targets.append((discovery.trace_dir / "check.json", library.to_json()))
        for path, payload in targets:
            write_text(path, payload if payload.endswith("\n") else payload + "\n")
            print(f"报告已落盘: {path}")

    if not args.quiet:
        print(text if text.endswith("\n") else text + "\n")

    if not discovery.skills:
        print(
            f"FAIL: 未发现任何技能——没有任何东西被检查。"
            f"用 `{PROG} discover --show-config` 核对根列表，或用 `--root <目录>` 指定技能根。",
            file=sys.stderr,
        )
        return 1

    if not args.quiet:
        summary = library.skill_verdicts()
        for entry in library.entries:
            if entry.report.verdict() == FAIL:
                bad = [r.rid for r in entry.report.results if r.status == FAIL]
                print(f"  FAIL {entry.skill}: {', '.join(bad)}", file=sys.stderr)
        if any(e.report.verdict() == FAIL for e in library.entries):
            print(
                f"—— 汇总：技能 {len(library.entries)} 个"
                f"（PASS={summary[PASS]} WARN={summary[WARN]} FAIL={summary[FAIL]}）——",
                file=sys.stderr,
            )
    else:
        summary = library.skill_verdicts()
        print(
            f"—— 汇总：技能 {len(library.entries)} 个"
            f"（PASS={summary[PASS]} WARN={summary[WARN]} FAIL={summary[FAIL]}）——",
            file=sys.stderr,
        )

    if _wants(args.stages, "lint") and not args.scripts:
        skipped = sum(
            1 for entry in library.entries for r in entry.report.results
            if r.status == SKIP and "--scripts" in r.evidence
        )
        if skipped:
            print(
                f"提示：{skipped} 项脚本契约实测未执行（因此退出码不为 0）；加 --scripts 开启。",
                file=sys.stderr,
            )
    return library.exit_code()


def cmd_watch(args: argparse.Namespace) -> int:
    """轮询技能库，变化即复跑并打印增量报告。"""
    try:
        discovery, _config = _load_discovery(args)
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 1
    assert discovery.profile is not None
    try:
        return run_watch(
            Path(args.project).expanduser(),
            Path(args.user_home).expanduser() if args.user_home else Path.home(),
            discovery.profile,
            roots=args.root or None,
            stages=args.stages,
            interval=max(0.01, args.interval),
            cycles=1 if args.once else args.cycles,
            script_timeout_s=args.script_timeout,
            as_json=args.json,
        )
    except KeyboardInterrupt:
        print("\n[watch] 已停止。", file=sys.stderr)
        return 0


def cmd_deliver(args: argparse.Namespace) -> int:
    """交付门禁：0 FAIL 且 0 未覆盖项才算通过，并写交付记录。"""
    try:
        discovery, config = _load_discovery(args)
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 1

    project = Path(args.project).expanduser().resolve()
    unrelated: list[str] = []
    scope = "all"
    note = None
    if args.staged:
        affected, unrelated, note = filter_staged_skills(project, discovery)
        discovery.skills = affected
        scope = "staged"

    library = LibraryReport(stage="deliver", target=str(project))
    library.meta["工具版本"] = f"{PROG} {__version__}"
    library.meta["宿主档"] = discovery.profile.name if discovery.profile else "?"
    library.meta["配置来源"] = " < ".join(config.sources)
    library.meta["范围"] = scope + (f"（{note}）" if note else "")
    for res in discovery.results:
        library.add(res)

    for ref in discovery.skills:
        merged = Report(target=str(ref.path), stage="deliver")
        merged.results = _stage_results(ref.path, args, discovery.trace_dir)
        library.add_entry(
            LibraryEntry(skill=ref.name, scope=ref.scope, path=str(ref.path), report=merged)
        )

    gate = evaluate(library, strict=args.strict)
    markdown = library.to_markdown()
    command = f"{PROG} deliver {'--staged ' if args.staged else ''}" \
              f"--project {args.project}" + (" --strict" if args.strict else "")
    record = build_record(
        library, gate, project=project, scope=scope, command=command.strip(),
        discovery=discovery, unrelated=unrelated,
    )
    # `--json` 输出的是**交付记录本身**（含门禁结论）：门禁命令的机读输出必须带结论，
    # 否则 CI 只能靠退出码猜。markdown 与人读报告仍是分开的两种渲染。
    text = json.dumps(record, ensure_ascii=False, indent=2) if args.json else markdown

    print(f"{'PASS' if gate.passed else 'FAIL'}: {gate.summary()}", file=sys.stderr)
    for item in gate.blockers:
        print(f"  阻断 {item}", file=sys.stderr)
    if args.verbose:
        for item in gate.uncovered:
            print(f"  未覆盖 {item}", file=sys.stderr)
        for item in gate.warnings:
            print(f"  待甄别 {item}", file=sys.stderr)

    if not args.quiet:
        print(text if text.endswith("\n") else text + "\n")

    if not discovery.skills:
        # 本次提交没有触及任何技能（hook 场景常见）：无事可查，不阻断、不记账。
        print("提示：本次没有需要检查的技能，未生成交付记录。", file=sys.stderr)
        return 0
    if args.no_record:
        return 0 if gate.passed else 1

    assert discovery.trace_dir is not None
    if args.out:
        write_text(Path(args.out), text if text.endswith("\n") else text + "\n")
        print(f"报告已落盘: {args.out}")
    written = write_record(discovery.trace_dir, record, markdown)
    print("交付记录: " + "；".join(str(p) for p in written), file=sys.stderr)
    return 0 if gate.passed else 1


def cmd_evals(args: argparse.Namespace) -> int:
    """校验技能的评测资产（evals.json 与评测工作区产物）。"""
    path = Path(args.path)
    if not path.exists():
        print(f"FAIL: 路径不存在: {path}", file=sys.stderr)
        return 1
    report = check_evals(
        path,
        workspace=Path(args.workspace) if args.workspace else None,
        iteration=args.iteration,
    )
    report.meta["工具版本"] = f"{PROG} {__version__}"
    report.meta["官方口径"] = "agentskills.io/skill-creation/evaluating-skills"
    _emit(report, args)
    return report.exit_code()


def cmd_review(args: argparse.Namespace) -> int:
    """语义评审：提示词目录 / 任务包 / 回写汇总 / 独立技能包 / 状态。"""
    action = getattr(args, "review_action", None)
    if not action:
        print(f"用法: {PROG} review <prompts|pack|collect|status|skill> [选项]", file=sys.stderr)
        return 1
    try:
        catalog = load_catalog()
    except CatalogError as exc:
        print(f"提示词目录错误: {exc}", file=sys.stderr)
        return 1

    if action == "prompts":
        prompts = select_prompts(catalog, args.prompts, args.family)
        if args.json:
            payload = json.dumps({"version": 1, "prompts": [p.to_dict() for p in prompts]},
                                 ensure_ascii=False, indent=2)
        else:
            payload = render_prompts_md(prompts)
        if args.out:
            write_text(Path(args.out), payload if payload.endswith("\n") else payload + "\n")
            print(f"已落盘: {args.out}")
        if not args.quiet:
            print(payload if payload.endswith("\n") else payload + "\n")
        return 0

    if action == "pack":
        skill_dir = Path(args.path)
        if not skill_dir.is_dir():
            print(f"FAIL: 技能目录不存在: {skill_dir}", file=sys.stderr)
            return 1
        try:
            prompts = select_prompts(catalog, args.prompts, args.family)
        except CatalogError as exc:
            print(f"提示词选择错误: {exc}", file=sys.stderr)
            return 1
        if not prompts:
            print("FAIL: 选中的提示词为空", file=sys.stderr)
            return 1
        written = build_pack(skill_dir, prompts,
                             out_dir=Path(args.out) if args.out else None, split=args.split)
        for path in written:
            print(f"已生成: {path}")
        print(f"\n下一步：把任务包交给任意 LLM 或人填写，"
              f"然后 `{PROG} review collect <填好的模板>`。")
        return 0

    if action == "skill":
        out = Path(args.out) if args.out else Path(".")
        for path in emit_skill(out, catalog, name=args.name):
            print(f"已生成: {path}")
        print("\n该技能包自包含（SKILL.md + references/ + assets/），"
              "放到任意宿主的技能目录即可加载。")
        return 0

    if action == "collect":
        paths: list[Path] = [Path(p) for p in (args.files or [])]
        if args.dir:
            paths.extend(sorted(Path(args.dir).glob("*.json")))
        if not paths:
            print("FAIL: 没有要汇总的回写文件（给文件名或 --dir）", file=sys.stderr)
            return 1
        missing = [str(p) for p in paths if not p.is_file()]
        if missing:
            print(f"FAIL: 文件不存在: {', '.join(missing)}", file=sys.stderr)
            return 1

        try:
            discovery, _config = _load_discovery(args)
        except ConfigError as exc:
            print(f"配置错误: {exc}", file=sys.stderr)
            return 1
        skill_dir = Path(args.skill_dir) if args.skill_dir else None
        expected: list[str] | None = None
        if skill_dir is not None:
            manifest = skill_dir.parent / f"{skill_dir.name}-review" / (
                f"{skill_dir.name}-review-manifest.json")
            if manifest.is_file():
                try:
                    expected = json.loads(manifest.read_text(encoding="utf-8")).get("prompt_ids")
                except (OSError, json.JSONDecodeError):
                    expected = None
        report, record = collect_reviews(paths, catalog, skill_dir=skill_dir,
                                        expected_ids=expected)
        report.meta["工具版本"] = f"{PROG} {__version__}"
        report.meta["提示词目录"] = f"{len(catalog)} 条"
        text = report.to_json() if args.json else report.to_markdown()
        if args.out:
            write_text(Path(args.out), text if text.endswith("\n") else text + "\n")
            print(f"报告已落盘: {args.out}")
        if not args.quiet:
            print(text if text.endswith("\n") else text + "\n")

        if not args.no_store:
            assert discovery.trace_dir is not None
            latest = write_review_record(discovery.trace_dir / "review", record)
            print(f"评审记录: {latest}", file=sys.stderr)
        print(f"结论: {record['verdict']}（阻断项 {len(record['blocking_fails'])}；"
              f"未覆盖 {len(record['uncovered_prompts'])}）", file=sys.stderr)
        return report.exit_code()

    if action == "status":
        try:
            discovery, _config = _load_discovery(args)
        except ConfigError as exc:
            print(f"配置错误: {exc}", file=sys.stderr)
            return 1
        assert discovery.trace_dir is not None
        text = review_status(discovery.trace_dir,
                             [(ref.name, ref.path) for ref in discovery.skills])
        if args.out:
            write_text(Path(args.out), text)
            print(f"已落盘: {args.out}")
        if not args.quiet:
            print(text)
        return 0

    print(f"FAIL: 未知动作 {action!r}", file=sys.stderr)
    return 1


def cmd_hook(args: argparse.Namespace) -> int:
    """安装/查看 pre-commit 交付门禁。"""
    if not getattr(args, "hook_action", None):
        print("用法: skillverify hook <install|status> [--project 目录]", file=sys.stderr)
        return 1
    project = Path(args.project).expanduser().resolve()
    if args.hook_action == "status":
        state, path = hook_status(project)
        print(f"hook 状态: {state}")
        print(f"路径: {path}")
        return 0
    if not is_git_repo(project):
        print(f"FAIL: 不是 git 仓库: {project}", file=sys.stderr)
        return 1
    try:
        path, action = install_hook(project, force=args.force,
                                    fail_closed=args.fail_closed)
    except RuntimeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"pre-commit {action}: {path}")
    print("提交时自动执行 `skillverify deliver --staged`；"
          "临时跳过用 `git commit --no-verify`。")
    return 0


def _emit(report: Report, args: argparse.Namespace) -> None:
    """按参数输出报告，并把 FAIL 明细同步到 stderr（便于管道消费）。"""
    if args.json:
        text = report.to_json()
    else:
        text = report.to_markdown()

    if args.out:
        write_text(Path(args.out), text if text.endswith("\n") else text + "\n")
        print(f"报告已落盘: {args.out}")

    if not args.quiet:
        print(text if text.endswith("\n") else text + "\n")

    if not args.quiet:
        fails = [r for r in report.results if r.status == FAIL]
        if fails:
            print(f"—— FAIL 明细（{len(fails)} 条）——", file=sys.stderr)
            for res in fails:
                print(f"  [{res.rid}] {res.title}: {res.evidence}", file=sys.stderr)


def build_parser() -> _ArgParser:
    parser = _ArgParser(
        prog=PROG,
        description="Agent Skill 生命周期验证套件（个人小团队版，宿主无关）",
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<命令>")

    p_spec = sub.add_parser(
        "spec",
        help="官方规范校验（frontmatter 6 字段白名单与命名约定）",
        description=(
            "按官方 Agent Skills 规范校验单个技能。离线实现，行为对齐 "
            "skills-ref 0.1.1；加 --official 可与官方 CLI 对账。"
        ),
    )
    p_spec.add_argument("path", help="技能目录（含 SKILL.md）")
    p_spec.add_argument("--official", action="store_true",
                        help="额外调用官方 agentskills validate 对账")
    _add_common(p_spec)
    p_spec.set_defaults(func=cmd_spec)

    p_lint = sub.add_parser(
        "lint",
        help="官方留白的补检（引用/预算/卫生/脚本契约/依赖/安全/编码）",
        description=(
            "对单个技能做官方校验器不覆盖的检查。默认只做静态检查，"
            "不执行任何脚本；--scripts 会以 `--help` 与一个非法参数调用技能自带脚本，"
            "用于实测脚本契约（存在副作用风险，故须显式开启）。"
        ),
    )
    p_lint.add_argument("path", help="技能目录（含 SKILL.md）")
    p_lint.add_argument(
        "--scripts", action="store_true",
        help="执行技能自带脚本以实测 --help/错误路径/幂等（默认关闭）",
    )
    p_lint.add_argument(
        "--script-timeout", type=float, default=10.0, metavar="秒",
        help="单个脚本的超时上限（默认 10 秒）",
    )
    _add_common(p_lint)
    p_lint.set_defaults(func=cmd_lint)

    p_evals = sub.add_parser(
        "evals",
        help="评测资产校验（官方 evals.json + 评测工作区产物）",
        description=(
            "校验官方评测约定：evals/evals.json 的形状，以及并列工作区 "
            "`<技能名>-workspace/iteration-N/eval-*/{with_skill,without_skill|old_skill}/"
            "{outputs,timing.json,grading.json}` 与 benchmark.json / feedback.json。"
            "没有评测资产时记 WARN 并说明（「没有 evals」不该和「evals 全绿」长得一样）。"
        ),
    )
    p_evals.add_argument("path", help="技能目录（含 SKILL.md）")
    p_evals.add_argument("--workspace", metavar="目录",
                         help="评测工作区（默认找并列的 <技能名>-workspace/）")
    p_evals.add_argument("--iteration", type=int, metavar="N",
                         help="只校验 iteration-N（默认校验全部）")
    _add_common(p_evals)
    p_evals.set_defaults(func=cmd_evals)

    p_disc = sub.add_parser(
        "discover",
        help="列出技能发现结果（声明式宿主适配，不做检查）",
        description=(
            "按 hosts.toml 声明的技能根发现技能，并打印每个根的命中情况。"
            "接入新宿主只需在 hosts.toml 里加一段 [hosts.<名>]，无需改代码；"
            "也可以用 --root 直接指定技能根来模拟任意布局。"
        ),
    )
    _add_discovery_options(p_disc)
    p_disc.add_argument("--show-config", action="store_true",
                        help="只打印合并后的有效配置（含来源顺序），不做发现")
    _add_common(p_disc)
    p_disc.set_defaults(func=cmd_discover)

    p_check = sub.add_parser(
        "check",
        help="对整库批量执行 spec + lint 并输出汇总",
        description=(
            "发现技能后逐个跑官方规范校验与补检，输出整库汇总报告。"
            "未发现任何技能时返回 1——「什么都没检查」不允许看起来像通过。"
        ),
    )
    _add_discovery_options(p_check)
    p_check.add_argument("--stages", choices=("all", "both", "spec", "lint", "evals", "review"),
                         default="both",
                         help="跑哪些阶段（默认 both = spec+lint，日常快查；"
                              "all = 再加评测资产与语义评审记录）")
    p_check.add_argument("--workspace", metavar="目录",
                         help="评测工作区（默认找并列的 <技能名>-workspace/）")
    p_check.add_argument("--iteration", type=int, metavar="N",
                         help="只校验 iteration-N（默认全部）")
    p_check.add_argument("--scripts", action="store_true",
                         help="执行技能自带脚本以实测脚本契约（默认关闭，存在副作用风险）")
    p_check.add_argument("--script-timeout", type=float, default=10.0, metavar="秒",
                         help="单个脚本的超时上限（默认 10 秒）")
    p_check.add_argument("--skip-review", action="store_true",
                         help="跳过语义评审记录检查（显式跳过会留痕为未覆盖项）")
    p_check.add_argument("--official", action="store_true",
                         help="额外调用官方 agentskills validate 对账")
    p_check.add_argument("--trace", action="store_true",
                         help="把报告写入配置里的中央留痕目录（trace_dir）")
    _add_common(p_check)
    p_check.set_defaults(func=cmd_check)

    p_watch = sub.add_parser(
        "watch",
        help="监听技能库变化并即时复跑（开发期即时反馈）",
        description=(
            "轮询技能库（默认 1 秒一次，纯标准库，不依赖平台专属事件 API），"
            "只复跑指纹变化的技能。默认不执行技能自带脚本——高频复跑下反复执行脚本"
            "既慢又有副作用；要实测脚本契约请手动跑 `lint --scripts`。"
        ),
    )
    _add_discovery_options(p_watch)
    p_watch.add_argument("--stages", choices=("both", "spec", "lint"), default="both",
                         help="跑哪些阶段（默认 spec+lint；评测资产不随敲代码变化，"
                              "要看评测资产请用 `check --stages evals`）")
    p_watch.add_argument("--interval", type=float, default=1.0, metavar="秒",
                         help="轮询间隔（默认 1 秒，最小 0.01）")
    p_watch.add_argument("--cycles", type=int, metavar="N",
                         help="跑 N 轮后退出（默认不限轮数）")
    p_watch.add_argument("--once", action="store_true", help="等价于 --cycles 1")
    p_watch.add_argument("--script-timeout", type=float, default=10.0, metavar="秒",
                         help="单个脚本的超时上限（默认 10 秒）")
    p_watch.add_argument("--json", action="store_true",
                         help="每轮输出一行 JSON（便于管道消费）")
    p_watch.set_defaults(func=cmd_watch)

    p_deliver = sub.add_parser(
        "deliver",
        help="交付门禁：0 FAIL 且 0 未覆盖项，并写交付记录",
        description=(
            "交付门禁比 `check` 严：FAIL 阻断；WARN 不阻断但逐条记入交付记录；"
            "SKIP 里属「未开启的可选批次/环境能力不足」的记未覆盖项（默认不阻断，"
            "`--strict` 时阻断），其余 SKIP 一律阻断。"
            "通过或未通过都会写交付记录到中央留痕目录。"
        ),
    )
    _add_discovery_options(p_deliver)
    p_deliver.add_argument("--staged", action="store_true",
                           help="只检查 git 暂存内容涉及的技能（pre-commit 用）")
    p_deliver.add_argument("--strict", action="store_true",
                           help="连「未覆盖项」也阻断（发行前跑一次）")
    p_deliver.add_argument("--stages", choices=("all", "both", "spec", "lint", "evals", "review"),
                           default="all",
                           help="跑哪些阶段（默认 all = spec+lint+evals+review：交付要考虑"
                                "该技能已有的全部资产与评审结论；both = spec+lint）")
    p_deliver.add_argument("--workspace", metavar="目录",
                           help="评测工作区（默认找并列的 <技能名>-workspace/）")
    p_deliver.add_argument("--iteration", type=int, metavar="N",
                           help="只校验 iteration-N（默认全部）")
    p_deliver.add_argument("--script-timeout", type=float, default=10.0, metavar="秒",
                           help="单个脚本的超时上限（默认 10 秒）")
    p_deliver.add_argument("--no-record", action="store_true",
                           help="不写交付记录（--json 仍会输出记录内容）")
    p_deliver.add_argument("--skip-review", action="store_true",
                           help="跳过语义评审记录检查（默认参与；显式跳过会留痕）")
    p_deliver.add_argument("--verbose", action="store_true",
                           help="把未覆盖项与待甄别项也逐条打到 stderr")
    p_deliver.add_argument("--json", action="store_true",
                           help="输出交付记录本身（含门禁结论）而非人读报告")
    p_deliver.add_argument("--out", help="报告落盘路径（.md，或按 --json 输出 .json）")
    p_deliver.add_argument("--quiet", action="store_true", help="不打印报告正文")
    p_deliver.set_defaults(func=cmd_deliver)

    p_hook = sub.add_parser(
        "hook",
        help="安装/查看 pre-commit 交付门禁",
        description=(
            "在 git 仓库里安装 pre-commit hook，提交时自动执行 "
            "`skillverify deliver --staged`。已存在他人 hook 时不改动，"
            "`--force` 会先备份再覆盖。"
        ),
    )
    hook_sub = p_hook.add_subparsers(dest="hook_action", metavar="<动作>")
    for action, help_text in (("install", "安装/更新 pre-commit hook"),
                              ("status", "查看 hook 状态")):
        p = hook_sub.add_parser(action, help=help_text)
        p.add_argument("--project", default=".", metavar="目录", help="仓库目录（默认当前目录）")
        if action == "install":
            p.add_argument("--force", action="store_true",
                           help="覆盖已存在的他人 hook（先备份为 .bak）")
            p.add_argument("--fail-closed", action="store_true",
                           help="找不到 skillverify 时阻断提交（默认故障开放，只告警）")
        p.set_defaults(func=cmd_hook)
    p_hook.set_defaults(func=cmd_hook, hook_action=None)

    p_review = sub.add_parser(
        "review",
        help="语义评审：提示词目录 / 任务包 / 回写汇总 / 独立技能包",
        description=(
            "机械检查之外的判断交给语义评审：29 条提示词，每条带 PASS/FAIL 判据与证据要求。"
            "三档执行器产出同一 schema——档 1 任意 CLI（把任务包喂给它）、"
            "档 2 会话任务包（任意 LLM 或人填写）、档 3 人工兜底（手写同一 JSON）。"
        ),
    )
    review_sub = p_review.add_subparsers(dest="review_action", metavar="<动作>")

    r_prompts = review_sub.add_parser("prompts", help="列出/渲染提示词目录（含判据）")
    r_prompts.add_argument("--family", action="append", metavar="D|W|E|R",
                           help="只显示某家族（可重复）")
    r_prompts.add_argument("--prompts", metavar="id1,id2", help="只显示指定 id")
    r_prompts.add_argument("--json", action="store_true", help="输出机读 JSON")
    r_prompts.add_argument("--out", help="落盘路径")
    r_prompts.add_argument("--quiet", action="store_true", help="不打印正文")
    r_prompts.set_defaults(func=cmd_review)

    r_pack = review_sub.add_parser("pack", help="生成语义评审任务包（含回写模板）")
    r_pack.add_argument("path", help="被评审的技能目录")
    r_pack.add_argument("--prompts", metavar="id1,id2", help="只评指定 id（默认全部 29 条）")
    r_pack.add_argument("--family", action="append", metavar="D|W|E|R",
                        help="只评某家族（可重复）")
    r_pack.add_argument("--out", metavar="目录",
                        help="任务包输出目录（默认 <技能>-review/）")
    r_pack.add_argument("--split", action="store_true",
                        help="每条提示词一个 Markdown 文件（便于一条一个 LLM 调用）")
    r_pack.set_defaults(func=cmd_review)

    r_collect = review_sub.add_parser("collect", help="校验回写并汇总进中央记录")
    r_collect.add_argument("files", nargs="*", help="回写 JSON 文件（可多个）")
    r_collect.add_argument("--dir", metavar="目录", help="汇总该目录下的全部 *.json")
    r_collect.add_argument("--skill-dir", metavar="目录",
                           help="被评审的技能目录（用于记录内容指纹与覆盖范围）")
    r_collect.add_argument("--no-store", action="store_true", help="只校验，不写中央记录")
    r_collect.add_argument("--json", action="store_true", help="输出机读 JSON")
    r_collect.add_argument("--out", help="报告落盘路径")
    r_collect.add_argument("--quiet", action="store_true", help="不打印报告正文")
    _add_discovery_options(r_collect)
    r_collect.set_defaults(func=cmd_review)

    r_status = review_sub.add_parser("status", help="查看各技能的评审记录与新鲜度")
    r_status.add_argument("--out", help="落盘路径")
    r_status.add_argument("--quiet", action="store_true", help="不打印正文")
    _add_discovery_options(r_status)
    r_status.set_defaults(func=cmd_review)

    r_skill = review_sub.add_parser("skill", help="生成「语义评审」独立技能包")
    r_skill.add_argument("--out", metavar="目录", help="输出目录（默认为当前目录）")
    r_skill.add_argument("--name", default="skillverify-review", help="技能名（默认 skillverify-review）")
    r_skill.set_defaults(func=cmd_review)

    p_review.set_defaults(func=cmd_review, review_action=None)

    return parser


def _add_discovery_options(parser: argparse.ArgumentParser) -> None:
    """discover / check 共用的发现参数（声明式宿主适配的全部开关）。"""
    parser.add_argument("--host", metavar="档名",
                        help="hosts.toml 里的宿主档（默认 default = 官方跨宿主约定）")
    parser.add_argument("--project", default=".", metavar="目录",
                        help="项目根（项目级技能根相对它解析；默认当前目录）")
    parser.add_argument("--user-home", metavar="目录",
                        help="解析 ~ 的基准目录（默认当前用户主目录）；便于隔离测试")
    parser.add_argument("--root", action="append", metavar="目录",
                        help="直接指定技能根（可重复；给出后忽略配置里的根列表）")
    parser.add_argument("--config", action="append", metavar="文件",
                        help="额外的 hosts.toml（可重复，按给定顺序覆盖）")
    parser.add_argument("--no-config", action="store_true",
                        help="忽略用户级/项目级配置，只用内置配置")


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", help="报告落盘路径（.md，或按 --json 输出 .json）")
    parser.add_argument("--json", action="store_true", help="输出机读 JSON")
    parser.add_argument("--quiet", action="store_true", help="不打印报告正文")


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
