"""lint.deps —— 依赖与脚本自带依赖声明的检查（DEP）。

官方条款（https://agentskills.io/skill-creation/using-scripts）：
- "Self-contained scripts ... declares its own dependencies inline. The agent can run
  the script with a single command — no separate manifest file or install step required."
- "Pin versions with PEP 508 specifiers: `"beautifulsoup4>=4.12,<5"`."
- specification#scripts："Be self-contained or clearly document dependencies"
  ——**这是本模块 DEP-002 采用 WARN 而非 FAIL 的依据**：官方给了"或在文档中说明"
  这条路，只查内联声明会把合规写法误判为违规。

实现要点（逐条对应旧体系的坑）：
- 版本比较分三档：pinned（`==`/精确 `@1.2.3`）＞ranged（`>=`/`^`/`~`/`*`/`latest` 等
  dist-tag）＞unpinned；`latest` 这类 dist-tag **按 ranged 计**（它定义上就会漂移）。
- 取值旗标（`-r requirements.txt`、`npx -p pkg`）会**吃掉**下一个 token，否则
  `requirements.txt` 会被当成包名重复报错。
- `go run .` / `go run main.go` 属本地形态，不是未钉版本的第三方包。
- import 名与包名常常不同（`bs4`→beautifulsoup4、`PIL`→Pillow），因此"未在声明中
  找到该 import"只记 WARN，并附常用别名映射，绝不因改名而 FAIL。
- PEP 723 代码块用 `tokenize` 定位**真正的注释**行，避免旧体系"文档字符串里写
  一行 `# /// script` 就被当成声明"的漏洞。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import ast
import re
import sys
import tokenize
from io import StringIO

from ..report import FAIL, INFO, PASS, WARN, Result, Rule
from .inventory import FileRec
from .shared import LintContext, res, summarize, strip_inline_comment

_USING_SCRIPTS = "https://agentskills.io/skill-creation/using-scripts"
_SPEC_SCRIPTS = "https://agentskills.io/specification#scripts"

RULES: dict[str, Rule] = {
    "DEP-001": Rule(
        "DEP-001",
        "一次性命令/包调用须钉版本",
        "SHOULD",
        _USING_SCRIPTS + "#one-off-commands",
        "补版本：`npx eslint@9.0.0`、`uvx ruff@0.8.0`、`pip install 'black==24.10.0'`；"
        "代码里必须精确钉住，文档里的示例至少不要用 latest",
    ),
    "DEP-002": Rule(
        "DEP-002",
        "脚本的第三方依赖须内联声明或在文档中说明",
        "SHOULD",
        _SPEC_SCRIPTS,
        "在脚本头部加 PEP 723 块（`# /// script` … `# ///`，含 dependencies），"
        "或在 SKILL.md 写明需要预先安装哪些包",
    ),
    "DEP-003": Rule(
        "DEP-003",
        "包内不得出现独立依赖清单（会引入安装步骤）",
        "SHOULD",
        _USING_SCRIPTS + "#self-contained-scripts",
        "把依赖移入脚本的 PEP 723 块并删除清单；技能应能被单条命令直接跑起来",
    ),
    "DEP-004": Rule(
        "DEP-004",
        "内联声明的依赖须钉版本并声明 requires-python",
        "SHOULD",
        _USING_SCRIPTS + "#self-contained-scripts",
        "把 `\"pkg\"` 改为 `\"pkg>=1.2,<2\"`，并补 `requires-python = \">=3.10\"`",
    ),
    "DEP-005": Rule(
        "DEP-005",
        "非 Python 脚本的内联依赖（只认明确形态）也要钉版本",
        "HOUSE",
        "官方未规定非 Python 生态的内联依赖口径（本项目收紧）："
        "「自包含脚本」的要求跨语言成立，但各生态机制不同，故只认明确形态、只记 WARN",
        "Deno：写 `npm:pkg@1.2.3` / `jsr:@scope/pkg@1.2.3`，别只写 `npm:pkg`；"
        "Bun 等把版本写进 import 说明符的写法：`\"pkg@1.2.3\"`；"
        "Ruby 的 `bundler/inline`：`gem \"名字\", \"1.2.3\"`，别只写 `gem \"名字\"`",
    ),
}

#: 会消费下一个 token 的取值旗标（否则旗标值会被当成包名）
VALUE_FLAGS = frozenset(
    {"-r", "--requirement", "-c", "--constraint", "-e", "--editable", "-i",
     "--index-url", "--extra-index-url", "-t", "--target", "--prefix", "-p",
     "--package", "-o", "--output", "-f", "--find-links", "--index", "--python",
     "--with-requirements", "--from", "--registry"}
)

#: 包调用形态：(名称, 正则)
RUNNER_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("npx/bunx/uvx/pipx", re.compile(r"\b(?:npx|bunx|uvx|pipx)\b")),
    ("pip install", re.compile(r"\bpip3?\s+install\b")),
    ("uv", re.compile(r"\buv\s+(?:pip\s+install|tool\s+run|run\s+--with)\b")),
    ("deno", re.compile(r"\bdeno\s+(?:run|install)\b")),
    ("go run", re.compile(r"\bgo\s+run\b")),
)

#: dist-tag：定义上会漂移，按 ranged 计
DIST_TAGS = frozenset({"latest", "next", "beta", "canary", "rc", "alpha", "dev", "nightly"})

#: 独立依赖清单：FAIL 集（会引入安装步骤）
MANIFEST_FAIL = frozenset(
    {"package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
     "requirements.txt", "pipfile", "pipfile.lock", "uv.lock", "poetry.lock",
     "gemfile", "gemfile.lock", "go.mod", "go.sum", "cargo.toml", "cargo.lock",
     "environment.yml", "conda.yml", "pdm.lock"}
)
#: WARN 集（可能只是工具配置）
MANIFEST_WARN = frozenset({"pyproject.toml", "setup.py", "setup.cfg", "tox.ini"})

#: 非 Python 脚本里**写在代码中**的依赖声明形态（生态名, 说明, 正则）。
#:
#: 为什么只认这几种：各生态的内联声明机制差别很大，穷举等于编造；
#: 认不出来的形态一律**不报**（宁缺勿滥），认出来的形态只给一条可机械判定的事实：
#: 版本钉没钉住。裸包名（`import x from "lodash"`）**不算**内联声明——那由 package.json
#: 之类的清单管理，把它报成"未钉版本"会给每个 Node 脚本刷一行噪音。
INLINE_DEP_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Deno：`import ... from "npm:pkg@1"` / `jsr:@scope/pkg@1`（动态 import 也算）
    ("deno", re.compile(r"""(?:from|import)\s*\(?\s*["']((?:npm|jsr):[^"']+)["']""")),
    # Bun 等把版本写进 import 说明符的写法：`from "pkg@1.2.3"` / `require("pkg@1.2.3")`
    ("bun", re.compile(r"""(?:from|require\s*\()\s*["']([^"']+@[^"']+)["']""")),
)
#: Ruby 的 `bundler/inline`（脚本自带一份内联 Gemfile）
RUBY_INLINE_RE = re.compile(r"""require\s+["']bundler/inline["']""")
#: `gem "名字"` 或 `gem "名字", "约束"`
RUBY_GEM_RE = re.compile(r"""^\s*gem\s+["']([^"']+)["']\s*(?:,\s*(.+?))?\s*$""")

