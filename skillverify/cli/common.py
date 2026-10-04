"""cli.common —— 各命令共用的参数、渲染与阶段调度。

拆出来的理由：`cli.py` 曾是一个 900+ 行的单文件，9 个子命令与它们共用的工具函数混在一起。
这里只放**共用**的部分；具体命令在 `commands.py`，装配在 `__init__.py`。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..discover import Discovery, Config, discover_skills, load_config
from ..encoding import write_text
from ..evalx import check_evals
from ..lint import lint_skill
from ..report import FAIL, SKIP, WARN, Report, Result
from ..review import check_review
from ..spec import check_spec, run_official
from ..trigger import check_trigger

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
        # 触发评测资产与官方输出质量评测同属"评测资产"阶段（官方口径只覆盖前者）
        results.extend(check_trigger(skill_path).results)
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

