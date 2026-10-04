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

SUBCOMMAND_RE = re.compile(r"skillverify\s+([a-z][a-z-]*)")
FLAG_RE = re.compile(r"(?<![\w-])--[a-z][a-z-]*")
RULE_ID_RE = re.compile(r"\b(?:D|W|E|R)-\d{2}\b|\b(?:SKILL|SPEC|REF|BUDGET|HYG|ENC|I18N|BODY|COV|"
                        r"SCRIPT|DEP|SEC|DISC|EVAL|GRAD|TIME|BENCH|WS|REV)-\d{3}\b")

#: 文档里那条"由人/LLM 完成"的步骤（测试用程序化填写代替）
FILL_MARKER = "这一步由人或任意 LLM 完成"

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
                "skillverify review pack", "review collect", "skillverify deliver",
                "skillverify hook install", "skillverify check", "skillverify watch",
                "skillverify discover", "review skill"]
    missing = [cmd for cmd in required if cmd not in texts["验证流程指南.md"]]
    check(not missing, f"流程指南覆盖全程所需命令（缺: {missing}）")

    # 编写指南要覆盖"写作期会踩的坑"，而不是只讲流程
    author_topics = ["description", "references/", "scripts/", "evals/evals.json",
                     "PEP 723", "允许 6 个字段", "UTF-8"]
    missing_topics = [t for t in author_topics if t not in texts["技能编写指南.md"]]
    check(not missing_topics, f"编写指南覆盖关键主题（缺: {missing_topics}）")


# --------------------------------------------------------------------------- #
# 4：把文档里的命令块真跑一遍
# --------------------------------------------------------------------------- #


def make_fixture(tmp: Path) -> tuple[Path, Path, Path, Path, Path]:
    """建一份**能过全部门禁**的演示技能（临时 git 仓库）。"""
    project = tmp / "demo-proj"
    skills_root = project / ".agents" / "skills"
    skill = skills_root / "demo-skill"
    (skill / "references").mkdir(parents=True)
    (skill / "scripts").mkdir()
    (skill / "evals" / "files").mkdir(parents=True)

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
    (skill / "evals" / "files" / "input.csv").write_text(
        "month,revenue\n2025-01,100\n", encoding="utf-8", newline="")
    (skill / "evals" / "evals.json").write_text(json.dumps({
        "skill_name": "demo-skill",
        "evals": [{
            "id": 1,
            "prompt": "我有一份月度销售 CSV 在 evals/files/input.csv，找出收入最高的 3 个月。",
            "expected_output": "一份列出前 3 个高收入月份的汇总。",
            "files": ["evals/files/input.csv"],
            "assertions": ["输出列出了 3 个月份", "每个月后面跟着收入数值"],
        }],
    }, ensure_ascii=False, indent=2), encoding="utf-8", newline="")

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
    return project, skills_root, skill, home, pack_dir


def extract_runnable(text: str) -> list[tuple[str, int | None]]:
    """取出 `<!-- runnable -->` 标记后的第一个代码块，解析成 [(命令, 期望退出码)]。"""
    marker = text.find("<!-- runnable -->")
    if marker < 0:
        raise AssertionError("《验证流程指南.md》里没有 <!-- runnable --> 标记的演练块")
    start = text.find("```", marker)
    end = text.find("```", start + 3)
    if start < 0 or end < 0:
        raise AssertionError("演练块没有正常闭合")
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


def run_walkthrough(tmp: Path) -> None:
    print("[test_walkthrough]")
    project, skills_root, skill, home, pack_dir = make_fixture(tmp)
    steps = extract_runnable(DOC_PIPELINE.read_text(encoding="utf-8"))
    check(len(steps) >= 12, f"演练块解析出 {len(steps)} 个步骤")

    template = pack_dir / "demo-skill-review-template.json"
    filled = tmp / "filled-review.json"
    mapping = {
        "<技能目录>": str(skill),
        "<技能根>": str(skills_root),
        "<项目>": str(project),
        "<用户主目录>": str(home),
        "<任务包目录>": str(pack_dir),
        "<技能名>": "demo-skill",
        "<回写文件>": str(filled),
    }

    executed = 0
    for raw, expected in steps:
        if raw == FILL_MARKER:
            check(template.is_file(), "演练到「填写模板」这一步时任务包已生成")
            if template.is_file():
                fill_template(template, filled)
            continue
        command = raw
        for key, value in mapping.items():
            command = command.replace(key, value)
        leftover = re.findall(r"<[^>]+>", command)
        if leftover:
            fail(f"演练步骤仍有未替换的占位符 {leftover}: {raw[:80]}")
            continue
        argv = shlex.split(command)
        if argv and argv[0] == "skillverify":
            argv = argv[1:]
        code, _out, err = run_cli(argv)
        executed += 1
        if code != expected:
            fail(f"演练步骤退出码不符（期望 {expected} 实得 {code}）: {raw[:96]}"
                 f"\n         stderr: {err.strip()[:200]}")
        else:
            ok(f"演练步骤 exit={code}: {raw[:80]}")

    check(executed == len([s for s in steps if s[0] != FILL_MARKER]),
          f"演练块 {executed} 条命令全部执行")
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
# 反向：文档里的期望退出码不是随手写的
# --------------------------------------------------------------------------- #


def run_doc_semantics(tmp: Path) -> None:
    """确认文档里那几条"非零退出码"的解释与实际行为一致。"""
    print("[test_doc_semantics]")
    project, skills_root, skill, home, _pack = make_fixture(tmp / "sem")

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
        run_walkthrough(tmp)
        run_doc_semantics(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = len(_passed) + len(_failed)
    print(f"\n结果: PASS={len(_passed)} FAIL={len(_failed)} 合计={total}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
