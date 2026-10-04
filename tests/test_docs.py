"""文档回归测试（M6）。

**本文件把"文档是否可信"变成可执行的断言**——这是 M6 验收口径
"用一份现有技能，仅读这两份文档走完全程"的机械化实现：

1. **自包含性**：两份文档不得引用 `handoff/`、`legacy/` 或其它内部文档
   （用户要求"不用参考其他文档就能读懂"）；不得硬编码盘符路径。
2. **术语一致**：文档里出现的每个 `skillverify <子命令>` 与每个 `--旗标`
   都必须真实存在（否则文档会承诺一个不存在的功能，这比没有文档更糟）。
3. **规则 ID 一致**：文档里点名的规则 ID（`W-02`、`EVAL-000`、`DISC-001`…）
   必须在提示词目录或规则表里存在。
4. **全程可跑**：把《验证流程指南.md》里 `<!-- runnable -->` 标记的命令块抽出来，
   在一份临时技能上**逐条真跑**，断言实际退出码与文档标注的一致。
   文档里那条"由人或任意 LLM 填写模板"的步骤，测试用程序化填写代替——
   它证明的是"这一步之后的链路通"，而不是替人做判断。

用法：
    python -m tests.test_docs
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skillverify import cli, review  # noqa: E402
from skillverify.discover import RULES as DISC_RULES  # noqa: E402
from skillverify.encoding import force_utf8_stdio  # noqa: E402
from skillverify.evalx import RULES as EVAL_RULES  # noqa: E402
from skillverify.lint import RULES as LINT_RULES  # noqa: E402
from skillverify.spec import RULES as SPEC_RULES  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DOC_AUTHOR = REPO / "技能编写指南.md"
DOC_PIPELINE = REPO / "验证流程指南.md"
DOC_MANUAL = REPO / "操作手册.md"
DOC_MIGRATION = REPO / "迁移与部署指南.md"
DOC_STRUCTURE = REPO / "仓库结构说明.md"
DOC_COVERAGE = REPO / "覆盖对照-生命周期验证方案.md"

SUBCOMMAND_RE = re.compile(r"skillverify[ \t]+([a-z][a-z-]*)")
FLAG_RE = re.compile(r"(?<![\w-])--[a-z][a-z-]*")
RULE_ID_RE = re.compile(r"\b(?:D|W|E|R)-\d{2}\b|\b(?:SKILL|SPEC|REF|BUDGET|HYG|ENC|I18N|BODY|COV|"
                        r"SCRIPT|DEP|SEC|DISC|EVAL|GRAD|TIME|BENCH|WS|REV)-\d{3}\b")

#: 文档里那条"由人/LLM 完成"的步骤（测试用程序化填写代替）
FILL_MARKER = "这一步由人或任意 LLM 完成"
#: 演练块里另一种"测试动作"步骤：由测试补上评测资产
ASSET_MARKER = "这一步由你来做"

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
            code = cli.main(argv)
    except SystemExit as exc:
        # argparse 的 --version/--help 与参数错误走 SystemExit；
        # 进程内调用要把它当"退出码"接住，否则会静默中断整个套件。
        code = exc.code if isinstance(exc.code, int) else 1
        return code, out.getvalue(), err.getvalue()
    except BaseException:
        sys.stderr.write(f"[run_cli] argv={argv} 抛出异常，已捕获输出：\n"
                         f"--- stdout ---\n{out.getvalue()}\n--- stderr ---\n{err.getvalue()}\n")
        raise
    return code, out.getvalue(), err.getvalue()


def all_option_strings(parser: argparse.ArgumentParser) -> set[str]:
    """收集 CLI 里真实存在的全部旗标（argparse 没有公开遍历 API，只能读私有属性）。"""
    found: set[str] = set()
    for action in parser._actions:  # noqa: SLF001 - argparse 无公开 API
        found.update(action.option_strings)
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            for sub in action.choices.values():
                found |= all_option_strings(sub)
    return found


def all_subcommands(parser: argparse.ArgumentParser) -> set[str]:
    found: set[str] = set()
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            found |= set(action.choices)
            for sub in action.choices.values():
                found |= all_subcommands(sub)
    return found


# --------------------------------------------------------------------------- #
# 1/2/3：文档自包含、术语一致、规则 ID 一致
# --------------------------------------------------------------------------- #


def run_consistency() -> None:
    print("[test_consistency]")
    for path in (DOC_AUTHOR, DOC_PIPELINE):
        check(path.is_file() and path.stat().st_size > 2000,
              f"{path.name} 存在且有实质内容（{path.stat().st_size if path.is_file() else 0} 字节）")

    texts = {p.name: p.read_text(encoding="utf-8") for p in (DOC_AUTHOR, DOC_PIPELINE)}
    for name, text in texts.items():
        leaks = [token for token in ("handoff/", "legacy/", "会话交接", "审计报告")
                 if token in text]
        check(not leaks, f"{name} 不引用内部/会话文档（命中: {leaks}）")
        # 只把"盘符 + 真实路径片段"算硬编码；正文里提一句 `C:\`（反例）不算
        drives = re.findall(r"(?<![\w.])[A-Za-z]:[\\/]\w", text)
        check(not drives, f"{name} 不含硬编码盘符路径（命中: {drives}）")
        check("agentskills.io" in text or name == "验证流程指南.md",
              f"{name} 与官方规范的关系写清了")

    check("python -m skillverify.cli" in texts["验证流程指南.md"],
          "流程指南写了免安装直接跑 repo 的方式")

    parser = cli.build_parser()
    subs = all_subcommands(parser)
    flags = all_option_strings(parser)

    for name, text in texts.items():
        used = set(SUBCOMMAND_RE.findall(text))
        unknown = sorted(used - subs)
        check(not unknown, f"{name} 提到的子命令都真实存在（凭空出现的: {unknown}）")

    # 只有流程指南会提到 CLI 旗标；编写指南里的 --dry-run/--confirm 是**用户脚本**的旗标
    # 只校验**跟着 skillverify 出现**的旗标：文档里还有 git 的 --no-verify、
    # 用户脚本的 --dry-run、测试入口的 --dogfood，它们不是本工具的选项。
    external_flags = {"--no-verify"}
    cli_lines = [ln for ln in texts["验证流程指南.md"].splitlines() if "skillverify" in ln]
    pipeline_flags = {f for ln in cli_lines for f in FLAG_RE.findall(ln)}
    unknown_flags = sorted(f for f in pipeline_flags if f not in flags | external_flags)
    check(not unknown_flags,
          f"流程指南里跟 skillverify 一起出现的旗标都真实存在（凭空出现的: {unknown_flags}）")

    known_rules = set(SPEC_RULES) | set(LINT_RULES) | set(EVAL_RULES) | set(DISC_RULES) \
        | set(review.RULES) | {p.id for p in review.load_catalog()}
    for name, text in texts.items():
        used = set(RULE_ID_RE.findall(text))
        unknown = sorted(used - known_rules)
        check(not unknown, f"{name} 点名的规则 ID 都存在（凭空出现的: {unknown}）")

    # 30 条提示词在目录里，文档至少要让人知道怎么列出它们
    check("review prompts" in texts["验证流程指南.md"], "流程指南写了怎么看提示词目录")

    # "走完全程"的每一步都要在文档里出现，否则删掉一步测试不会响
    required = ["skillverify spec", "skillverify lint", "skillverify evals",
                "skillverify review pack", "review collect", "review material",
                "skillverify deliver", "skillverify hook install", "skillverify check",
                "review run",
                "skillverify watch", "skillverify discover", "review skill"]
    missing = [cmd for cmd in required if cmd not in texts["验证流程指南.md"]]
    check(not missing, f"流程指南覆盖全程所需命令（缺: {missing}）")

    # 编写指南要覆盖"写作期会踩的坑"，而不是只讲流程
    author_topics = ["description", "references/", "scripts/", "evals/evals.json",
                     "PEP 723", "允许 6 个字段", "UTF-8"]
    missing_topics = [t for t in author_topics if t not in texts["技能编写指南.md"]]
    check(not missing_topics, f"编写指南覆盖关键主题（缺: {missing_topics}）")


# --------------------------------------------------------------------------- #
# 项目级工作记忆（AGENTS.md）与其本地覆盖层
# --------------------------------------------------------------------------- #


def run_agent_notes() -> None:
    """`AGENTS.md` 是改这个工具的人（含 AI 协作者）读的工作约定与踩坑记录。

    它**不是**面向使用者的交付文档，所以不受"自包含"约束（可以提 legacy/），
    但它必须①存在且带关键不变量，②不含机器专属路径（否则迁移到别人的机器就是错的），
    ③其本地覆盖层 `AGENTS.local.md` 必须被 gitignore 挡住。
    """
    print("[test_agent_notes]")
    notes = REPO / "AGENTS.md"
    check(notes.is_file() and notes.stat().st_size > 2000,
          f"AGENTS.md 存在且有实质内容（{notes.stat().st_size if notes.is_file() else 0} 字节）")
    if not notes.is_file():
        return
    text = notes.read_text(encoding="utf-8")

    topics = {
        "运行时零依赖": "dependencies",
        "判定分级（SKIP=未执行）": "SKIP",
        "legacy 冻结": "冻结",
        "运行时数据随包分发": "package-data",
        "文档命令真跑": "runnable",
        "注入自测": "变异",
    }
    missing = [label for label, needle in topics.items() if needle not in text]
    check(not missing, f"AGENTS.md 覆盖关键不变量（缺: {missing}）")

    # 机器专属路径绝不能进这份（它要随仓库分发）
    drives = re.findall(r"(?<![\w.])[A-Za-z]:[\\/]\w", text)
    check(not drives, f"AGENTS.md 不含机器专属盘符路径（命中: {drives}）")
    check("AGENTS.local.md" in text, "AGENTS.md 指明机器专属信息放 AGENTS.local.md")

    ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    for entry in ("AGENTS.local.md", "CLAUDE.local.md", "handoff/", ".agents/skillverify/"):
        check(entry in ignore, f".gitignore 挡住 {entry}")


# --------------------------------------------------------------------------- #
# 4：把文档里的命令块真跑一遍
# --------------------------------------------------------------------------- #


def write_assets(skill: Path, skill_name: str, assertions: list[str]) -> None:
    """写"新手最需要照抄"的那三份评测资产（官方 evals.json + 触发查询集 + 运行记录）。

    测试用它代替《操作手册.md》里"这一步由你来做"的动作，从而把整条新手路线跑通。
    """
    (skill / "evals" / "files").mkdir(parents=True, exist_ok=True)
    (skill / "evals" / "files" / "input.csv").write_text(
        "month,revenue\n2025-01,100\n", encoding="utf-8", newline="")
    (skill / "evals" / "evals.json").write_text(json.dumps({
        "skill_name": skill_name,
        "evals": [{
            "id": 1,
            "prompt": "我有一份月度销售 CSV 在 evals/files/input.csv，找出收入最高的 3 个月。",
            "expected_output": "一份列出前 3 个高收入月份的汇总。",
            "files": ["evals/files/input.csv"],
            "assertions": assertions,
        }],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="")
    # 触发评测资产（本项目约定；与官方 evals.json 分开）：8 正 + 8 负，train 62.5%，
    # 每条 3 次运行，正例全触发、负例全不触发。
    queries = []
    for idx in range(16):
        should = idx < 8
        queries.append({
            "id": f"{'P' if should else 'N'}{idx % 8 + 1:02d}",
            "query": f"（示例查询 {idx + 1}）帮我处理一下这份销售数据",
            "should_trigger": should,
            "subset": "train" if idx < 10 else "validation",
            "category": "positive-direct" if should else "negative-near-miss",
            "rationale": "文档演练用的示例查询",
        })
    (skill / "evals" / "trigger-queryset.json").write_text(json.dumps(
        {"skill_name": skill_name, "queries": queries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="")
    runs = [{"query_id": q["id"], "run": i + 1, "loaded": bool(q["should_trigger"]),
             "evidence": f"第 {i + 1} 次运行的观察"} for q in queries for i in range(3)]
    (skill / "evals" / "trigger-runs.json").write_text(json.dumps(
        {"runs": runs}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="")


def make_fixture(tmp: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    """建一份**能过全部门禁**的演示技能（临时 git 仓库）。"""
    project = tmp / "demo-proj"
    skills_root = project / ".agents" / "skills"
    skill = skills_root / "demo-skill"
    (skill / "references").mkdir(parents=True)
    (skill / "scripts").mkdir()

    (skill / "SKILL.md").write_text(
        "---\n"
        "name: demo-skill\n"
        "description: 从 CSV 统计月度销售并输出前 3 名的报告。"
        "当用户提到销售数据、CSV 统计或月度汇总时使用。\n"
        "---\n\n"
        "# Demo Skill\n\n"
        "## 可用脚本\n\n"
        "- **`scripts/report.py`** —— 读取 CSV 并输出前 3 名（`python scripts/report.py --help`）\n\n"
        "## 步骤\n\n"
        "1. 运行 `scripts/report.py --input data.csv`；\n"
        "2. 需要列名约定时读 `references/guide.md`。\n",
        encoding="utf-8", newline="")
    (skill / "references" / "guide.md").write_text(
        "# 列名约定\n\n必须包含 month 与 revenue 两列。\n", encoding="utf-8", newline="")
    (skill / "scripts" / "report.py").write_text(
        '"""统计 CSV 月度销售。"""\n'
        "import argparse\n"
        "import sys\n\n\n"
        "def main() -> int:\n"
        '    parser = argparse.ArgumentParser(description="输出前 3 名月份。")\n'
        '    parser.add_argument("--input", help="输入 CSV 路径")\n'
        '    parser.add_argument("--dry-run", action="store_true", help="只预览不写文件")\n'
        "    parser.parse_args()\n"
        '    print("ok")\n'
        "    return 0\n\n\n"
        'if __name__ == "__main__":\n'
        "    sys.exit(main())\n",
        encoding="utf-8", newline="")
    write_assets(skill, "demo-skill", ["输出列出了 3 个月份", "每个月后面跟着收入数值"])

    # 评测工作区（官方结构）：一个 iteration、两侧 arm、可对账的 benchmark
    assertions = ["输出列出了 3 个月份", "每个月后面跟着收入数值"]
    ws = skill.parent / "demo-skill-workspace" / "iteration-1"
    for arm, flags in (("with_skill", [True, True]), ("without_skill", [False, False])):
        arm_dir = ws / "eval-top-months" / arm
        (arm_dir / "outputs").mkdir(parents=True, exist_ok=True)
        (arm_dir / "outputs" / "summary.md").write_text("结果\n", encoding="utf-8", newline="")
        n_pass = sum(1 for f in flags if f)
        (arm_dir / "grading.json").write_text(json.dumps({
            "assertion_results": [
                {"text": text, "passed": flag, "evidence": "见 outputs/summary.md"}
                for text, flag in zip(assertions, flags)],
            "summary": {"passed": n_pass, "failed": len(flags) - n_pass,
                        "total": len(flags), "pass_rate": round(n_pass / len(flags), 3)},
        }, ensure_ascii=False, indent=2), encoding="utf-8", newline="")
        (arm_dir / "timing.json").write_text(json.dumps(
            {"total_tokens": 900 if arm == "with_skill" else 400,
             "duration_ms": 1800 if arm == "with_skill" else 900}),
            encoding="utf-8", newline="")
    (ws / "benchmark.json").write_text(json.dumps({
        "run_summary": {
            "with_skill": {"pass_rate": {"mean": 1.0, "stddev": 0.0},
                           "time_seconds": {"mean": 1.8, "stddev": 0.0},
                           "tokens": {"mean": 900, "stddev": 0.0}},
            "without_skill": {"pass_rate": {"mean": 0.0, "stddev": 0.0},
                              "time_seconds": {"mean": 0.9, "stddev": 0.0},
                              "tokens": {"mean": 400, "stddev": 0.0}},
            "delta": {"pass_rate": 1.0, "time_seconds": 0.9, "tokens": 500},
        }}), encoding="utf-8", newline="")
    (skill.parent / "demo-skill-workspace" / "feedback.json").write_text(json.dumps(
        {"eval-top-months": ""}), encoding="utf-8", newline="")

    # 假的评审命令（档 1 执行器用）：读 stdin、把 JSON 打到 stdout
    runner = tmp / "fake-runner.py"
    runner.write_text("\n".join([
        "import json, re, sys",
        "payload = sys.stdin.read()",
        "m = re.search(r'提示词 (\\\\S+)：', payload)",
        "pid = m.group(1) if m else 'W-01'",
        "print(json.dumps({'prompt_id': pid, 'verdict': 'PASS',",
        "                  'evidence': '见 SKILL.md:2 的 description 字段',",
        "                  'finding': '', 'suggestion': ''}, ensure_ascii=False))",
    ]) + "\n", encoding="utf-8", newline="")

    # 盲评用的两版产物（review material --blind 的输入）
    blind = tmp / "blind-src"
    (blind / "old").mkdir(parents=True, exist_ok=True)
    (blind / "new").mkdir(parents=True, exist_ok=True)
    (blind / "old" / "summary.md").write_text("旧版输出\n", encoding="utf-8", newline="")
    (blind / "new" / "summary.md").write_text("新版输出\n", encoding="utf-8", newline="")

    home = tmp / "demo-home"
    home.mkdir()
    pack_dir = tmp / "demo-pack"
    filled = tmp / "filled-review.json"

    if shutil.which("git"):
        subprocess.run(["git", "init", "-q"], cwd=project, capture_output=True)
        subprocess.run(["git", "-C", str(project), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "-c", "user.email=t@t",
                        "-c", "user.name=t", "commit", "-q", "-m", "init"],
                       capture_output=True)
        # 提交之后改一处：这样 E-02 的 description diff 才有内容可看
        (skill / "SKILL.md").write_text(
            (skill / "SKILL.md").read_text(encoding="utf-8").replace(
                "当用户提到销售数据、CSV 统计或月度汇总时使用。",
                "当用户提到销售数据、CSV 统计、月度汇总或季度对比时使用。"),
            encoding="utf-8", newline="")
    return project, skills_root, skill, home, pack_dir, runner


def extract_runnable(text: str, which: int = 0, doc: str = "文档"
                     ) -> list[tuple[str, int | None]]:
    """取出第 `which` 个 `<!-- runnable -->` 块，解析成 [(命令, 期望退出码)]。

    块内**整行注释会被跳过**（那里正好用来写"这一步在干什么"），但带两种标记的注释行会变成
    "测试动作"步骤：`FILL_MARKER`（填写评审模板）与 `ASSET_MARKER`（补上评测资产）。
    """
    markers = [m.start() for m in re.finditer(r"<!--\s*runnable\s*-->", text)]
    if which >= len(markers):
        raise AssertionError(f"{doc} 里没有第 {which + 1} 个 <!-- runnable --> 标记的演练块")
    start = text.find("```", markers[which])
    end = text.find("```", start + 3)
    if start < 0 or end < 0:
        raise AssertionError(f"{doc} 的第 {which + 1} 个演练块没有正常闭合")
    body = text[start + 3:end]
    lines = body.splitlines()[1:]  # 去掉 ```bash 这一行
    steps: list[tuple[str, int | None]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if FILL_MARKER in stripped:
                steps.append((FILL_MARKER, None))
            elif ASSET_MARKER in stripped:
                steps.append((ASSET_MARKER, None))
            continue
        expected = None
        if "#" in stripped:
            code_part, _, comment = stripped.rpartition("#")
            match = re.search(r"(\d+)", comment)
            if match:
                expected = int(match.group(1))
            stripped = code_part.strip()
        steps.append((stripped, expected))
    return steps


def fill_template(template: Path, out: Path) -> None:
    """代替"人或任意 LLM"填写回写模板（只填结论与可定位证据）。"""
    data = json.loads(template.read_text(encoding="utf-8"))
    data["reviewer"] = "文档演练（程序化填写）"
    for item in data["results"]:
        item["verdict"] = "PASS"
        item["evidence"] = "见 SKILL.md:2 的 description 字段，含销售/CSV/月度三个关键词"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="")


def run_block(doc: Path, which: int, mapping: dict[str, str],
              actions: dict[str, "Callable[[], None]"], label: str,
              min_steps: int = 3) -> int:
    """执行某文档里的第 `which` 个演练块，逐条核对期望退出码；返回执行的命令数。"""
    steps = extract_runnable(doc.read_text(encoding="utf-8"), which, doc.name)
    check(len(steps) >= min_steps, f"{label}：演练块解析出 {len(steps)} 个步骤")
    executed = 0
    for raw, expected in steps:
        if raw in actions:
            actions[raw]()
            continue
        command = raw
        for key, value in mapping.items():
            command = command.replace(key, value)
        leftover = re.findall(r"<[^>]+>", command)
        if leftover:
            fail(f"{label}：演练步骤仍有未替换的占位符 {leftover}: {raw[:80]}")
            continue
        argv = shlex.split(command)
        if argv and argv[0] == "skillverify":
            argv = argv[1:]
        code, _out, err = run_cli(argv)
        executed += 1
        if code != expected:
            fail(f"{label}：退出码不符（期望 {expected} 实得 {code}）: {raw[:96]}"
                 f"\n         stderr: {err.strip()[:200]}")
        else:
            ok(f"{label}：exit={code}: {raw[:72]}")
    check(executed == len([s for s in steps if s[0] not in actions]),
          f"{label}：{executed} 条命令全部执行")
    return executed


def rich_mapping(tmp: Path, project: Path, skills_root: Path, skill: Path, home: Path,
                 pack_dir: Path, runner: Path, prefix: str = "demo") -> dict[str, str]:
    """完整夹具用的占位符映射（《验证流程指南.md》《操作手册.md》《迁移与部署指南.md》共用）。"""
    return {
        "<技能目录>": str(skill),
        "<技能根>": str(skills_root),
        "<项目>": str(project),
        "<用户主目录>": str(home),
        "<任务包目录>": str(pack_dir),
        "<技能名>": skill.name,
        "<回写文件>": str(tmp / f"{prefix}-filled-review.json"),
        "<材料目录>": str(tmp / f"{prefix}-material"),
        "<独立技能目录>": str(tmp / f"{prefix}-emitted"),
        "<盲评旧版>": str(tmp / "blind-src" / "old"),
        "<盲评新版>": str(tmp / "blind-src" / "new"),
        "<回写目录>": str(tmp / f"{prefix}-cli-writeback"),
        # --runner 收的是**一个命令字符串**：这里不能嵌双引号，
        # 否则演练行 `--runner "<评审命令>"` 经 shlex 拆分会碎成多个参数。
        "<评审命令>": f"{sys.executable} {runner}",
    }


def run_walkthrough(tmp: Path) -> None:
    print("[test_walkthrough]")
    project, skills_root, skill, home, pack_dir, runner = make_fixture(tmp)
    template = pack_dir / "demo-skill-review-template.json"
    mapping = rich_mapping(tmp, project, skills_root, skill, home, pack_dir, runner)
    filled = Path(mapping["<回写文件>"])
    check('"' not in mapping["<评审命令>"],
          "评审命令不含双引号（含空格路径需改用别的引用方式，见文档说明）")

    def fill() -> None:
        check(template.is_file(), "演练到「填写模板」这一步时任务包已生成")
        if template.is_file():
            fill_template(template, filled)

    run_block(DOC_PIPELINE, 0, mapping, {FILL_MARKER: fill}, "流程指南")
    record = project / ".agents" / "skillverify" / "review" / "demo-skill.json"
    check(record.is_file(), "演练后中央留痕里有评审记录")
    if record.is_file():
        stored = json.loads(record.read_text(encoding="utf-8"))
        check(stored["verdict"] == "pass" and stored["reviewers"] == ["文档演练（程序化填写）"],
              "评审记录结论为 pass 且带签署")
    hook = project / ".git" / "hooks" / "pre-commit"
    check(hook.is_file() and "skillverify-hook" in hook.read_text(encoding="utf-8"),
          "演练最后真的装上了 pre-commit hook")


# --------------------------------------------------------------------------- #
# 《操作手册.md》《迁移与部署指南.md》：命令真跑
# --------------------------------------------------------------------------- #

#: 手册路线 A 用的"新建技能"——只有 SKILL.md，没有任何评测资产
NEW_SKILL_MD = (
    "---\n"
    "name: my-new-skill\n"
    "description: 从 CSV 统计月度销售并输出前 3 名报告。"
    "当用户提到销售数据、CSV 统计或月度汇总时使用。\n"
    "---\n\n"
    "# My New Skill\n\n"
    "## 步骤\n\n"
    "1. 读取用户给的 CSV；\n"
    "2. 输出前 3 名月份的汇总。\n"
)


def run_manual(tmp: Path) -> None:
    """《操作手册.md》两条路线：① 新建技能（最小夹具）② 已有技能（完整夹具）。"""
    print("[test_manual]")
    # ---- 路线 A：新建技能 ----
    base_a = tmp / "manual-a"
    project = base_a / "proj"
    skills_root = project / ".agents" / "skills"
    skill = skills_root / "my-new-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(NEW_SKILL_MD, encoding="utf-8", newline="")
    home = base_a / "home"
    home.mkdir(parents=True)
    pack_dir = base_a / "review-pack"
    if shutil.which("git"):  # hook install 需要 git 仓库
        subprocess.run(["git", "init", "-q"], cwd=project, capture_output=True)
        subprocess.run(["git", "-C", str(project), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "-m", "init"], capture_output=True)

    mapping_a = {
        "<技能目录>": str(skill),
        "<技能根>": str(skills_root),
        "<项目>": str(project),
        "<用户主目录>": str(home),
        "<任务包目录>": str(pack_dir),
        "<技能名>": "my-new-skill",
        "<回写文件>": str(base_a / "filled-review.json"),
    }
    template_a = pack_dir / "my-new-skill-review-template.json"
    filled_a = Path(mapping_a["<回写文件>"])

    def add_assets() -> None:
        check(not (skill / "evals" / "evals.json").is_file(),
              "手册路线 A：补资产之前，技能确实还没有评测资产")
        write_assets(skill, "my-new-skill", ["输出列出了 3 个月份", "每个月后面跟着收入数值"])
        check((skill / "evals" / "evals.json").is_file(), "手册路线 A：补上了评测资产")

    def fill_a() -> None:
        check(template_a.is_file(), "手册路线 A：填写模板时任务包已生成")
        if template_a.is_file():
            fill_template(template_a, filled_a)

    run_block(DOC_MANUAL, 0, mapping_a,
              {ASSET_MARKER: add_assets, FILL_MARKER: fill_a}, "操作手册·路线A")
    record_a = project / ".agents" / "skillverify" / "review" / "my-new-skill.json"
    check(record_a.is_file(), "手册路线 A：评审结论落进了中央记录")

    # ---- 路线 B：已存在的技能（完整夹具）----
    base_b = tmp / "manual-b"
    project_b, skills_b, skill_b, home_b, pack_b, runner_b = make_fixture(base_b)
    mapping_b = rich_mapping(base_b, project_b, skills_b, skill_b, home_b, pack_b, runner_b,
                             prefix="manual-b")
    template_b = pack_b / f"{skill_b.name}-review-template.json"
    filled_b = Path(mapping_b["<回写文件>"])

    def fill_b() -> None:
        check(template_b.is_file(), "手册路线 B：填写模板时任务包已生成")
        if template_b.is_file():
            fill_template(template_b, filled_b)

    run_block(DOC_MANUAL, 1, mapping_b, {FILL_MARKER: fill_b}, "操作手册·路线B")
    record_b = project_b / ".agents" / "skillverify" / "review" / f"{skill_b.name}.json"
    check(record_b.is_file(), "手册路线 B：评审结论落进了中央记录")


def run_migration(tmp: Path) -> None:
    """《迁移与部署指南.md》的"新机器自检 + 第一次验收"块。"""
    print("[test_migration]")
    base = tmp / "migrate"
    project, skills_root, skill, home, pack_dir, runner = make_fixture(base)
    mapping = rich_mapping(base, project, skills_root, skill, home, pack_dir, runner,
                           prefix="migrate")
    run_block(DOC_MIGRATION, 0, mapping, {}, "迁移指南")
    check(base.joinpath("demo-proj").is_dir(), "迁移指南的演练确实作用在独立夹具上")


def run_new_docs() -> None:
    """新文档的通用约束：命令与旗标必须真实存在，且不得含机器专属路径。"""
    print("[test_new_docs]")
    parser = cli.build_parser()
    subs = all_subcommands(parser)
    flags = all_option_strings(parser)
    external_flags = {"--no-verify"}          # git 自己的旗标
    docs = (DOC_MANUAL, DOC_MIGRATION, DOC_STRUCTURE, DOC_COVERAGE)
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        check(len(text) > 1500, f"{doc.name} 存在且有实质内容（{len(text)} 字符）")
        drives = re.findall(r"(?<![\w.])[A-Za-z]:[\\/]\w", text)
        check(not drives, f"{doc.name} 不含机器专属盘符路径（命中: {drives}）")

    # CI 样例也在"文档"之列：它引用的命令必须真实存在，否则流水线会在别人机器上红
    workflow = REPO / ".github" / "workflows" / "skillverify.yml"
    check(workflow.is_file(), "CI 样例存在（.github/workflows/skillverify.yml）")
    if workflow.is_file():
        wf = workflow.read_text(encoding="utf-8")
        used = set(SUBCOMMAND_RE.findall(wf))
        unknown = sorted(used - subs)
        check(not unknown, f"CI 样例提到的子命令都真实存在（凭空出现的: {unknown}）")
        wf_flags = {f for ln in wf.splitlines() if "skillverify" in ln for f in FLAG_RE.findall(ln)}
        unknown_wf = sorted(f for f in wf_flags if f not in flags | external_flags)
        check(not unknown_wf, f"CI 样例提到的旗标都真实存在（凭空出现的: {unknown_wf}）")
        check("deliver" in used and "--strict" in wf, "CI 样例跑交付门禁且用 --strict")
        check("tests.run_all" in wf, "CI 样例包含工具自身的回归套件 job")

    for doc in (DOC_MANUAL, DOC_MIGRATION):
        text = doc.read_text(encoding="utf-8")
        used = set(SUBCOMMAND_RE.findall(text))
        unknown = sorted(used - subs)
        check(not unknown, f"{doc.name} 提到的子命令都真实存在（凭空出现的: {unknown}）")
        cli_lines = [ln for ln in text.splitlines() if "skillverify" in ln]
        used_flags = {f for ln in cli_lines for f in FLAG_RE.findall(ln)}
        unknown_flags = sorted(f for f in used_flags if f not in flags | external_flags)
        check(not unknown_flags,
              f"{doc.name} 里跟 skillverify 一起出现的旗标都真实存在（凭空出现的: {unknown_flags}）")

    manual = DOC_MANUAL.read_text(encoding="utf-8")
    check(manual.count("<!-- runnable -->") == 2, "操作手册有两条可执行路线")
    for needle, label in (("新建", "新建技能"), ("已经存在", "已有技能"), ("PASS", "判定说明"),
                          ("SKIP", "未执行的语义"), ("退出码", "退出码说明"),
                          ("reviewer", "评审签署"), ("evidence", "证据要求")):
        check(needle in manual, f"操作手册覆盖「{label}」")
    migration = DOC_MIGRATION.read_text(encoding="utf-8")
    for needle, label in (("必须带", "必须带什么"), ("不要带", "不要带什么"),
                          ("pip install", "安装方式"), ("hosts.toml", "宿主适配"),
                          ("常见问题", "排障")):
        check(needle in migration, f"迁移指南覆盖「{label}」")


def run_structure_doc() -> None:
    """《仓库结构说明.md》必须与真实文件树一致（既不列不存在的，也不漏代码文件）。"""
    print("[test_structure]")
    text = DOC_STRUCTURE.read_text(encoding="utf-8")
    listed = {p for p in re.findall(r"`((?:skillverify|tests)/[A-Za-z0-9_./-]+)`", text)
              if "*" not in p}
    missing = sorted(p for p in listed if not (REPO / p).exists())
    check(not missing, f"结构说明列出的路径都真实存在（不存在: {missing}）")

    on_disk = {str(p.relative_to(REPO)).replace("\\", "/")
               for p in list((REPO / "skillverify").rglob("*.py"))
               + list((REPO / "tests").glob("*.py"))
               + list((REPO / "skillverify" / "data").glob("*"))
               if "__pycache__" not in p.parts}
    not_listed = sorted(on_disk - listed)
    check(not not_listed, f"所有代码与数据文件都在结构说明里列出（漏: {not_listed}）")
    check(len(on_disk) >= 30, f"结构说明覆盖 {len(on_disk)} 个代码/数据文件")

    # 套件表里不许再写死断言数：它必然漂移（实测漂过 54→130、98→97）。
    counted = [ln for ln in text.splitlines()
               if re.match(r"^\| `tests/\S+` \|.*\|\s*\d+\s*\|$", ln)]
    check(not counted, f"结构说明不写死断言数（命中 {len(counted)} 行）")
    check("tests.run_all" in text, "结构说明指向 run_all 作为断言数的来源")

    for name in ("pyproject.toml", ".gitattributes", ".gitignore", "AGENTS.md",
                 "AGENTS.local.md"):
        check(f"`{name}`" in text, f"结构说明提到根文件 {name}")
    for dirname in ("skillverify/cli/", "skillverify/lint/", "skillverify/data/", "tests/"):
        check(dirname in text, f"结构说明展开了 {dirname}")


# --------------------------------------------------------------------------- #
# 反向：文档里的期望退出码不是随手写的
# --------------------------------------------------------------------------- #


def run_doc_semantics(tmp: Path) -> None:
    """确认文档里那几条"非零退出码"的解释与实际行为一致。"""
    print("[test_doc_semantics]")
    project, skills_root, skill, home, _pack, _runner = make_fixture(tmp / "sem")

    code, _out, err = run_cli(["lint", str(skill)])
    check(code == 2 and "--scripts" in err,
          f"未加 --scripts 时 lint 返回 2 且说明原因（实得 {code}）")

    bare = tmp / "sem-bare" / ".agents" / "skills" / "bare-skill"
    bare.mkdir(parents=True)
    (bare / "SKILL.md").write_text(
        "---\nname: bare-skill\ndescription: 一个用来演示「没有评测资产」的技能。\n---\n\n# B\n",
        encoding="utf-8", newline="")
    code, _out, _err = run_cli(["evals", str(bare)])
    check(code == 2, f"无评测资产时 evals 返回 2（文档如此声明；实得 {code}）")

    empty = tmp / "sem-empty"
    (empty / ".agents" / "skills").mkdir(parents=True)
    code, _out, err = run_cli(["check", "--project", str(empty), "--user-home", str(home),
                               "--root", str(empty / ".agents" / "skills"), "--quiet"])
    check(code == 1 and "未发现任何技能" in err,
          f"空库 check 返回 1（文档如此声明；实得 {code}）")

    code, _out, _err = run_cli(["discover", "--show-config"])
    check(code == 0, "discover --show-config 可用（文档排障一节用到它）")


def main() -> int:
    force_utf8_stdio()
    parser = argparse.ArgumentParser(description="skillverify 文档回归测试")
    parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="sv_test_docs_"))
    try:
        run_consistency()
        run_agent_notes()
        run_new_docs()
        run_structure_doc()
        run_walkthrough(tmp)
        run_manual(tmp)
        run_migration(tmp)
        run_doc_semantics(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = len(_passed) + len(_failed)
    print(f"\n结果: PASS={len(_passed)} FAIL={len(_failed)} 合计={total}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
