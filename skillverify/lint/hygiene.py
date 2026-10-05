"""lint.hygiene —— 目录卫生、编码、正文存在性、扫描覆盖（HYG / ENC / I18N / BODY / COV）。

分组理由：这五族都是"包作为一个交付物是否干净"的问题，判定依据全部来自
inventory（文件清单与原始字节），不需要解析脚本或执行子进程。

关于 `__pycache__` 的刻意不一致（旧体系两处口径矛盾，此处显式声明）：
- `__pycache__` **不**进 SKIP_DIRS：它是最常被误提交的垃圾，必须能被 HYG-002 检出；
  其内容因二进制嗅探（.pyc 含 NUL）不会被当文本扫，故不产生额外噪音。
- `.pytest_cache`/`.mypy_cache`/`.ruff_cache`/`.tox` 进 SKIP_DIRS：这些是本地工具缓存，
  必然被 .gitignore 覆盖，检出它们只会制造噪音。

关于垃圾文件判定的"是否会被交付"：HYG-002 的**级别由 git 决定**——
被 git 跟踪的文件（真的会随包交付）记 FAIL，未被跟踪/无法判定 git 记 WARN。
这是在"噪音"与"漏报"之间的显式取舍：旧体系一律 FAIL，在一个有 .gitignore 的
仓库里会持续误报，最终训练出"无视 WARN"的习惯。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..report import FAIL, INFO, PASS, WARN, Result, Rule
# 素材类扩展名与体积阈值统一取自 inventory，避免同一常量两处各写一份
from .inventory import ASSET_EXTS, BIG_FILE_BYTES
from .shared import (
    MAX_EVIDENCE_ITEMS,
    LintContext,
    count_lines,
    fence_map,
    res,
    strip_inline_comment,
    summarize,
)

_SPEC_DIRS = "https://agentskills.io/specification#directory-structure"

#: 随包许可/版权文件的常见名字（小写比较）
LICENSE_FILES = frozenset({
    "license", "license.txt", "license.md", "licence", "licence.txt",
    "copying", "copying.txt", "notice", "notice.txt", "notice.md",
})

#: license 字段的合理长度上限（超过它多半是把完整条款塞进了 frontmatter）
LICENSE_FIELD_MAX = 200


RULES: dict[str, Rule] = {
    "HYG-001": Rule(
        "HYG-001",
        "目录命名宜用官方约定的承载目录（scripts//references//assets/）",
        "HOUSE",
        _SPEC_DIRS + "（官方允许任意目录，命名约定是建议）",
        "改用 references/ 或 assets/；同义变体目录名会让使用者在多个技能间失去一致性预期",
    ),
    "HYG-002": Rule(
        "HYG-002",
        "包内不得残留缓存/临时/备份文件",
        "HOUSE",
        "本项目收紧：官方未要求，但这类文件会被一同分发",
        "删除该文件，并把相应模式加入 .gitignore，避免再次误提交",
    ),
    "HYG-003": Rule(
        "HYG-003",
        "文件扩展名在已知集合内",
        "HOUSE",
        "本项目收紧：官方允许任意文件",
        "确认该文件确属技能内容（是则归入 assets/ 或补全扩展名，否则删除）",
    ),
    "HYG-004": Rule(
        "HYG-004",
        "单个文件 ≤1MB",
        "HOUSE",
        "本项目收紧：官方无体积约定",
        "把大文件移出技能包（技能包会被整份复制/加载），或改为按需下载并说明来源",
    ),
    "HYG-005": Rule(
        "HYG-005",
        "素材类文件应归置 assets/",
        "HOUSE",
        _SPEC_DIRS,
        "把模板/图片/数据等静态资源移到 assets/，SKILL.md 用相对路径引用",
    ),
    "ENC-001": Rule(
        "ENC-001",
        "shell 脚本必须 LF 换行",
        "HOUSE",
        "本项目收紧（CRLF 会让 `bash x.sh` 报 bad interpreter）",
        "转换为 LF；在 .gitattributes 写 `*.sh text eol=lf` 防止复发",
    ),
    "ENC-002": Rule(
        "ENC-002",
        "文本文件统一 LF 换行",
        "HOUSE",
        "本项目收紧：官方未规定换行，但混用会污染 diff 并影响跨宿主工具",
        "转换为 LF；在 .gitattributes 写 `* text=auto eol=lf` 防止复发",
    ),
    "ENC-003": Rule(
        "ENC-003",
        "文本文件不得带 BOM",
        "HOUSE",
        "本项目收紧：官方未规定；BOM 会让部分解析器把首行 `---` 读错",
        "以 UTF-8（无 BOM）重新保存",
    ),
    "ENC-004": Rule(
        "ENC-004",
        "文本文件必须能以 UTF-8 解码",
        "HOUSE",
        "本项目实测教训：GBK 等本地编码在其它宿主必然乱码或崩溃",
        "以 UTF-8 重新保存该文件",
    ),
    "I18N-001": Rule(
        "I18N-001",
        "代码块内的命令行不得混入中文/全角字符",
        "HOUSE",
        "本项目收紧（命令与注释分行的可复制性要求）",
        "命令保持原文，中文说明另起一行或写在 `#` 注释里",
    ),
    "BODY-001": Rule(
        "BODY-001",
        "SKILL.md 正文非空",
        "HOUSE",
        "https://agentskills.io/specification#body-content",
        "补写正文：分步指令、输入输出示例、常见边界情况",
    ),
    "COV-001": Rule(
        "COV-001",
        "扫描覆盖完整（无读取失败/超限跳过）",
        "HOUSE",
        "本项目纪律：覆盖不完整时不得以 PASS 呈现",
        "修正文件权限或体积后复跑；覆盖有洞时本报告的 PASS 不代表该项已通过",
    ),
    "HYG-006": Rule(
        "HYG-006",
        f"license 字段宜简短（≤{LICENSE_FIELD_MAX} 字符、单行）",
        "HOUSE",
        "旧体系 V15（许可合规）；官方仅规定 license 为可选字段",
        "把完整条款放进随包文件（LICENSE/COPYING），frontmatter 里只写许可名或一句指引——"
        "frontmatter 是每次加载都要读的元数据，塞长文本会挤占上下文预算",
    ),
    "HYG-007": Rule(
        "HYG-007",
        "声明了 license 就应有随包许可文件",
        "HOUSE",
        "旧体系 V15（许可合规）",
        "在技能根放一份 LICENSE（或 COPYING/NOTICE）：对外交付时收件人要能核对条款全文",
    ),
}

#: 非约定目录名（建议改用 references//assets/）
NONSTANDARD_DIRS: dict[str, str] = {
    "docs": "references/",
    "doc": "references/",
    "utils": "scripts/",
    "util": "scripts/",
    "lib": "scripts/",
    "libs": "scripts/",
    "helpers": "scripts/",
    "helper": "scripts/",
    "misc": "references/",
    "common": "scripts/",
    "shared": "scripts/",
    "tools": "scripts/",
    "tool": "scripts/",
    "templates": "assets/",
}

#: 垃圾路径（任意一段命中即算）
JUNK_PATH_RE = re.compile(
    r"(?:^|/)(?:__pycache__|\.DS_Store|Thumbs\.db|desktop\.ini|\.cache)(?:$|/)", re.I
)
#: 垃圾文件名
JUNK_NAME_RE = re.compile(
    r"(?:\.py[co]$|\.tmp$|\.temp$|\.log$|\.log\.\d+$|\.orig$|\.rej$|\.bak$"
    r"|\.swp$|\.swo$|~$|\.crdownload$|\.part$)",
    re.I,
)

TEXT_EXTS = frozenset(
    {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".rst",
     ".jsonl", ".xml", ".html", ".css", ".tsv"}
)
SPECIAL_NAMES = frozenset(
    {"license", "license.txt", "license.md", "notice", "notice.txt", "changelog",
     "changelog.md", ".gitignore", ".gitattributes", ".editorconfig", "makefile",
     "dockerfile", "readme", "readme.md", "skill.md", "agents.md"}
)

#: 代码块内行首为命令的行（用于 I18N-001）
CMD_START_RE = re.compile(
    r"^\s*(?:\$\s+|>\s+|PS\s+[A-Za-z]:\\>\s*)?"
    r"(?:pip3?|npm|npx|pnpm|yarn|uvx?|pipx|python3?|node|deno|bun|git|curl|wget|"
    r"bash|sh|zsh|fish|pwsh|powershell|cd|ls|dir|mkdir|rmdir|rm|del|cp|copy|"
    r"mv|move|cat|type|echo|touch|chmod|docker|kubectl|make)\b"
)
#: 全角字符 + CJK 汉字（命令行里出现任何一个都会让命令不可直接复制执行）
FULLWIDTH_RE = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uff01-\uff5e]")


def tracked_files(root: Path) -> set[str] | None:
    """返回 git 跟踪的文件（相对技能根目录，POSIX 风格）；无法判定时返回 None。

    仅用于判定"这个垃圾文件是否真的会随包交付"，不作为检查是否执行的开关——
    即便返回 None，检查照跑，只是级别退化为 WARN。
    """
    try:
        top = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        )
        if top.returncode != 0:
            return None
        repo = Path(top.stdout.strip())
        proc = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        if proc.returncode != 0:
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    out: set[str] = set()
    for rel in proc.stdout.split("\0"):
        if not rel:
            continue
        try:
            out.add((repo / rel).resolve().relative_to(root.resolve()).as_posix())
        except (ValueError, OSError):
            continue
    return out


def _check_hygiene(ctx: LintContext) -> list[Result]:
    out: list[Result] = []
    inv = ctx.inventory

    # ---- HYG-001 非约定目录名 ----
    bad_dirs = sorted({rec.rel.parts[0] for rec in inv.files
                       if len(rec.rel.parts) > 1 and rec.rel.parts[0].lower() in NONSTANDARD_DIRS})
    if bad_dirs:
        detail = "; ".join(f"{d}/ → 建议 {NONSTANDARD_DIRS[d.lower()]}" for d in bad_dirs)
        out.append(res(RULES["HYG-001"], WARN, detail))
    else:
        out.append(res(RULES["HYG-001"], PASS, "顶层目录命名符合约定"))

    # ---- HYG-002 垃圾文件（级别由 git 跟踪状态决定）----
    tracked = tracked_files(ctx.root)
    junk: list[str] = []
    junk_tracked = False
    for rec in inv.files:
        if JUNK_PATH_RE.search(rec.rp) or JUNK_NAME_RE.search(rec.rel.name):
            junk.append(rec.rp)
            if tracked is not None and rec.rp in tracked:
                junk_tracked = True
    if not junk:
        out.append(res(RULES["HYG-002"], PASS, "无缓存/临时/备份文件"))
    else:
        if tracked is None:
            note = "（无法判定 git 跟踪状态，暂记 WARN）"
            status = WARN
        elif junk_tracked:
            note = "（其中含已被 git 跟踪的文件，会随包交付）"
            status = FAIL
        else:
            note = "（均未被 git 跟踪，可能只是本地残留）"
            status = WARN
        out.append(res(RULES["HYG-002"], status, f"{summarize(junk)}{note}"))

    # ---- HYG-003 扩展名白名单 ----
    unknown: list[str] = []
    for rec in inv.files:
        name = rec.rel.name.lower()
        suffix = rec.suffix
        if suffix in TEXT_EXTS or suffix in ASSET_EXTS or suffix in {
            ".py", ".sh", ".bash", ".zsh", ".fish", ".js", ".mjs", ".cjs", ".ts",
            ".rb", ".pl", ".ps1", ".psm1",
        }:
            continue
        if name in SPECIAL_NAMES or not suffix:
            continue
        unknown.append(rec.rp)
    if unknown:
        unknown = sorted(unknown)
        out.append(res(RULES["HYG-003"], WARN,
                       f"扩展名不在已知集合: {summarize(unknown, MAX_EVIDENCE_ITEMS)}"))
    else:
        out.append(res(RULES["HYG-003"], PASS, f"{len(inv.files)} 个文件扩展名均在已知集合"))

    # ---- HYG-004 体积 ----
    big = [f"{rec.rp}（{rec.size // 1024}KB）" for rec in inv.files
           if rec.size > BIG_FILE_BYTES]
    if big:
        out.append(res(RULES["HYG-004"], WARN,
                       f"单文件 >{BIG_FILE_BYTES // 1024 // 1024}MB: {summarize(big)}"))
    else:
        out.append(res(RULES["HYG-004"], PASS,
                       f"无单文件超过 {BIG_FILE_BYTES // 1024 // 1024}MB"))

    # ---- HYG-005 素材归置 ----
    # evals/ 是官方约定的评测输入文件落点（`evals/files/...`），不是"没归置的素材"；
    # 把它算进 assets/ 检查会产生假阳性（M6 文档演练实测命中过）。
    misplaced = sorted(rec.rp for rec in inv.files
                       if rec.suffix in ASSET_EXTS and not rec.under("assets", "evals"))
    if misplaced:
        out.append(res(RULES["HYG-005"], WARN, f"素材类文件不在 assets/: {summarize(misplaced)}"))
    else:
        out.append(res(RULES["HYG-005"], PASS, "素材类文件均在 assets/（或 evals/）内或不存在"))

    return out


def _check_encoding(ctx: LintContext) -> list[Result]:
    out: list[Result] = []
    shell_crlf: list[str] = []
    other_crlf: list[str] = []
    boms: list[str] = []
    undecodable: list[str] = []
    scanned = 0

    for rec in ctx.inventory.files:
        if rec.raw is None:
            continue
        scanned += 1
        if rec.raw.startswith(b"\xef\xbb\xbf"):
            boms.append(rec.rp)
        if rec.decode_error:
            undecodable.append(rec.rp)
        if rec.is_binary:
            continue  # 二进制不含"换行约定"概念（PNG/zip 天然含 0x0D）
        if b"\r" in rec.raw:
            (shell_crlf if rec.is_shell else other_crlf).append(rec.rp)

    if shell_crlf:
        out.append(res(RULES["ENC-001"], FAIL, f"shell 脚本含 CR: {summarize(shell_crlf)}"))
    else:
        out.append(res(RULES["ENC-001"], PASS, "无 shell 脚本含 CR（或包内无 shell 脚本）"))

    if other_crlf:
        out.append(res(RULES["ENC-002"], WARN, f"含 CR（CRLF 或孤立 CR）: {summarize(other_crlf)}"))
    else:
        out.append(res(RULES["ENC-002"], PASS, f"{scanned} 个文件均为 LF"))

    if boms:
        out.append(res(RULES["ENC-003"], WARN, f"带 BOM: {summarize(boms)}"))
    else:
        out.append(res(RULES["ENC-003"], PASS, "无 BOM"))

    if undecodable:
        out.append(res(RULES["ENC-004"], FAIL,
                       f"无法按 UTF-8 解码（已用替换符兜底扫描）: {summarize(undecodable)}"))
    else:
        out.append(res(RULES["ENC-004"], PASS, "全部文本文件可按 UTF-8 解码"))

    return out


def _check_i18n(ctx: LintContext) -> list[Result]:
    hits: list[str] = []
    fences = fence_map(ctx.text)
    for idx, line in enumerate(ctx.text.split("\n")):
        if not (fences[idx] if idx < len(fences) else False):
            continue
        if not CMD_START_RE.match(line):
            continue
        body = strip_inline_comment(line)
        if FULLWIDTH_RE.search(body):
            hits.append(f"SKILL.md:{idx + 1}: {body.strip()[:48]}")
    if hits:
        return [res(RULES["I18N-001"], WARN, summarize(hits))]
    return [res(RULES["I18N-001"], PASS, "代码块内命令行为零命中")]


def _check_body(ctx: LintContext) -> list[Result]:
    if not (ctx.body or "").strip():
        return [res(RULES["BODY-001"], WARN, "frontmatter 之后无正文内容")]
    return [res(RULES["BODY-001"], PASS, f"正文 {count_lines(ctx.body)} 行")]


def _check_coverage(ctx: LintContext) -> list[Result]:
    inv = ctx.inventory
    errs = inv.read_errors
    overs = inv.oversized
    if errs or overs:
        parts = []
        if errs:
            parts.append("读取失败: " + summarize([f"{r.rp}（{r.error}）" for r in errs]))
        if overs:
            parts.append("超 2MB 未做内容扫描: " + summarize([r.rp for r in overs]))
        return [res(RULES["COV-001"], WARN, "；".join(parts))]
    note = f"扫描 {len(inv.files)} 个文件"
    if inv.binaries:
        note += f"（二进制跳过内容扫描 {len(inv.binaries)} 个）"
    if inv.symlinks:
        note += f"（符号链接未跟随 {len(inv.symlinks)} 个）"
    return [res(RULES["COV-001"], PASS, note)]


def _license_files(ctx: LintContext) -> list[str]:
    """技能根下的许可/版权文件（只看顶层与一层子目录，避免把依赖里的 LICENSE 算进来）。"""
    found: list[str] = []
    for rec in ctx.inventory.files:
        if rec.path.name.lower() in LICENSE_FILES and rec.rp.count("/") <= 1:
            found.append(rec.rp)
    return sorted(set(found))


def _check_license(ctx: LintContext) -> list[Result]:
    """V15 的机械部分：`license` 字段是否简短、声明了许可时有没有随包文件。

    官方只规定 `license` 是可选字段（没规定长度与文件）；这两条是本项目的 HOUSE 收紧，
    因此都是 WARN——**不阻断交付**，但会在交付记录里留痕。
    """
    out: list[Result] = []
    fm = ctx.doc.frontmatter
    raw = fm.get("license") if fm is not None else None
    value = raw if isinstance(raw, str) else ""
    stripped = value.strip()
    files = _license_files(ctx)

    if not stripped:
        out.append(res(RULES["HYG-006"], INFO, "不适用：未声明 license"))
    elif len(stripped) > LICENSE_FIELD_MAX or "\n" in value:
        out.append(res(RULES["HYG-006"], WARN,
                       f"license 字段过长（{len(stripped)} 字符，上限 {LICENSE_FIELD_MAX}）："
                       f"完整条款应放在随包文件里，字段只写许可名或一句指引"))
    else:
        out.append(res(RULES["HYG-006"], PASS, f"license 字段简短（{len(stripped)} 字符）"))

    if not stripped:
        out.append(res(RULES["HYG-007"], INFO, "不适用：未声明 license"))
    elif files:
        out.append(res(RULES["HYG-007"], PASS, f"随包许可文件：{'、'.join(files[:3])}"))
    else:
        out.append(res(RULES["HYG-007"], WARN,
                       f"声明了 license（{stripped[:40]}）但技能目录里没有随包许可文件："
                       f"对外交付时收件人无从核对条款全文"))
    return out


def check(ctx: LintContext) -> list[Result]:
    out: list[Result] = []
    out.extend(_check_hygiene(ctx))
    out.extend(_check_license(ctx))
    out.extend(_check_encoding(ctx))
    out.extend(_check_i18n(ctx))
    out.extend(_check_body(ctx))
    out.extend(_check_coverage(ctx))
    return out
