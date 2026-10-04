"""lint.scripts —— 脚本契约检查（SCRIPT）。

官方条款（https://agentskills.io/skill-creation/using-scripts#designing-scripts-for-agentic-use）：
- "Avoid interactive prompts ... This is a hard requirement of the agent execution
  environment." → 本模块唯一以 MUST 定级的规则。
- "Document usage with `--help`"、"Write helpful error messages"、"Use structured output"、
  "Separate data from diagnostics"、"Idempotency"、"Dry-run support"、
  "Meaningful exit codes"、"Predictable output size"。

**关于"执行技能自带脚本"的风险（必须显式声明）**：
`--help` 并非绝对安全——一个没实现 `--help` 的脚本会忽略该未知参数并直接执行主体动作。
因此：
1. 默认**不执行**任何脚本，相关规则记 SKIP（覆盖有洞，计入退出码 2）；
   只有显式 `--scripts` 才执行。这是"不把用户的数据安全押在脚本写得好"上。
2. 执行时：stdin=DEVNULL、单个脚本超时、**全局时间预算**（避免 40 个脚本卡 10 分钟）、
   cwd=技能根目录（与官方"Agent 从技能根目录执行命令"的约定一致）。
3. 只调用 `--help` 与一个必然非法的参数；不做"真实运行"。

静态部分不执行任何代码：AST 判定交互式输入与防护旗标，避免旧体系
"`input(` 子串匹配同时命中 `my_input(` 与注释"的假阳性。
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
import time

from ..report import FAIL, INFO, PASS, SKIP, WARN, Result, Rule
from .inventory import FileRec
from .shared import LintContext, res, summarize

_USING = "https://agentskills.io/skill-creation/using-scripts#designing-scripts-for-agentic-use"

RULES: dict[str, Rule] = {
    "SCRIPT-001": Rule(
        "SCRIPT-001",
        "Python 脚本可通过语法解析",
        "HOUSE",
        "本项目收紧：语法都不合法的脚本无从谈起（不执行，仅 ast.parse）",
        "修掉语法错误（若是 Python 2 脚本，请移植到 Python 3）",
    ),
    "SCRIPT-002": Rule(
        "SCRIPT-002",
        "脚本不得阻塞在交互式输入上",
        "MUST",
        _USING,
        "改为命令行旗标/环境变量/stdin 读入；缺参数时打印明确错误与用法后非零退出",
    ),
    "SCRIPT-003": Rule(
        "SCRIPT-003",
        "脚本应提供 --help（静态可见的参数解析）",
        "SHOULD",
        _USING,
        "用 argparse/click/typer 等提供 `--help`，或至少实现 `-h` 分支打印用法",
    ),
    "SCRIPT-004": Rule(
        "SCRIPT-004",
        "实测 `--help` 可用（退出 0、有输出、含用法）",
        "SHOULD",
        _USING,
        "实现 `--help`：打印用途、参数、示例；退出码 0；输出走 stdout",
    ),
    "SCRIPT-005": Rule(
        "SCRIPT-005",
        "破坏性/有状态操作须有防护旗标（--dry-run 或 --confirm/--force）",
        "SHOULD",
        _USING,
        "为破坏性操作加 `--dry-run`（预览）或 `--confirm/--force`（显式确认），"
        "并在 `--help` 中说明",
    ),
    "SCRIPT-006": Rule(
        "SCRIPT-006",
        "实测非法参数：非零退出且错误信息走 stderr",
        "SHOULD",
        _USING,
        "未知参数时向 stderr 打印可诊断的错误（含期望值与收到值）并非零退出",
    ),
    "SCRIPT-007": Rule(
        "SCRIPT-007",
        "实测重复调用行为一致（幂等）",
        "SHOULD",
        _USING,
        "消除输出中的时间戳/随机序；同一输入应得到同一结果",
    ),
    "SCRIPT-008": Rule(
        "SCRIPT-008",
        "`--help` 输出简洁（≤4000 字符）",
        "HOUSE",
        "本项目收紧：官方只说 “Keep it concise”，未给数字；宿主常在 10–30K 字符处截断",
        "精简 `--help`：保留用途、参数、1–2 条示例",
    ),
}

#: Python：交互式输入（AST 判定，忽略注释与文档字符串）
_PY_INTERACTIVE_NAMES = frozenset({"input", "raw_input"})
_PY_INTERACTIVE_ATTRS = frozenset({"getpass", "prompt", "confirm", "ask", "prompt_async"})
_PY_INTERACTIVE_MODULES = frozenset(
    {"inquirer", "prompt_toolkit", "questionary", "pyinquirer", "readline"}
)

#: shell：`read -p`（提示符）或 `read -s`（无回显）才算阻塞；裸 `read` 读 stdin 是允许的
_SH_INTERACTIVE_RE = re.compile(r"\bread\s+-[a-zA-Z]*[ps]\b|\bselect\s+\w+\s+in\b")
#: JS：readline.question / inquirer.prompt / prompts(
_JS_INTERACTIVE_RE = re.compile(
    r"\breadline\s*\.\s*question\b|\binquirer\s*\.\s*prompt\b|\bprompts?\s*\("
)
#: PowerShell：Read-Host
_PS_INTERACTIVE_RE = re.compile(r"\bRead-Host\b", re.I)

#: 破坏性/有状态操作（收窄到"确实会毁数据"的形态；不含 publish/migrate 这类业务词）
DESTRUCTIVE_RES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\brm\s+-[a-zA-Z]*[rf]"), "递归/强制删除（rm -rf 类）"),
    (re.compile(r"\bshutil\s*\.\s*rmtree\b"), "递归删除目录（shutil.rmtree）"),
    (re.compile(r"\bos\s*\.\s*(?:remove|unlink|rmdir)\b"), "删除文件/目录（os.remove 类）"),
    (re.compile(r"\bRemove-Item\b[^\n]*-(?:Recurse|Force)", re.I), "递归删除（Remove-Item）"),
    (re.compile(r"\bdd\s+if="), "裸写块设备（dd if=）"),
    (re.compile(r"\bmkfs(?:\.\w+)?\b|\bformat\s+[A-Za-z]:"), "格式化文件系统"),
    (re.compile(r"\bDROP\s+(?:TABLE|DATABASE)\b|\bTRUNCATE\s+TABLE\b", re.I), "删表/清表"),
    (re.compile(r"\bgit\s+push\b[^\n]*--force\b"), "强制推送（--force）"),
    (re.compile(r"\breg\s+(?:add|delete)\b"), "写注册表（reg add/delete）"),
)

#: 防护旗标（须由参数解析器声明，不接受"文件里任意位置出现该字符串"）
GUARD_FLAGS = frozenset(
    {"--dry-run", "--dry_run", "--dryrun", "--simulate", "--check", "--confirm",
     "--force", "-f", "--yes", "-y", "--no-confirm", "--apply"}
)
_GUARD_TEXT_RE = re.compile(r"--dry[-_]run\b|--confirm\b|--force\b|--yes\b|--simulate\b")

#: 用法提示词（**刻意不含 "error:"**：`NameError:` 回溯曾被误判为用法输出）
USAGE_HINTS = ("usage:", "usage", "用法", "options:", "参数", "required", "必需",
               "the following arguments")

#: 用于"非法参数"探针的旗标（足够独特，不会与真实参数撞车）
_BOGUS_FLAG = "--skillverify-invalid-flag-9f3c"

MAX_HELP_CHARS = 4000


# --------------------------------------------------------------------------- #
# 静态分析
# --------------------------------------------------------------------------- #


def _language(rec: FileRec) -> str | None:
    """判定脚本语言：先看扩展名，再看 shebang。

    静态分析只需要"语言"，**不需要解释器存在**——若把两者绑在一起，
    一台没装 bash 的机器上所有 shell 脚本都会退化成"未能检查"，
    静态检查（交互式输入、破坏性操作）就白写了。
    """
    by_suffix = {
        ".py": "python", ".sh": "sh", ".bash": "sh", ".zsh": "sh", ".fish": "sh",
        ".js": "js", ".mjs": "js", ".cjs": "js", ".ts": "js",
        ".ps1": "ps", ".psm1": "ps",
    }.get(rec.suffix)
    if by_suffix:
        return by_suffix
    if rec.suffix == "":
        head = (rec.text or "").split("\n", 1)[0]
        if head.startswith("#!"):
            if re.search(r"\bpython3?\b", head):
                return "python"
            if re.search(r"\b(?:ba|z|fi)?sh\b", head):
                return "sh"
            if "node" in head:
                return "js"
    return None


def _interpreter_for(rec: FileRec, language: str) -> list[str] | None:
    """返回启动命令前缀（不含脚本路径）；解释器不可用返回 None。"""
    if language == "python":
        return [sys.executable]
    exe_name = {"sh": "bash", "js": "node", "ps": "pwsh"}.get(language)
    if exe_name is None:
        return None
    exe = shutil.which(exe_name)
    if exe is None:
        return None
    extra = ["-NoProfile", "-File"] if language == "ps" else []
    return [exe, *extra]


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _python_interactive_hits(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in _PY_INTERACTIVE_NAMES:
                hits.append(f"第 {node.lineno} 行 调用 {name}()")
            elif name in _PY_INTERACTIVE_ATTRS and isinstance(node.func, ast.Attribute):
                obj = _call_name(node.func.value) if isinstance(node.func.value, ast.Attribute) else (
                    node.func.value.id if isinstance(node.func.value, ast.Name) else ""
                )
                if obj.lower() in _PY_INTERACTIVE_MODULES or obj.lower() in ("click", "typer"):
                    hits.append(f"第 {node.lineno} 行 调用 {obj}.{name}()")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0].lower() in _PY_INTERACTIVE_MODULES:
                    hits.append(f"第 {node.lineno} 行 导入 {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0].lower() in _PY_INTERACTIVE_MODULES:
                hits.append(f"第 {node.lineno} 行 导入 {node.module}")
    return hits


def _text_interactive_hits(rec: FileRec, language: str) -> list[str]:
    pattern = {
        "sh": _SH_INTERACTIVE_RE,
        "js": _JS_INTERACTIVE_RE,
        "ps": _PS_INTERACTIVE_RE,
    }.get(language)
    if pattern is None:
        return []
    hits = []
    for lineno, line in enumerate((rec.text or "").split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith(("#", "//")):
            continue
        if pattern.search(line):
            hits.append(f"第 {lineno} 行: {stripped[:60]}")
    return hits


def _declared_flags(text: str) -> set[str]:
    """参数解析器声明的旗标（AST；只认 add_argument/option/argument/flag 的首个字符串参数）。"""
    flags: set[str] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return flags
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _call_name(node.func) not in {"add_argument", "option", "argument", "flag", "add_option"}:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("-"):
                flags.add(arg.value)
    return flags


def _has_guard(rec: FileRec) -> bool:
    text = rec.text or ""
    if rec.suffix == ".py":
        return bool(_declared_flags(text) & GUARD_FLAGS)
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith(("#", "//")):
            continue
        if _GUARD_TEXT_RE.search(stripped):
            return True
    return False


#: 参数解析器（**严格**口径）：只有这类解析器才会拒绝未知参数，
#: 因此它是"非法参数探针"的安全前提——手工解析 argv 的脚本会把未知参数当成
#: 位置参数照常执行，探针就变成了"真的跑一遍"。
_PARSER_RE = re.compile(
    r"\bargparse\b|\bArgumentParser\b|\bclick\b|\btyper\b|\bdocopt\b|\bfire\b"
    r"|\bgetopts\b|\bcommander\b|\byargs\b|\bminimist\b|\bprocess\.argv\b"
    r"|\bparam\s*\(|\bGet-Help\b|\$args\b"
)

#: `--help` 支持（**宽松**口径，含手工解析 argv 的写法）：只用于静态判定"看起来有没有 --help"。
#: 宽松是安全的：此处误判只会少报一条 WARN，不会执行任何东西。
_HELP_SUPPORT_RE = re.compile(
    _PARSER_RE.pattern
    + r"|\bsys\.argv\b|\bgetopt\b|\bshow_help\b|\bprint_usage\b|\busage\s*\("
    + r"|--help\b|『--help』"
)


# --------------------------------------------------------------------------- #
# 动态探测
# --------------------------------------------------------------------------- #


def _run(cmd: list[str], ctx: LintContext, timeout: float):
    return subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(ctx.root),
    )


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()[:100]
    return ""


def _probe(cmd: list[str], ctx: LintContext, timeout: float) -> tuple[int | None, str, str]:
    """执行一次探测，返回 (退出码, stdout, stderr)；超时/无法启动时退出码为 None。

    `(proc.stdout or "")` 的兜底是必需的：某些平台会给出 None，旧体系因此
    抛 AttributeError 直接中断整份报告。
    """
    try:
        proc = _run(cmd, ctx, timeout)
    except subprocess.TimeoutExpired:
        return None, "", ""
    except OSError as exc:
        return None, "", str(exc)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


# --------------------------------------------------------------------------- #
# 主检查
# --------------------------------------------------------------------------- #


def check(ctx: LintContext) -> list[Result]:
    out: list[Result] = []
    scripts = [rec for rec in ctx.inventory.files if rec.under("scripts")]
    #: 静态可分析（语言可判定，与解释器是否存在无关）
    static_targets: list[tuple[FileRec, str]] = []
    #: 可执行探测（语言可判定且解释器可用）
    analyzable: list[tuple[FileRec, list[str]]] = []
    unanalyzed: list[str] = []
    unavailable: list[str] = []
    for rec in scripts:
        if not rec.is_text:
            unanalyzed.append(f"{rec.rp}（非文本）")
            continue
        language = _language(rec)
        if language is None:
            unanalyzed.append(rec.rp)
            continue
        static_targets.append((rec, language))
        cmd = _interpreter_for(rec, language)
        if cmd is None:
            unavailable.append(rec.rp)
        else:
            # 存**完整命令**（解释器 + 脚本路径）：少了脚本路径会变成跑解释器自己的
            # `--help`，整套实测会安静地测错对象。这类错误不会抛异常，只会骗人。
            analyzable.append((rec, [*cmd, str(rec.path)]))

    # ---- SCRIPT-001：Python 语法 ----
    py_recs = [rec for rec, lang in static_targets if lang == "python"]
    py2 = [rec.rp for rec in py_recs
           if "python2" in (rec.text or "").split("\n", 1)[0]]
    syntax_bad: list[str] = []
    for rec in py_recs:
        if rec.rp in py2:
            continue
        try:
            ast.parse(rec.text or "")
        except SyntaxError as exc:
            syntax_bad.append(f"{rec.rp}:{exc.lineno}: {exc.msg}")
    if not py_recs:
        out.append(res(RULES["SCRIPT-001"], INFO, "不适用：包内无 Python 脚本"))
    elif syntax_bad:
        out.append(res(RULES["SCRIPT-001"], FAIL, summarize(syntax_bad)))
    else:
        note = f"{len(py_recs)} 个 Python 脚本语法可解析"
        if py2:
            note += f"（{summarize(py2)} 疑似 Python 2，已跳过）"
        out.append(res(RULES["SCRIPT-001"], PASS, note))

    # ---- SCRIPT-002：交互式输入 ----
    interactive: list[str] = []
    for rec, language in static_targets:
        hits = _python_interactive_hits(rec.text or "") if language == "python" \
            else _text_interactive_hits(rec, language)
        for hit in hits:
            interactive.append(f"{rec.rp} {hit}")
    if not scripts:
        out.append(res(RULES["SCRIPT-002"], INFO, "不适用：包内无 scripts/ 目录"))
    elif interactive:
        out.append(res(RULES["SCRIPT-002"], FAIL,
                       f"疑似阻塞式交互输入: {summarize(interactive)}"))
    elif unanalyzed:
        out.append(res(RULES["SCRIPT-002"], WARN,
                       f"未命中交互式输入，但无法判定语言、未能检查: {summarize(unanalyzed)}"))
    else:
        out.append(res(RULES["SCRIPT-002"], PASS, f"{len(static_targets)} 个脚本零命中"))

    # ---- SCRIPT-003：静态 --help ----
    no_help = [rec.rp for rec, _lang in static_targets
               if not _HELP_SUPPORT_RE.search(rec.text or "")]
    if not scripts:
        out.append(res(RULES["SCRIPT-003"], INFO, "不适用：包内无 scripts/ 目录"))
    elif no_help:
        out.append(res(RULES["SCRIPT-003"], WARN,
                       f"未见 --help 支持（也未见参数解析器）: {summarize(no_help)}"))
    else:
        out.append(res(RULES["SCRIPT-003"], PASS,
                       f"{len(static_targets)} 个脚本均可见 --help/参数解析线索"))

    # ---- SCRIPT-005：破坏性操作与防护旗标 ----
    destructive: list[str] = []
    unguarded: list[str] = []
    for rec, _lang in static_targets:
        text = rec.text or ""
        kinds: list[str] = []
        for pattern, label in DESTRUCTIVE_RES:
            if pattern.search(text):
                kinds.append(label)
        if not kinds:
            continue
        destructive.append(f"{rec.rp}: {'、'.join(sorted(set(kinds)))}")
        if not _has_guard(rec):
            unguarded.append(rec.rp)
    if not scripts:
        out.append(res(RULES["SCRIPT-005"], INFO, "不适用：包内无 scripts/ 目录"))
    elif not destructive:
        out.append(res(RULES["SCRIPT-005"], PASS, "未发现破坏性/有状态操作"))
    elif unguarded:
        out.append(res(RULES["SCRIPT-005"], WARN,
                       f"有破坏性操作但未见解析器声明的防护旗标: {summarize(unguarded)}"
                       f"（命中: {summarize(destructive)}）"))
    else:
        out.append(res(RULES["SCRIPT-005"], PASS,
                       f"破坏性操作均有防护旗标（{len(destructive)} 个脚本）"))

    # ---- SCRIPT-004/006/007/008：需要执行 ----
    out.extend(_dynamic(ctx, analyzable, bool(scripts), unavailable))

    return out


def _dynamic(
    ctx: LintContext,
    analyzable: list[tuple[FileRec, list[str]]],
    has_scripts: bool,
    unavailable: list[str],
) -> list[Result]:
    """实测类规则：`--help` / 非法参数 / 幂等 / 输出体量。

    SKIP 与 INFO 的口径（全模块统一纪律）：
    - 包内无脚本 → INFO（不适用，不影响退出码）；
    - 有脚本但未开启 `--scripts`、或解释器不可用 → SKIP（本项**未执行**，计入退出码 2，
      因为"没检查"绝不能看起来像"通过"）。
    """
    rids = ("SCRIPT-004", "SCRIPT-006", "SCRIPT-007", "SCRIPT-008")
    # 本族全部依赖"外部执行能力"（是否开启 --scripts、解释器是否可用、时间预算是否够）。
    # 这些 SKIP 一律 optional=True：它们不是技能自身的缺陷，交付门禁默认不因此阻断，
    # 但会在交付记录里被逐条列为"未覆盖项"；`deliver --strict` 可要求全项覆盖。
    if not has_scripts:
        return [res(RULES[rid], INFO, "不适用：包内无 scripts/ 目录") for rid in rids]
    if not analyzable:
        return [res(RULES[rid], SKIP,
                    "未执行：包内脚本均无法判定语言，或所需解释器不可用",
                    optional=True) for rid in rids]
    if not ctx.run_scripts:
        return [res(RULES[rid], SKIP,
                    f"未执行：需 --scripts 显式开启（将执行 {len(analyzable)} 个脚本的 --help）",
                    optional=True)
                for rid in rids]

    help_ok: list[str] = []
    help_bad: list[str] = []
    nohint: list[str] = []
    error_bad: list[str] = []
    error_warn: list[str] = []
    error_ok: list[str] = []
    idem_bad: list[str] = []
    verbose: list[str] = []
    skipped: list[str] = []
    deadline = time.monotonic() + ctx.script_budget_s

    for rec, cmd in analyzable:
        if time.monotonic() >= deadline:
            skipped.append(rec.rp)
            continue
        budget = max(1.0, min(ctx.script_timeout_s, deadline - time.monotonic()))

        rc, out, err = _probe([*cmd, "--help"], ctx, budget)
        if rc is None:
            help_bad.append(f"{rec.rp}: `--help` 在 {budget:.0f}s 内未返回"
                            f"（疑似阻塞在交互式输入）")
            continue
        if rc != 0:
            help_bad.append(f"{rec.rp}: `--help` 退出码 {rc}；"
                            f"{_first_line(err) or _first_line(out)}")
            continue
        if not (out + err).strip():
            help_bad.append(f"{rec.rp}: `--help` 无任何输出")
            continue
        help_ok.append(rec.rp)
        if not any(hint in (out + err).lower() for hint in USAGE_HINTS):
            nohint.append(f"{rec.rp}（输出未见用法提示: {_first_line(out)}）")
        if len(out) > MAX_HELP_CHARS:
            verbose.append(f"{rec.rp}（{len(out)} 字符）")

        # 幂等：再跑一次，逐字节比较 stdout；超时与"输出不同"必须区分开
        rc2, out2, _err2 = _probe([*cmd, "--help"], ctx, budget)
        if rc2 is None:
            idem_bad.append(f"{rec.rp}: 第二次 `--help` 超时（偶发挂起）")
        elif out2 != out:
            idem_bad.append(f"{rec.rp}: 两次 `--help` 的 stdout 不一致")

        # 非法参数探针：仅在确有参数解析器时执行（否则可能触发主体动作）
        if not _PARSER_RE.search(rec.text or ""):
            continue
        rc3, _out3, err3 = _probe([*cmd, _BOGUS_FLAG], ctx, budget)
        if rc3 is None:
            error_bad.append(f"{rec.rp}: 传入非法参数后挂起（未在 {budget:.0f}s 内退出）")
        elif rc3 == 0:
            error_warn.append(f"{rec.rp}: 非法参数被接受（退出码 0，Agent 会误以为参数生效）")
        elif not err3.strip():
            error_warn.append(f"{rec.rp}: 非法参数退出码 {rc3}，但 stderr 为空"
                              f"（诊断信息只出现在 stdout）")
        else:
            error_ok.append(rec.rp)

    results: list[Result] = []
    if help_bad:
        results.append(res(RULES["SCRIPT-004"], FAIL, summarize(help_bad)))
    elif nohint:
        results.append(res(RULES["SCRIPT-004"], WARN, summarize(nohint)))
    else:
        results.append(res(RULES["SCRIPT-004"], PASS, f"{len(help_ok)} 个脚本 `--help` 可用"))

    if error_bad:
        results.append(res(RULES["SCRIPT-006"], FAIL, summarize(error_bad)))
    elif error_warn:
        results.append(res(RULES["SCRIPT-006"], WARN, summarize(error_warn)))
    elif error_ok:
        results.append(res(RULES["SCRIPT-006"], PASS,
                           f"{len(error_ok)} 个脚本对非法参数给出非零退出与 stderr 诊断"))
    else:
        results.append(res(RULES["SCRIPT-006"], INFO, "不适用：无脚本具备参数解析器"))

    if idem_bad:
        results.append(res(RULES["SCRIPT-007"], WARN, summarize(idem_bad)))
    else:
        results.append(res(RULES["SCRIPT-007"], PASS,
                           f"{len(help_ok)} 个脚本两次 `--help` 输出一致"))

    if verbose:
        results.append(res(RULES["SCRIPT-008"], WARN, summarize(verbose)))
    else:
        results.append(res(RULES["SCRIPT-008"], PASS, "`--help` 输出体量均在阈值内"))

    if skipped or unavailable:
        note = []
        if skipped:
            note.append(f"全局时间预算 {ctx.script_budget_s:.0f}s 用尽，未探测: {summarize(skipped)}")
        if unavailable:
            note.append(f"解释器不可用，未探测: {summarize(unavailable)}")
        results.append(res(RULES["SCRIPT-004"], SKIP, "未执行：" + "；".join(note),
                           optional=True))
    return results