#: import 名 → 发行包名（只收常见且无歧义的；其余靠 WARN + 人工确认）
IMPORT_ALIASES: dict[str, str] = {
    "pil": "pillow", "image": "pillow", "bs4": "beautifulsoup4", "yaml": "pyyaml",
    "cv2": "opencv-python", "sklearn": "scikit-learn", "docx": "python-docx",
    "pptx": "python-pptx", "fitz": "pymupdf", "serial": "pyserial",
    "crypto": "pycryptodome", "dateutil": "python-dateutil", "dotenv": "python-dotenv",
    "gi": "pygobject", "attr": "attrs", "jwt": "pyjwt", "magic": "python-magic",
    "multipart": "python-multipart", "pkg_resources": "setuptools",
    "win32com": "pywin32", "win32api": "pywin32", "win32con": "pywin32",
    "usb": "pyusb", "slugify": "python-slugify", "openpyxl": "openpyxl",
}

STDLIB = frozenset(getattr(sys, "stdlib_module_names", frozenset()))


def normalize_name(name: str) -> str:
    """PEP 503 归一化：`Foo_Bar` 与 `foo-bar` 视为同一个包。"""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def dep_name(spec: str) -> str:
    """从依赖规格里取出**包名**（丢掉版本、范围、extras、marker、@ 前缀）。

    必须只归一化包名：旧式写法若把 `requests==2.31.0` 整体归一化，会得到
    `requests==2-31-0`，于是"声明了 requests"反而被判成"import 未在声明中"。
    """
    text = re.sub(r"^(?:npm|jsr):", "", spec.strip().strip("'\""))
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9_.\-]*", text)
    return normalize_name(match.group(0)) if match else ""


