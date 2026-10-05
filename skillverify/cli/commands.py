"""cli.commands —— 各子命令的实现。

分三组：单技能（spec/lint/evals）、整库（discover/check/watch/deliver）、
流程（review/hook）。共用工具在 `common.py`。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import __version__
from ..tmpdir import new_temp_dir
from ..deliver import (
    apply_waivers,
    attach_previous,
    build_record,
    evaluate,
    filter_staged_skills,
    hook_status,
    install_hook,
    is_git_repo,
    write_record,
)
from ..discover import Config, ConfigError, Discovery, render_config
from ..encoding import write_text
from ..evalx import check_evals
from ..lint import lint_skill
from ..audit import audit_markdown, audit_skill, write_record as write_audit_record
from ..library import run_library
from ..material import build_materials
from ..mount import load as load_mount_config
from ..mount import run_mount
from ..runner import run_runner
from ..runner import validate as runner_validate
from ..report import Result, FAIL, PASS, SKIP, WARN, LibraryEntry, LibraryReport, Report
from ..report import merge
from ..review import (
    CatalogError,
    build_pack,
    collect as collect_reviews,
    emit_skill,
    load_catalog,
    render_prompts_md,
    select_prompts,
    status as review_status,
    write_record as write_review_record,
)
from ..spec import check_spec, find_official_cli, run_official
from ..trigger import check_trigger
from ..watch import run_watch
from .common import (
    PROG,
    _emit,
    _load_discovery,
    _looks_like_workspace,
    _stage_results,
    _status_exit,
    _wants,
)

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
                f"请对具体技能目录运行，或用 `{PROG} check --root {path}` 对整库批量运行"
                f"（`{PROG} discover` 可先看会发现哪些技能）。",
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
        # 用 Result.optional 判断"未开启的可选批次"，**不要**匹配证据文本：
        # deliver 侧本来就只按 status/optional 判定，文本匹配是另一种耦合。
        skipped = [r for r in report.results if r.status == SKIP and r.optional]
        if skipped:
            print(
                f"提示：{len(skipped)} 项脚本契约实测未执行（因此退出码为 2 而非 0）；"
                f"加 --scripts 开启（注意：会以 `--help` 调用技能自带脚本）。",
                file=sys.stderr,
            )
    return report.exit_code()



def _render_discovery(discovery: Discovery, project: Path, config: Config) -> str:
    """发现结果的人读视图：技能根命中情况 + 技能清单 + 库级结果。"""
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
        lines.append(
            f"| {info.label} | {info.scope} | {'是' if info.exists else '否'} "
            f"| {info.found} | {info.note or ''} |"
        )
    lines += ["", "## 技能", ""]
    if discovery.skills:
        lines += ["| 技能 | 作用域 | 路径 |", "|---|---|---|"]
        for ref in discovery.skills:
            lines.append(f"| {ref.name} | {ref.scope} | {ref.path} |")
    else:
        lines.append("（无）")
    if discovery.results:
        lines += ["", "## 库级结果", "",
                  "| 规则 | 级别 | 判定 | 说明 | 证据 |", "|---|---|---|---|---|"]
        for res in discovery.results:
            lines.append(f"| {res.rid} | {res.level} | {res.status} "
                         f"| {res.title} | {res.evidence} |")
    lines += [
        "",
        "> 未发现技能不等于通过：`discover` 只报告发现了什么，"
        "`check` 才会对发现的技能逐条判定。",
        "",
    ]
    return "\n".join(lines)


def cmd_mount(args: argparse.Namespace) -> int:
    """挂载前置检查（**仓库侧**）：可发现性 / name·description 可读 / 同名冲突 / fail-loud。

    明确**不**验证宿主注册表与真实触发匹配——本工具没有宿主 API，命令说明里写清楚了。
    """
    project = Path(args.project).expanduser()
    user_home = Path(args.user_home).expanduser() if args.user_home else Path.home()
    try:
        config = load_mount_config(
            project, user_home,
            extra_configs=[Path(c) for c in (args.config or [])],
            no_config=args.no_config,
        )
    except ConfigError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    report = run_mount(project, user_home, config, host=args.host, skill=args.skill,
                       all_hosts=args.all_hosts)
    report.meta["工具版本"] = f"{PROG} {__version__}"
    _emit(report, args)
    return report.exit_code()


def _run_with(workdir: Path, command: str, timeout_s: float) -> tuple[int, str]:
    """在技能目录里跑使用者给的命令（委托执行）。返回（退出码, 附注）。

    命令字符串按 shell 语义执行：它通常指向官方评测器或宿主提供的入口脚本。
    **本工具不猜测官方评测器的参数**——参数由使用者给出，这里只负责执行、限时、报退出码。
    """
    import subprocess

    try:
        proc = subprocess.run(command, shell=True, cwd=str(workdir),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return 124, f"超时（>{timeout_s:.0f}s）：{command}"
    except OSError as exc:
        return 127, f"无法执行: {exc}"
    detail = (proc.stdout or "")[-800:] + (proc.stderr or "")[-800:]
    return proc.returncode, detail.strip()


def cmd_audit(args: argparse.Namespace) -> int:
    """外来技能审计：把各阶段结论组合成一张"要不要用它"的单子，并留下指纹。

    明确不做的事写在命令说明与审计单里：不跑技能脚本、不模拟触发、不做信任分级。
    """
    target = Path(args.target).expanduser()
    if not target.is_absolute():
        target = (Path(args.project).expanduser() / target).resolve()
    if not target.exists():
        # 也可以直接给"已发现的技能名"
        try:
            discovery, _config = _load_discovery(args)
        except ConfigError as exc:
            print(f"配置错误: {exc}", file=sys.stderr)
            return 1
        hit = next((ref for ref in discovery.skills if ref.name == args.target), None)
        if hit is None:
            print(f"FAIL: 找不到技能或目录: {args.target}", file=sys.stderr)
            return 1
        target = Path(hit.path)

    others: list[str] = []
    try:
        discovery, _config = _load_discovery(args)
        others = [ref.name for ref in discovery.skills if Path(ref.path) != target]
        trace_dir = discovery.trace_dir or (Path(args.project).expanduser() / ".agents" / "skillverify")
    except ConfigError:
        trace_dir = Path(args.project).expanduser() / ".agents" / "skillverify"

    try:
        report, record = audit_skill(target, trace_dir=trace_dir, others=others,
                                     run_scripts=args.scripts)
    except OSError as exc:
        print(f"FAIL: 无法审计 {target}: {exc}", file=sys.stderr)
        return 1

    if args.out or args.record:
        write_audit_record(trace_dir, record, audit_markdown(record, report))
        print(f"审计单已落盘: {trace_dir / 'audit' / (record.skill + '.md')}", file=sys.stderr)
    _emit(report, args)
    # `--json` 时**不能**再打印审计单正文：stdout 只放一种东西（否则机读输出被污染）
    if not args.quiet and not args.out and not args.json:
        print(audit_markdown(record, report))
    return report.exit_code()


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

    for res in run_library(discovery.skills, budget=args.metadata_budget,
                           overlap_threshold=args.desc_overlap):
        discovery.results.append(res)
        if res.status == WARN:
            print(f"  {res.rid} {res.evidence}", file=sys.stderr)

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
    # 库级检查（多技能组合视角）：元数据预算 + 描述词面重叠。
    # 放这里而不是只放 discover：`check` 才是日常与 CI 的入口。
    for res in run_library(discovery.skills, budget=args.metadata_budget,
                           overlap_threshold=args.desc_overlap):
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
            print(f"报告已落盘: {path}", file=sys.stderr)

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
            if r.status == SKIP and r.optional
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
    # §6.1 的豁免通道：显式、有理由、落盘。没有它，误报只有"改到过"一条路。
    if getattr(args, "accept", None):
        if not getattr(args, "because", None):
            print("FAIL: --accept 必须配 --because <理由>——豁免要留下书面理由，会写进交付记录",
                  file=sys.stderr)
            return 1
        gate, waived = apply_waivers(gate, args.accept, args.because)
        for item in waived:
            print(f"  已豁免 {item}", file=sys.stderr)
    markdown = library.to_markdown()
    command = f"{PROG} deliver {'--staged ' if args.staged else ''}" \
              f"--project {args.project}" + (" --strict" if args.strict else "")
    record = build_record(
        library, gate, project=project, scope=scope, command=command.strip(),
        discovery=discovery, unrelated=unrelated,
    )
    # V29：与上一轮比对必须在**输出之前**完成，否则 CI 读到的记录里没有对比
    previous = attach_previous(discovery.trace_dir, record) if discovery.trace_dir else {}

    # `--json` 输出的是**交付记录本身**（含门禁结论）：门禁命令的机读输出必须带结论，
    # 否则 CI 只能靠退出码猜。markdown 与人读报告仍是分开的两种渲染。
    text = json.dumps(record, ensure_ascii=False, indent=2) if args.json else markdown

    print(f"{'PASS' if gate.passed else 'FAIL'}: {gate.summary()}", file=sys.stderr)
    if previous.get("found"):
        marks = "⚠ 退步" if previous.get("worse") else ("改善" if previous.get("better") else "持平")
        print(f"  与上一轮相比：{marks} —— {previous.get('note', '')}", file=sys.stderr)
    for item in previous.get("history_rewritten") or []:
        print(f"  ⚠ 工作区历史被改动：{item}"
              f"（同名 iteration 的内容与上一轮不同——旧结果被覆盖了）", file=sys.stderr)
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
        print(f"报告已落盘: {args.out}", file=sys.stderr)
    written = write_record(discovery.trace_dir, record, markdown)
    print("交付记录: " + "；".join(str(p) for p in written), file=sys.stderr)
    return 0 if gate.passed else 1


def cmd_evals(args: argparse.Namespace) -> int:
    """校验技能的评测资产（evals.json 与评测工作区产物）。"""
    path = Path(args.path)
    if not path.exists():
        print(f"FAIL: 路径不存在: {path}", file=sys.stderr)
        return 1
    # 两类资产一起查：官方输出质量评测（evals/evals.json）与触发评测
    # （evals/trigger-queryset.json）。官方口径只覆盖前者，后者是本项目的约定。
    official = check_evals(
        path,
        workspace=Path(args.workspace) if args.workspace else None,
        iteration=args.iteration,
    )
    trigger = check_trigger(path)
    report = merge([official, trigger], target=str(path), stage="evals")
    report.meta["工具版本"] = f"{PROG} {__version__}"
    report.meta["官方口径"] = "agentskills.io/skill-creation/evaluating-skills"
    report.meta["执行层"] = (
        "本工具**不执行**评测（不发网络、不调模型）。要真跑一遍，请用官方 skill-creator "
        "或你的宿主；也可以把它的入口命令交给 `--run-with` 委托执行，本工具执行后照旧校验产物"
    )

    # 委托执行：命令由使用者给出（本工具不猜官方评测器的参数）
    if args.run_with:
        from ..evalx import RUN_HINT

        code, note = _run_with(path, args.run_with, args.run_timeout)
        report.meta["委托执行"] = f"{args.run_with}（退出码 {code}）"
        if code != 0:
            # 失败**绝不**写成"不适用/通过"：这是既有约定（review run 同样处理）
            print(f"FAIL: 委托执行的命令失败（退出码 {code}）：{args.run_with}", file=sys.stderr)
            if note:
                print(note, file=sys.stderr)
            report.add(Result("RUN-101", "委托执行的评测命令正常结束", FAIL, "HOUSE",
                              f"命令 {args.run_with!r} 退出码 {code}", RUN_HINT))
            _emit(report, args)
            return report.exit_code()
        print(f"委托执行完成（退出码 0）：{args.run_with}", file=sys.stderr)
        # 执行之后**重新校验产物**：这正是本工具的定位（校验官方执行层的产物）
        refreshed = merge([check_evals(
            path,
            workspace=Path(args.workspace) if args.workspace else None,
            iteration=args.iteration,
        ), check_trigger(path)], target=str(path), stage="evals")
        report = refreshed
        report.meta["工具版本"] = f"{PROG} {__version__}"
        report.meta["执行层"] = f"已委托执行：{args.run_with}（退出码 0）；以下为执行后的产物校验"
        report.meta["委托执行"] = args.run_with
    report.meta.update({k: v for k, v in official.meta.items() if k not in report.meta})
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
            print(f"已落盘: {args.out}", file=sys.stderr)
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
            print(f"已生成: {path}", file=sys.stderr)
        print(f"\n下一步：把任务包交给任意 LLM 或人填写，"
              f"然后 `{PROG} review collect <填好的模板>`。", file=sys.stderr)
        return 0

    if action == "skill":
        out = Path(args.out) if args.out else Path(".")
        for path in emit_skill(out, catalog, name=args.name):
            print(f"已生成: {path}", file=sys.stderr)
        print("\n该技能包自包含（SKILL.md + references/ + assets/），"
              "放到任意宿主的技能目录即可加载。", file=sys.stderr)
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
            print(f"报告已落盘: {args.out}", file=sys.stderr)
        if not args.quiet:
            print(text if text.endswith("\n") else text + "\n")

        if not args.no_store:
            assert discovery.trace_dir is not None
            latest = write_review_record(discovery.trace_dir / "review", record)
            print(f"评审记录: {latest}", file=sys.stderr)
        print(f"结论: {record['verdict']}（阻断项 {len(record['blocking_fails'])}；"
              f"未覆盖 {len(record['uncovered_prompts'])}）", file=sys.stderr)
        return report.exit_code()

    if action == "run":
        skill_dir = Path(args.path)
        if not skill_dir.is_dir():
            print(f"FAIL: 技能目录不存在: {skill_dir}", file=sys.stderr)
            return 1
        if not args.runner:
            print("FAIL: 档 1 执行器需要 `--runner <命令>`（该命令会读到提示词并以 JSON 回结论）。",
                  file=sys.stderr)
            return 1
        prompt_ids = [x.strip() for x in args.prompts.split(",") if x.strip()] if args.prompts else None
        report, writeback = run_runner(
            skill_dir,
            args.runner,
            prompt_ids=prompt_ids,
            timeout_s=args.timeout,
            allow_partial=args.allow_partial,
        )
        # 与档 2/档 3 走**同一条**校验
        checks = runner_validate(writeback)
        for res in checks:
            report.add(res)
        report.meta["工具版本"] = f"{PROG} {__version__}"

        out_dir = Path(args.out) if args.out else None
        target = None
        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
            target = out_dir / f"{skill_dir.name}-review-cli.json"
            target.write_text(json.dumps(writeback, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8", newline="")
            print(f"已生成: {target}", file=sys.stderr)

        if args.collect:
            if target is None:
                # 只作 collect 的输入载体；临时目录不可用属环境故障，明确报错而不是静默跳过留痕。
                try:
                    scratch = new_temp_dir(prefix="sv_runner_")
                except OSError as exc:
                    print(f"FAIL: 临时目录不可用（{exc}），无法在 --collect 下转存回写 JSON。",
                          file=sys.stderr)
                    return 1
                target = scratch / f"{skill_dir.name}-review-cli.json"
                target.write_text(json.dumps(writeback, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8", newline="")
            collect_report, record = collect_reviews(
                [target], load_catalog(), skill_dir=skill_dir,
                expected_ids=writeback.get("prompt_ids"))
            for res in collect_report.results:
                report.add(res)
            discovery, _config = _load_discovery(args)
            assert discovery.trace_dir is not None
            latest = write_review_record(discovery.trace_dir / "review", record)
            print(f"评审记录: {latest}", file=sys.stderr)
            print(f"结论: {record['verdict']}（阻断项 {len(record['blocking_fails'])}；"
                  f"未覆盖 {len(record['uncovered_prompts'])}）", file=sys.stderr)

        text = report.to_json() if args.json else report.to_markdown()
        if not args.quiet:
            print(text if text.endswith("\n") else text + "\n")
        # runner 失败时报告里已有 FAIL（除非 --allow-partial），退出码随之非零
        return report.exit_code()

    if action == "material":
        skill_dir = Path(args.path)
        if not skill_dir.is_dir():
            print(f"FAIL: 技能目录不存在: {skill_dir}", file=sys.stderr)
            return 1
        blind = (Path(args.blind[0]), Path(args.blind[1])) if args.blind else (None, None)
        report, written = build_materials(
            skill_dir,
            out_dir=Path(args.out) if args.out else None,
            workspace=Path(args.workspace) if args.workspace else None,
            diff_base=args.diff_base,
            blind=blind,
            blind_seed=args.blind_seed,
        )
        report.meta["工具版本"] = f"{PROG} {__version__}"
        for path in written:
            print(f"已生成: {path}", file=sys.stderr)
        text = report.to_json() if args.json else report.to_markdown()
        if not args.quiet:
            print(text if text.endswith("\n") else text + "\n")
        skipped = [r for r in report.results if r.status == SKIP]
        if skipped:
            print(f"提示：{len(skipped)} 项材料未能生成（因此在退出码里记 SKIP=2）；"
                  f"逐条原因见报告。", file=sys.stderr)
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
            print(f"已落盘: {args.out}", file=sys.stderr)
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

