"""cli —— skillverify 命令行入口。

约定（全族统一，便于任何宿主/CI 消费）：
- 退出码：0=全 PASS；1=有 FAIL；2=无 FAIL 但有 WARN/SKIP。
- 报告默认打到 stdout；`--out` 可落盘；`--json` 输出机读结构。
- 参数错误一律 stderr + 用法 + 退出码 1（不撞 WARN 码 2）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .discover import Config, ConfigError, Discovery, load_config, discover_skills, render_config
from .encoding import force_utf8_stdio, write_text
from .lint import lint_skill
from .report import FAIL, PASS, SKIP, WARN, LibraryEntry, LibraryReport, Report, Result
from .spec import check_spec, find_official_cli, run_official

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

    for ref in discovery.skills:
        results: list[Result] = []
        if args.stages in ("both", "spec"):
            _doc, rep = check_spec(ref.path)
            results.extend(rep.results)
            if args.official:
                results.append(run_official(ref.path, official))
        if args.stages in ("both", "lint"):
            rep = lint_skill(
                ref.path, run_scripts=args.scripts, script_timeout_s=args.script_timeout
            )
            results.extend(rep.results)
        merged = Report(target=str(ref.path), stage="check")
        merged.results = results
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

    if args.stages == "both" and not args.scripts:
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
    p_check.add_argument("--stages", choices=("both", "spec", "lint"), default="both",
                         help="只跑某一阶段（默认两者都跑）")
    p_check.add_argument("--scripts", action="store_true",
                         help="执行技能自带脚本以实测脚本契约（默认关闭，存在副作用风险）")
    p_check.add_argument("--script-timeout", type=float, default=10.0, metavar="秒",
                         help="单个脚本的超时上限（默认 10 秒）")
    p_check.add_argument("--official", action="store_true",
                         help="额外调用官方 agentskills validate 对账")
    p_check.add_argument("--trace", action="store_true",
                         help="把报告写入配置里的中央留痕目录（trace_dir）")
    _add_common(p_check)
    p_check.set_defaults(func=cmd_check)

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