# --------------------------------------------------------------------------- #
# 一次命令里的包规格
# --------------------------------------------------------------------------- #


def _spec_token(tokens: list[str], start: int) -> str | None:
    """从 start 起找第一个非旗标 token，并跳过取值旗标的值。"""
    i = start
    while i < len(tokens):
        token = tokens[i]
        if token in VALUE_FLAGS:
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        return token
    return None


#: 包规格的合理形态（ASCII 字母/数字/@ 开头，允许 @ . _ / + -）
_SPEC_OK_RE = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9@._/+\-]*$")


def plausible_spec(spec: str) -> bool:
    """该 token 是否像"包规格"。

    **为什么必须有这道闸**：中文正文里出现"运行器选择（uvx/pipx/npx/bunx/deno/go run）
    是否与目标环境匹配"这类叙述时，正则会把它后面的整段中文当成"未钉版本的包名"报出来
    ——dogfood 实测确实产生了这样一条假 WARN。非 ASCII 的 token 一律不算包规格。
    """
    text = spec.strip().strip("'\"")
    if not text or not text.isascii():
        return False
    if not _SPEC_OK_RE.match(text):
        return False
    return ".." not in text


def classify_spec(spec: str, runner: str) -> tuple[str, str]:
    """返回 (档位, 名称)：pinned / ranged / unpinned / local。"""
    text = spec.strip().strip("'\"")
    if not text:
        return "local", ""
    if runner == "go run":
        if text.endswith(".go") or text.startswith(("./", "../", "/")) or text in (".", ".."):
            return "local", text
    if runner == "deno":
        if not text.startswith(("npm:", "jsr:")):
            return "local", text
        text = re.sub(r"^(?:npm|jsr):", "", text)
    if text.startswith(("./", "../", "/")) or text in (".", ".."):
        return "local", text

    if "@" in text:
        name, _, ver = text.rpartition("@")
        if not name:  # 形如 `@scope/pkg` 无版本
            return "unpinned", text
        if not ver:
            return "unpinned", name
        if ver.lower() in DIST_TAGS or ver.startswith(("^", "~", ">", "<", "*", "=")):
            return "ranged", name
        return "pinned", name

    for op in ("===", "==", ">=", "<=", "!=", "~=", ">", "<"):
        if op in text:
            name, _, ver = text.partition(op)
            if not ver.strip():
                return "unpinned", name
            return ("pinned" if op in ("==", "===") else "ranged"), name
    if text.endswith("@"):
        return "unpinned", text[:-1]
    return "unpinned", text


