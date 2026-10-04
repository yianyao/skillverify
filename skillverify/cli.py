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
from .encoding import force_utf8_stdio, write_text
from .report import FAIL, Report
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

    return parser


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", help="报告落盘路径（.md）")
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