def _runner_hits(rec: FileRec) -> list[tuple[str, str, str, int]]:
    """返回 [(runner 名, 档位, 包规格, 行号)]。"""
    out: list[tuple[str, str, str, int]] = []
    for lineno, line in enumerate((rec.text or "").split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        code = strip_inline_comment(line)
        for runner, pattern in RUNNER_RES:
            for match in pattern.finditer(code):
                tokens = code[match.end():].split()
                spec = _spec_token(tokens, 0)
                if spec is None or not plausible_spec(spec):
                    continue
                kind, name = classify_spec(spec, runner)
                if kind == "local":
                    continue
                out.append((runner, kind, spec, lineno))
    return out


# --------------------------------------------------------------------------- #
# PEP 723
# --------------------------------------------------------------------------- #


def _comment_lines(text: str) -> list[tuple[int, str]]:
    """用 tokenize 取真正的注释行（避免文档字符串中伪装成注释的文本）。"""
    out: list[tuple[int, str]] = []
    try:
        for tok in tokenize.generate_tokens(StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                out.append((tok.start[0], tok.string))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []
    return out


def pep723_block(text: str) -> str | None:
    """返回 PEP 723 `# /// script` 块的原始内容（含各行），无则 None。"""
    comments = _comment_lines(text)
    start = None
    for idx, (lineno, value) in enumerate(comments):
        if re.match(r"^\s*#\s*///\s*script\s*$", value):
            start = idx
            break
    if start is None:
        return None
    lines = []
    for _lineno, value in comments[start + 1:]:
        if re.match(r"^\s*#\s*///\s*$", value):
            return "\n".join(lines)
        lines.append(re.sub(r"^\s*#\s?", "", value))
    return None  # 未闭合：按"没有声明"处理，由 SCRIPT 族报未闭合


def _toml_array(block: str, key: str) -> list[str] | None:
    """从块里取 `key = [ ... ]` 的字符串项（受限 TOML 子集，见模块 docstring）。"""
    pattern = re.compile(rf"^\s*{key}\s*=\s*\[(.*?)\]", re.S | re.M)
    match = pattern.search(block)
    if not match:
        return None
    inner = match.group(1)
    items = re.findall(r"['\"]([^'\"]+)['\"]", inner)
    return [i.strip() for i in items if i.strip()]


def _toml_scalar(block: str, key: str) -> str | None:
    match = re.search(rf"^\s*{key}\s*=\s*['\"]([^'\"]+)['\"]", block, re.M)
    return match.group(1).strip() if match else None


# --------------------------------------------------------------------------- #
# import 分析
# --------------------------------------------------------------------------- #


def third_party_imports(rec: FileRec) -> list[str]:
    """Python 脚本里疑似第三方的顶层 import（已排除标准库与同目录本地模块）。"""
    text = rec.text or ""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # 相对导入 = 本地
                continue
            if node.module:
                names.add(node.module.split(".")[0])
    local_names = {p.stem for p in rec.path.parent.glob("*.py")}
    local_names |= {p.name for p in rec.path.parent.iterdir() if p.is_dir()}
    return sorted(
        n for n in names
        if n not in STDLIB and n not in local_names and not n.startswith("_")
    )


def _declared_in_docs(ctx: LintContext, names: list[str]) -> list[str]:
    """哪些 import 名在 SKILL.md / frontmatter 里被提到（官方允许的"文档说明"路径）。"""
    haystack = (ctx.text + "\n" + ctx.meta_text()).lower()
    found = []
    for name in names:
        candidates = {name.lower(), IMPORT_ALIASES.get(name.lower(), "")}
        if any(c and re.search(rf"(?<![\w-]){re.escape(c)}(?![\w-])", haystack) for c in candidates):
            found.append(name)
    return found


# --------------------------------------------------------------------------- #
# 主检查
# --------------------------------------------------------------------------- #


@dataclass
class DepFacts:
    """依赖层的**结构化事实**（规则与 audit 共用）。"""

    third_party: list[str]     # 出现过的第三方 import 名
    undeclared: list[str]      # 未内联声明、也未在文档说明
    mismatched: list[str]      # import 与 PEP 723 声明不一致
    inline: list[str]          # 非 Python 脚本里写死的内联依赖（`生态 包@版本`）


@dataclass
class InlineDep:
    """一处非 Python 内联依赖。"""

    ecosystem: str             # deno / bun / ruby
    spec: str                  # 原始写法（如 `npm:chalk@5.3.0`）
    kind: str                  # pinned / ranged / unpinned
    where: str                 # `<相对路径>:<行号>`


def _ruby_inline_deps(rec: FileRec) -> list[InlineDep]:
    """`bundler/inline` 文件里的 `gem "x"` 行。

    限制（写清楚，不假装更聪明）：只按**文件粒度**识别——文件里出现 `require "bundler/inline"`
    就把全文的 `gem` 行都算进来，不解析 `gemfile do … end` 的块边界。
    这类脚本通常整个文件就是一份内联 Gemfile，粒度足够；真出现例外也只是多报一行 WARN。
    """
    out: list[InlineDep] = []
    text = rec.text or ""
    if not RUBY_INLINE_RE.search(text):
        return out
    for lineno, line in enumerate(text.split("\n"), 1):
        match = RUBY_GEM_RE.match(strip_inline_comment(line))
        if not match:
            continue
        name, constraint = match.group(1), (match.group(2) or "").strip().strip("'\"")
        if not constraint:
            out.append(InlineDep("ruby", f'gem "{name}"', "unpinned", f"{rec.rp}:{lineno}"))
        elif re.match(r"^=\s*\d", constraint):
            out.append(InlineDep("ruby", f'gem "{name}", {constraint}', "pinned",
                                 f"{rec.rp}:{lineno}"))
        elif re.match(r"^\d", constraint):
            # `gem "x", "1.2.3"` = 精确版本
            out.append(InlineDep("ruby", f'gem "{name}", {constraint}', "pinned",
                                 f"{rec.rp}:{lineno}"))
        else:
            out.append(InlineDep("ruby", f'gem "{name}", {constraint}', "ranged",
                                 f"{rec.rp}:{lineno}"))
    return out


def scan_inline_deps(ctx: LintContext) -> list[InlineDep]:
    """扫非 Python 脚本里**写在代码中**的依赖声明（只认明确形态）。

    **唯一实现处**：`DEP-005` 与 `audit` 的能力清单都调它。
    """
    found: list[InlineDep] = []
    for rec in ctx.inventory.texts:
        if rec.suffix == ".py":
            continue
        for lineno, line in enumerate((rec.text or "").split("\n"), 1):
            code = strip_inline_comment(line)
            if not code.strip():
                continue
            for ecosystem, pattern in INLINE_DEP_RES:
                for match in pattern.finditer(code):
                    spec = match.group(1)
                    if ecosystem == "bun":
                        # Deno 的形态（含 `npm:` 前缀）已由上面那条处理；
                        # 相对路径 / 绝对路径 / URL / Node 内置模块都不是依赖声明。
                        if spec.startswith(("npm:", "jsr:", "./", "../", "/", "node:")) \
                                or "://" in spec:
                            continue
                    kind, _name = classify_spec(spec, ecosystem)
                    if kind == "local":
                        continue
                    found.append(InlineDep(ecosystem, spec, kind, f"{rec.rp}:{lineno}"))
        if rec.suffix == ".rb":
            found.extend(_ruby_inline_deps(rec))
    return found


@dataclass
class ThirdPartyScan:
    """DEP-002/DEP-004 需要的全部中间结果（规则内部用）。"""

    imports: list[str] = field(default_factory=list)
    undeclared: list[str] = field(default_factory=list)
    mismatched: list[str] = field(default_factory=list)
    declared: list[str] = field(default_factory=list)
    missing_python: list[str] = field(default_factory=list)
    dep_recs: int = 0
    blocks: int = 0


def scan_third_party(ctx: LintContext) -> ThirdPartyScan:
    """扫一遍 Python 脚本的第三方依赖与内联声明。

    **唯一实现处**：DEP-002/DEP-004 与 audit 的能力清单都调它——早先 audit 从
    DEP-002 的**证据文本**里抠依赖名，措辞一改就静默解析出垃圾。
    """
    scan = ThirdPartyScan()
    for rec in (r for r in ctx.inventory.texts if r.suffix == ".py"):
        imports = third_party_imports(rec)
        if not imports:
            continue
        scan.dep_recs += 1
        scan.imports.extend(imports)
        block = pep723_block(rec.text or "")
        if block is None:
            documented = _declared_in_docs(ctx, imports)
            if len(documented) < len(imports):
                rest = [n for n in imports if n not in documented]
                scan.undeclared.append(f"{rec.rp}: {', '.join(rest)}")
            continue
        scan.blocks += 1
        declared = _toml_array(block, "dependencies") or []
        normalized = {dep_name(d) for d in declared if dep_name(d)}
        scan.declared.extend(declared)
        for name in imports:
            alias = IMPORT_ALIASES.get(name.lower(), name)
            if normalize_name(name) not in normalized and normalize_name(alias) not in normalized:
                scan.mismatched.append(f"{rec.rp}: import {name} 未出现在 dependencies")
        if declared and _toml_scalar(block, "requires-python") is None:
            scan.missing_python.append(rec.rp)
    return scan


def facts(ctx: LintContext) -> DepFacts:
    scan = scan_third_party(ctx)
    return DepFacts(third_party=sorted(set(scan.imports)),
                    undeclared=list(scan.undeclared), mismatched=list(scan.mismatched),
                    inline=sorted({f"{d.ecosystem} {d.spec}" for d in scan_inline_deps(ctx)}))


def check(ctx: LintContext) -> list[Result]:
    out: list[Result] = []
    code_recs = [r for r in ctx.inventory.texts if r.is_code]
    py_recs = [r for r in ctx.inventory.texts if r.suffix == ".py"]

    # ---- DEP-001：一次性命令的版本钉住 ----
    fails: list[str] = []
    warns: list[str] = []
    total_calls = 0
    for rec in ctx.inventory.texts:
        for runner, kind, spec, lineno in _runner_hits(rec):
            total_calls += 1
            if kind == "ranged":
                warns.append(f"{rec.rp}:{lineno} {runner} {spec}（范围/dist-tag，会漂移）")
            elif kind == "unpinned":
                item = f"{rec.rp}:{lineno} {runner} {spec}（未钉版本）"
                (fails if rec.is_code else warns).append(item)
    if total_calls == 0:
        out.append(res(RULES["DEP-001"], INFO,
                       "不适用：未发现一次性包调用（npx/uvx/pipx/pip install/uv/deno/go run）"))
    elif fails:
        out.append(res(RULES["DEP-001"], FAIL, f"代码中的未钉版本调用: {summarize(fails)}"))
    else:
        detail = ("文档中的未钉版本调用: " + summarize(warns)) if warns else f"{total_calls} 处调用均已钉版本"
        out.append(res(RULES["DEP-001"], WARN if warns else PASS, detail))

    # ---- DEP-002 / DEP-004：内联声明 ----
    scan = scan_third_party(ctx)
    undeclared = scan.undeclared
    mismatched = scan.mismatched
    blocks = scan.blocks
    dep_recs = scan.dep_recs
    dep_specifiers = scan.declared
    missing_python = scan.missing_python

    if dep_recs == 0:
        out.append(res(RULES["DEP-002"], INFO, "不适用：无 Python 脚本导入第三方模块"))
    elif undeclared:
        out.append(res(RULES["DEP-002"], WARN,
                       f"未内联声明且未在文档说明: {summarize(undeclared)}"))
    elif mismatched:
        out.append(res(RULES["DEP-002"], WARN,
                       f"import 与声明不一致（包名可能不同，须人工确认）: {summarize(mismatched)}"))
    else:
        out.append(res(RULES["DEP-002"], PASS,
                       f"{dep_recs} 个脚本的第三方依赖均有内联声明或文档说明"))

    # ---- DEP-004：声明本身的钉版本与 requires-python ----
    if blocks == 0:
        out.append(res(RULES["DEP-004"], INFO, "不适用：无 PEP 723 内联声明"))
    else:
        loose = [s for s in dep_specifiers if classify_spec(s, "pip")[0] != "pinned"]
        parts = []
        if loose:
            parts.append(f"未精确钉版本: {summarize(loose)}")
        if missing_python:
            parts.append(f"有依赖但未声明 requires-python: {summarize(missing_python)}")
        if parts:
            out.append(res(RULES["DEP-004"], WARN, "；".join(parts)))
        else:
            out.append(res(RULES["DEP-004"], PASS,
                           f"{len(dep_specifiers)} 个声明依赖均已精确钉版本"))

    # ---- DEP-003：独立依赖清单 ----
    hard: list[str] = []
    soft: list[str] = []
    for rec in ctx.inventory.files:
        name = rec.rel.name.lower()
        is_req = name.startswith("requirements") and name.endswith(".txt")
        if not (is_req or name in MANIFEST_FAIL or name in MANIFEST_WARN):
            continue
        item = rec.rp
        if rec.under("references", "assets", "evals"):
            soft.append(f"{item}（样例/素材目录，须人工确认）")
        elif is_req or name in MANIFEST_FAIL:
            hard.append(item)
        else:
            soft.append(item)
    if hard:
        out.append(res(RULES["DEP-003"], FAIL, f"包内独立依赖清单: {summarize(hard)}"))
    elif soft:
        out.append(res(RULES["DEP-003"], WARN, f"疑似依赖清单（人工确认）: {summarize(soft)}"))
    else:
        out.append(res(RULES["DEP-003"], PASS, "无独立依赖清单"))

    # ---- DEP-005：非 Python 的内联依赖（只认明确形态） ----
    inline = scan_inline_deps(ctx)
    if not inline:
        out.append(res(RULES["DEP-005"], INFO,
                       "不适用：未发现非 Python 的内联依赖形态"
                       "（Deno 的 npm:/jsr: 说明符、import 说明符里带版本、Ruby bundler/inline）"))
    else:
        loose = [d for d in inline if d.kind != "pinned"]
        if loose:
            out.append(res(RULES["DEP-005"], WARN,
                           "非 Python 内联依赖未精确钉版本: "
                           + summarize([f"{d.where} {d.ecosystem} {d.spec}"
                                        f"（{d.kind}）" for d in loose])))
        else:
            out.append(res(RULES["DEP-005"], PASS,
                           f"{len(inline)} 处非 Python 内联依赖均已精确钉版本"))

    return out
