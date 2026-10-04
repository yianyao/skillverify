#!/usr/bin/env python3
"""security_scan.py — Agent Skill V8 安全扫描器（S 工具链）。

落实《Agent-Skill 生命周期验证方案》V8 条目（[M]，纳入 §6.1 机械门阻断策略）
与 W-S 表四行（§9.6 敏感信息 / §9.2 端点静态部分 / §8.3.1 交互补强 / §8.3.10+§9.8
危险指令关键词部分）。扫描面 = 技能包全部文本文件（不限于 SKILL.md 与 scripts/）。

检查项:
  V8-1 secret 正则库      已知密钥格式（AWS/GitHub/OpenAI/Slack/Google/私钥块/JWT/
                          通用赋值型），占位符降噪（§9.6）
  V8-2 熵检测             长度>=20 且香农熵>=4.5 的高熵串（启发式，宁可误报不漏报；
                          阈值设计上已排除常规 hex 哈希——hex 每字符熵上限 4.0）（§9.6）
  V8-3 外部端点提取比对   提取全部 http(s) URL，与 frontmatter compatibility 声明
                          及 --allow-url 白名单比对；未声明即 FAIL（§9.2 静态部分，
                          声明用途的语义核对留 L，§9.9）
  V8-4 多语言交互调用     input(/getpass/read -p/confirm(/readline(/inquirer/
                          prompt_toolkit/click.confirm 共 8 类（与 check_skill A9
                          同清单，扫描面扩展到全包）（§8.3.1，补强 A9 只扫 scripts/*.py）
  V8-5 破坏性关键词防护   脚本/代码文件命中破坏性关键词（rm/drop/delete/migrate/
                          publish/truncate/purge/reset/overwrite/unlink/destroy/
                          wipe/revoke）而不含 --confirm/--force/--dry-run 之一即
                          FAIL（§8.3.10 静态部分，示例清单可扩展）
  V8-6 危险指令关键词     绕过确认/静默上传/权限扩张类关键词（§9.8 关键词部分；
                          语义部分留 W-L/H）

两级命中语义（全工具统一）:
  代码文件（scripts/ 目录内任意文件 + 代码扩展名文件）命中 → FAIL
  文档文件（其余文本文件）命中 → WARN（人工复核；V8-3 端点例外——文档链接
  同样记未声明端点，豁免走 --allow-url 留痕，不降 WARN）

扫描面纪律:
  跳过 .git/.verification/__pycache__/node_modules/虚拟环境目录与二进制扩展名
  （.verification 是工具留痕非交付物；二进制按扩展名黑名单排除，宁可误扫不漏扫）。

用法:
    python security_scan.py <skill_dir>                        # 扫描单个技能
    python security_scan.py <skill_dir> --out report.md        # 报告落盘
    python security_scan.py <skill_dir> --allow-url docs.python.org --allow-url https://example.com/api

退出码: 0=全 PASS；1=任一 FAIL；2=无 FAIL 但有 WARN（与工具族 0/1/2 约定一致）。
注: 本工具只做机械初筛；§9.1/§9.2/§9.8 的语义审计仍由 L+H 承担（W-S/W-L 表）。

版本: v1.0（2026-10-02 建成，S1① 待办）
      v1.0.1（2026-10-02 首轮外部评审 9 条采纳修订）——
      1[S] 命中证据脱敏（V8-1/V8-2 首尾保留式掩码，报告落盘不再含完整密钥/高熵串）；
      2[S] --allow-url 前缀与 compatibility 声明匹配改主机边界比较（修复
          https://example.com 放行 https://example.com.evil.io 的绕过），路径级匹配
          补路径边界（/v1 不再匹配 /v1evil）；
      3[S] 读取失败移出 V8-1 命中、独立 COV 覆盖行（V8-1 结论仅由真实密钥命中决定，
          消除"扫出密钥"误读；覆盖不全仍使零命中行降 WARN + exit≠0）；
      4[S] V8-5 防护判定改结构化数据（protected 布尔位），不再耦合消息文本；
      5[P] frontmatter 解析合并缩进续行（折叠标量 compatibility 的 URL 不再漏提取）；
      6[doc] scripts/ 下任意扩展名（含 .md）按代码文件判——有意设计（可执行邻接位
          宁可误报不漏报），docstring 显式声明；
      7[P] 符号链接跳过（不跟随读取技能目录外目标）；
      8[P] 危险关键词单次预编译匹配；通用赋值型 key 过 md_escape；工具版本标识
          入报告头；
      9[P] V8-4 调用型模式加前置断言（input(/confirm(/readline( 不再命中
          reinput(/my_input(），read -p 扩展 read -rp 等组合短横线形态。
      v1.0.2（2026-10-02 第二轮外部评审 6 条：4 改代码 + 2 补文档）——
      1[P] V8-4 词形模式补齐边界断言：getpass/inquirer/prompt_toolkit 统一
          (?<!\\w)…\\b（不再命中 mygetpass/reinquirer/prompt_toolkits）；
      2[P] read 短选项收紧为 [a-zA-Z]*p（原 -\\w*p 曾误中 read -3p）；
      3[P] mask_secret tail 4→2（20 字符密钥泄露面 8→6 字符，对齐业界脱敏惯例）；
      4[doc] url_allowed 显式声明"声明域同时放行其全部子域"的设计口径；
      5[doc] COV 符号链接计数语义显式声明（仅统计有效链接；断链不入统计）；
      6[P] COV 行分隔符统一为 "; "（与其它行一致）。
      v1.0.3（2026-10-03 收官回填批次）——
      1[P] 参数解析改 _BlockArgParser（参数错误统一 exit 1，不撞 WARN 码——族纪律
          最后一个未回填成员，与 check_skill/smoke_runner 同源先例）；
      2[P] --out 空串显式校验（原 `--out ""` 静默不落盘，现 fail-fast exit 1）。
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

# ---------------------------------------------------------------- 常量表 ----

VERSION = "v1.0.3"  # 评审修订标识随报告落盘（v1.0.1 评审 8：与 fix-log 可对照）

SKIP_DIRS = {".git", ".verification", "__pycache__", "node_modules", ".venv", "venv"}
MAX_FILE_BYTES = 2 * 1024 * 1024  # 超 2MB 跳过并记覆盖说明（防病态文件拖死扫描）

BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".pdf",
    ".zip", ".gz", ".tar", ".7z", ".rar", ".exe", ".dll", ".so", ".dylib",
    ".woff", ".woff2", ".ttf", ".eot", ".otf", ".mp3", ".mp4", ".mov",
    ".avi", ".bin", ".pyc", ".pyo", ".class", ".jar", ".xls", ".xlsx",
}

CODE_EXTS = {".py", ".sh", ".bash", ".js", ".ts", ".mjs", ".cjs", ".rb", ".pl", ".ps1"}

# V8-1 secret 正则库（示例清单，可扩展）。顺序即报告展示顺序。
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS Access Key ID", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("OpenAI 风格密钥", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("私钥块", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}")),
    ("通用赋值型 secret", re.compile(
        r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd|access[_-]?key|"
        r"private[_-]?key|client[_-]?secret)\b\s*[:=]\s*[\"']([^\"']{8,})[\"']")),
]

# 占位符降噪：通用赋值型命中值含下列特征即跳过（文档示例/模板占位）
PLACEHOLDER_SIGNS = (
    "your_", "your-", "<", ">", "example", "placeholder", "changeme",
    "dummy", "xxxx", "****", "${", "{{", "{%", "todo", "tbd", "insert",
    "redacted", "not-a-real",
)

# V8-2 熵检测参数
ENTROPY_TOKEN_RE = re.compile(r"[A-Za-z0-9+/=_\-]{20,}")
ENTROPY_THRESHOLD = 4.5
ENTROPY_MAX_TOKEN = 200  # 超长串（如整段编码）不判熵，避免噪声

# V8-3 端点
URL_RE = re.compile(r"https?://[^\s\"'<>\\)\]]+")

# V8-4 交互式输入模式（与 check_skill.py A9 同清单——单一真源以 A9 文档为准）。
# 全部词形模式统一 (?<!\w) 前置断言 + \b 后边界（v1.0.2 评审 1：getpass/inquirer/
# prompt_toolkit 不再命中 mygetpass/reinquirer/prompt_toolkits，与 v1.0.1 评审 9
# 对 input( 的处理口径一致）；read 短选项收紧为字母组合（-\w*p 会误中 read -3p）。
# 注：本清单对 scripts/ 目录内**任意扩展名**文件（含 .md）按代码文件判——有意设计：
# scripts/ 是可执行邻接位，宁可误报不漏报；scripts 内文档若需说明 input( 用法，
# 应人工复核豁免或改写表述（v1.0.1 评审 6 显式声明）。
INTERACTIVE_PAT: list[tuple[str, re.Pattern[str]]] = [
    ("input(", re.compile(r"(?<!\w)input\s*\(")),
    ("getpass", re.compile(r"(?<!\w)getpass\b")),
    ("read -p", re.compile(r"\bread\s+-[a-zA-Z]*p\b")),  # read -p / -rp / -sp 等字母组合
    ("confirm(", re.compile(r"(?<!\w)confirm\s*\(")),
    ("readline(", re.compile(r"(?<!\w)readline\s*\(")),
    ("inquirer", re.compile(r"(?<!\w)inquirer\b")),
    ("prompt_toolkit", re.compile(r"(?<!\w)prompt_toolkit\b")),
    ("click.confirm", re.compile(r"click\.confirm")),
]

# V8-5 破坏性关键词（§8.3.10 示例清单）与防护标志——单次预编译（v1.0.1 评审 8）
DESTRUCTIVE_WORD_RE = re.compile(
    r"\b(rm|drop|delete|migrate|publish|truncate|purge|reset|overwrite|unlink|destroy|wipe|revoke)\b",
    re.I,
)
PROTECTION_FLAGS = ("--confirm", "--force", "--dry-run")

# V8-6 危险指令关键词（§9.8 关键词部分，示例清单可扩展）
DANGEROUS_PAT = re.compile(
    r"(?i)(绕过(?:用户)?确认|跳过(?:用户)?确认|静默上传|未经确认上传|权限扩张|扩大权限|提权|"
    r"bypass confirmation|skip confirmation|silent upload|"
    r"privilege escalation|escalate privileges|chmod 777)")


# ---------------------------------------------------------------- 基础设施 ----

def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((v / n) * math.log2(v / n) for v in counts.values())


def is_placeholder(value: str) -> bool:
    low = value.lower()
    return any(sign in low for sign in PLACEHOLDER_SIGNS)


def md_escape(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def mask_secret(s: str, head: int = 4, tail: int = 2) -> str:
    """首尾保留式脱敏：报告落盘不得含完整密钥/高熵串（v1.0.1 评审 1）。

    v1.0.2 评审 3：tail 4→2（对齐业界惯例——GitHub 只展示 token 前 4 位、
    AWS 控制台只展示末 4 位；20 字符密钥泄露面 8→6 字符，head=4 保留 AKIA
    类前缀特征便于定位）。"""
    if len(s) <= head + tail:
        return "…"
    return f"{s[:head]}…{s[-tail:]}(len={len(s)})"


def is_code_file(rel: Path) -> bool:
    return rel.suffix.lower() in CODE_EXTS or rel.parts[0] == "scripts"


def load_frontmatter(skill_dir: Path) -> dict[str, str]:
    """极简 frontmatter 顶层键解析（与 check_skill.py 口径一致，仅取 compatibility 用）。

    v1.0.1 评审 5：缩进续行并入前一个顶层键（YAML 折叠标量 `compatibility: >`
    的续写行不再漏提取——该场景曾致 V8-3 假阳性）。"""
    p = skill_dir / "SKILL.md"
    fm: dict[str, str] = {}
    try:
        raw = p.read_bytes()
    except OSError:
        return fm
    raw = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
    text = raw.decode("utf-8", errors="replace")
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", text, re.S)
    if not m:
        return fm
    last_key: str | None = None
    for ln in m.group(1).split("\n"):
        if ln[:1] in (" ", "\t"):
            # v1.0.1 评审 5：折叠/续行并入上一个键（无上一个键时忽略）
            if last_key:
                fm[last_key] = (fm[last_key] + " " + ln.strip()).strip()
            continue
        if ":" in ln:
            k, _, v = ln.partition(":")
            k = k.strip()
            if re.fullmatch(r"[a-z][a-z0-9-]*", k):
                fm[k] = v.strip()
                last_key = k
            else:
                last_key = None
        else:
            last_key = None
    return fm


def iter_scan_files(skill_dir: Path):
    """产出 (相对路径, 绝对路径)。仅跳过工具留痕目录；二进制/超限在扫描主体计数后跳过。"""
    for p in sorted(skill_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(skill_dir)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        yield rel, p


def normalize_url(u: str) -> str:
    return u.rstrip(".,;:!?)]}）。，、；：！？")


def _host_matches(host: str, base_host: str) -> bool:
    """主机边界：相等或为主域子域（example.com 匹配 api.example.com，不匹配 example.com.evil.io）。"""
    return bool(base_host) and (host == base_host or host.endswith("." + base_host))


def _path_matches(url_path: str, base_path: str) -> bool:
    """路径边界：/v1 匹配 /v1 与 /v1/x，不匹配 /v1evil（v1.0.1 评审 2）。"""
    b = base_path.rstrip("/")
    if not b:
        return True
    return url_path == b or url_path.startswith(b + "/")


def url_allowed(url: str, declared_urls: list[str], allow_entries: list[str]) -> tuple[bool, str]:
    """返回 (是否放行, 放行依据)。声明=compatibility 内出现（§9.9）；白名单=--allow-url。

    v1.0.1 评审 2：URL 形态条目一律解析 netloc 做主机边界比较（纯前缀 startswith
    会放行 https://example.com.evil.io），带路径的条目再补路径边界比较。
    设计声明（v1.0.2 评审 4）：**声明域同时放行其全部子域**——声明 api.example.com
    覆盖 www.api.example.com，子域语义由 _host_matches 承载（host == base 或
    host.endswith("." + base)）；--allow-url 与声明取同一口径。若未来需精确匹配
    （禁止子域），应在此处加开关而非改 _host_matches，以免声明/白名单口径分叉。"""
    u = urlparse(url)
    host = (u.netloc or "").lower()
    upath = u.path or "/"
    for d in declared_urls:
        d = normalize_url(d)
        du = urlparse(d)
        dh = (du.netloc or "").lower()
        if _host_matches(host, dh) and _path_matches(upath, du.path or "/"):
            return True, f"compatibility 声明: {d}"
    for a in allow_entries:
        if "://" not in a:
            a_low = a.lower().strip("/")
            if _host_matches(host, a_low):
                return True, f"--allow-url 域名: {a}"
        else:
            au = urlparse(a)
            if _host_matches(host, (au.netloc or "").lower()) and _path_matches(upath, au.path or "/"):
                return True, f"--allow-url 前缀: {a}"
    return False, ""


# ---------------------------------------------------------------- 扫描主体 ----

def scan(skill_dir: Path, allow_entries: list[str]) -> tuple[list[dict], dict]:
    """返回 (报告行, 统计)。行: dict(vid,title,level,ev)。"""
    rows: list[dict] = []

    def add(vid: str, title: str, level: str, ev: str) -> None:
        rows.append(dict(vid=vid, title=title, level=level, ev=ev))

    fm = load_frontmatter(skill_dir)
    compatibility = fm.get("compatibility", "")
    declared_urls = URL_RE.findall(compatibility)

    hits = {vid: [] for vid in ("V8-1", "V8-2", "V8-3", "V8-4c", "V8-4d",
                                "V8-5", "V8-6c", "V8-6d")}
    n_files = 0
    n_symlink_skipped = 0
    n_binary_skipped = 0
    n_oversize_skipped = 0
    n_read_err = 0
    n_placeholder_filtered = 0
    read_err_files: list[str] = []

    for rel, p in iter_scan_files(skill_dir):
        if p.is_symlink():
            # v1.0.1 评审 7：不跟随符号链接（范围蔓延 + 技能目录外信息泄露风险）
            n_symlink_skipped += 1
            continue
        if rel.suffix.lower() in BINARY_EXTS:
            n_binary_skipped += 1
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                n_oversize_skipped += 1
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            # v1.0.1 评审 3：读取失败不再计入 V8-1 命中（消除"扫出密钥"误读），
            # 仅计入覆盖统计（COV 行 WARN + 零命中行降 WARN + exit≠0 承担覆盖不全表达）
            n_read_err += 1
            read_err_files.append(f"{rel}: 读取失败（{e.strerror or e}）")
            continue
        n_files += 1
        code = is_code_file(rel)

        for lineno, line in enumerate(text.splitlines(), 1):
            # V8-1 secret 正则（证据脱敏：报告只留首尾片段——v1.0.1 评审 1）
            for name, pat in SECRET_PATTERNS:
                for m in pat.finditer(line):
                    if name == "通用赋值型 secret":
                        value = m.group(2)
                        if is_placeholder(value):
                            n_placeholder_filtered += 1
                            continue
                        snippet = f"{md_escape(m.group(1))}=<已脱敏 {mask_secret(value)}>"
                    else:
                        snippet = md_escape(mask_secret(m.group(0)))
                    hits["V8-1"].append((rel, lineno, f"{name}: {snippet}"))
            # V8-2 熵检测（同脱敏口径）
            for m in ENTROPY_TOKEN_RE.finditer(line):
                tok = m.group(0)
                if len(tok) > ENTROPY_MAX_TOKEN or "://" in tok:
                    continue
                if shannon_entropy(tok) >= ENTROPY_THRESHOLD:
                    hits["V8-2"].append((rel, lineno,
                        f"高熵串({len(tok)}字符): {md_escape(mask_secret(tok))}"))
            # V8-3 端点（全文件；V8-3 不分代码/文档两级，统一判未声明）
            for m in URL_RE.finditer(line):
                url = normalize_url(m.group(0))
                ok, basis = url_allowed(url, declared_urls, allow_entries)
                if not ok:
                    hits["V8-3"].append((rel, lineno, md_escape(url[:80])))
            # V8-4 交互调用（c=代码 FAIL / d=文档 WARN）
            for label, pat in INTERACTIVE_PAT:
                if pat.search(line):
                    hits["V8-4c" if code else "V8-4d"].append((rel, lineno, label))
            # V8-6 危险指令关键词（c/d 两级）
            for m in DANGEROUS_PAT.finditer(line):
                hits["V8-6c" if code else "V8-6d"].append((rel, lineno, md_escape(m.group(0)[:40])))

        # V8-5 破坏性关键词×确认防护（仅代码文件，文件级判定；
        # v1.0.1 评审 4：条目带 protected 布尔位，判定不再耦合消息文本）
        if code:
            kw_hit = sorted({m.group(0).lower() for m in DESTRUCTIVE_WORD_RE.finditer(text)})
            if kw_hit:
                protected = [f for f in PROTECTION_FLAGS if f in text]
                hits["V8-5"].append((rel, 0,
                    f"命中 {','.join(kw_hit)}；"
                    + (f"已有防护 {','.join(protected)}" if protected
                       else "无 --confirm/--force/--dry-run（须补防护或人工复核）"),
                    bool(protected)))

    # ---- 汇总判定 ----
    def fmt(items: list, cap: int = 5) -> str:
        # 条目为 (rel, lineno, ev[, ...])：V8-5 自 v1.0.1 起为 4 元组（末位 protected 布尔位），
        # fmt 只消费前三位——判定逻辑见 v5_bad/v5_ok 的结构化过滤
        shown = [f"{it[0]}:{it[1]} {it[2]}" if it[1] else f"{it[0]} {it[2]}" for it in items[:cap]]
        more = f"（另 {len(items) - cap} 处略）" if len(items) > cap else ""
        return "; ".join(shown) + more

    v1 = hits["V8-1"]
    add("V8-1", "secret 正则库零命中（§9.6）",
        "FAIL" if v1 else "PASS",
        fmt(v1) + ("" if v1 else f"（{len(SECRET_PATTERNS)} 类格式 × {n_files} 文件"
                                 + (f"，占位符降噪过滤 {n_placeholder_filtered} 处" if n_placeholder_filtered else "")
                                 + "）"))

    v2 = hits["V8-2"]
    add("V8-2", "熵检测零命中（§9.6 启发式）",
        "FAIL" if v2 else "PASS",
        (fmt(v2) + "（文本级匹配可能误报，命中须人工复核）" if v2
         else f"阈值: 长度>=20 且熵>= {ENTROPY_THRESHOLD}（hex 哈希天然低于阈值）"))

    v3 = hits["V8-3"]
    if v3:
        add("V8-3", "外部端点与声明比对（§9.2 静态）", "FAIL",
            f"未声明端点 {len(v3)} 处: {fmt(v3, 8)}"
            "。下一步: 属真实外联则写入 compatibility 声明（§9.9）；文档引用链接则 --allow-url <域名> 豁免并留痕")
    else:
        add("V8-3", "外部端点与声明比对（§9.2 静态）", "PASS",
            f"端点全部有归属（声明 {len(declared_urls)} 条/白名单 {len(allow_entries)} 条）" if (declared_urls or allow_entries)
            else "未发现外部 URL")

    v4c, v4d = hits["V8-4c"], hits["V8-4d"]
    if v4c:
        add("V8-4", "多语言交互调用零命中（§8.3.1）", "FAIL",
            fmt(v4c) + "（文本级匹配可能误报，命中须人工复核）"
            + (f"；另文档文件 WARN {len(v4d)} 处" if v4d else ""))
    elif v4d:
        add("V8-4", "多语言交互调用零命中（§8.3.1）", "WARN",
            f"代码文件零命中；文档文件提及 {len(v4d)} 处（人工复核是否为用法示例）: {fmt(v4d, 3)}")
    else:
        add("V8-4", "多语言交互调用零命中（§8.3.1）", "PASS",
            f"8 类模式 × {n_files} 文件零命中（扫描面含全包，补强 A9 的 scripts/*.py 限界）")

    v5 = hits["V8-5"]
    # v1.0.1 评审 4：条目 = (rel, 0, 消息, protected)；判定消费布尔位，不耦合消息文本
    v5_bad = [it for it in v5 if not it[3]]
    v5_ok = [it for it in v5 if it[3]]
    if v5_bad:
        add("V8-5", "破坏性关键词有确认防护（§8.3.10）", "FAIL",
            fmt(v5_bad) + "（关键词为示例清单；文本级匹配可能误报，命中须人工复核）"
            + (f"；已有防护 {len(v5_ok)} 个脚本合规" if v5_ok else ""))
    else:
        add("V8-5", "破坏性关键词有确认防护（§8.3.10）", "PASS",
            fmt(v5_ok) if v5_ok else "代码文件零命中破坏性关键词（或均有防护）")

    v6c, v6d = hits["V8-6c"], hits["V8-6d"]
    if v6c:
        add("V8-6", "危险指令关键词零命中（§9.8 关键词部分）", "FAIL",
            fmt(v6c) + "（文本级匹配可能误报，命中须人工复核；语义部分留 W-L/H）"
            + (f"；另文档文件 WARN {len(v6d)} 处" if v6d else ""))
    elif v6d:
        add("V8-6", "危险指令关键词零命中（§9.8 关键词部分）", "WARN",
            f"代码文件零命中；文档文件提及 {len(v6d)} 处（如'不得绕过确认'类合规表述，人工复核）: {fmt(v6d, 3)}")
    else:
        add("V8-6", "危险指令关键词零命中（§9.8 关键词部分）", "PASS",
            "全文件零命中")

    # v1.0.1 评审 3：覆盖行独立编号 COV——读取失败不再混入 V8-1 证据，
    # "扫出密钥"与"覆盖不全"在报告中语义分离。
    # 符号链接计数语义（v1.0.2 评审 5）：n_symlink_skipped 仅统计**有效**符号链接的
    # 跳过数——断链符号链接在 iter_scan_files 的 is_file() 即返回 False，不入任何
    # 统计（也不可读，无泄露面）；COV 行"符号链接 N"即"有效链接被跳过数"。
    cov_parts = [f"扫描 {n_files} 个文本文件",
                 f"跳过二进制扩展名 {n_binary_skipped}、超 2MB {n_oversize_skipped}、符号链接 {n_symlink_skipped}",
                 f"排除目录 {', '.join(sorted(SKIP_DIRS))}"]
    if n_read_err:
        cov_parts.append(f"{n_read_err} 个文件读取失败（覆盖不全，零命中行已同步降 WARN）: "
                         + "; ".join(read_err_files[:3]))
    add("COV", "扫描覆盖", "WARN" if n_read_err else "INFO", "; ".join(cov_parts))

    stats = dict(files=n_files, binary=n_binary_skipped, oversize=n_oversize_skipped,
                 symlink=n_symlink_skipped, read_err=n_read_err,
                 placeholder_filtered=n_placeholder_filtered)

    # 覆盖不全 ≠ 零命中通过（对齐 check_skill v1.1c 2.1 纪律）：有读取失败时，
    # 各零命中 PASS 行统一降 WARN，防止"覆盖不全却全绿 exit 0"
    if n_read_err:
        for r in rows:
            if r["level"] == "PASS":
                r["level"] = "WARN"
                r["ev"] += f"（WARN 缘由: {n_read_err} 个文件读取失败，覆盖不全）"
    return rows, stats


# ---------------------------------------------------------------- 报告与入口 ----

_ORDER = {"V8-1": 1, "V8-2": 2, "V8-3": 3, "V8-4": 4, "V8-5": 5, "V8-6": 6, "COV": 50}


def build_report(skill_dir: Path, rows: list[dict], stats: dict, allow_entries: list[str]) -> str:
    has_fail = any(r["level"] == "FAIL" for r in rows)
    has_warn = any(r["level"] == "WARN" for r in rows)
    judged = [r for r in rows if r["level"] in ("PASS", "FAIL")]
    lines = [
        "# V8 安全扫描报告（security_scan.py）",
        "",
        f"- 技能: {skill_dir.name}（{skill_dir}）",
        f"- 工具版本: {VERSION}",
        f"- 口径: V8（[M] 机械门）——secret 正则+熵（§9.6）/端点比对（§9.2 静态）/多语言交互（§8.3.1）"
        f"/破坏性关键词防护（§8.3.10）/危险指令关键词（§9.8 关键词部分）",
        f"- 白名单: {', '.join(allow_entries) if allow_entries else '无'}",
        f"- 扫描覆盖: {stats['files']} 文件（跳过二进制 {stats['binary']}、超限 {stats['oversize']}、"
        f"符号链接 {stats['symlink']}；排除 {', '.join(sorted(SKIP_DIRS))}）",
        f"- 总结论: {'FAIL（存在阻断项）' if has_fail else ('WARN（需人工书面评估）' if has_warn else 'PASS')}",
        "",
        "| 项 | 检查内容 | 结论 | 证据 |",
        "|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: (_ORDER.get(r["vid"], 99), r["vid"])):
        lines.append(f"| {r['vid']} | {r['title']} | {r['level']} | {r['ev']} |")
    lines += [
        "",
        f"> 判定统计: {sum(1 for r in judged if r['level'] == 'PASS')}/{len(judged)} PASS。"
        "语义审计（§9.1 恶意逻辑、§9.2 用途一致性、§9.8 完整语义）仍由 W-L 评审 + H 终审承担，本工具零命中不豁免语义审计。",
    ]
    if has_fail:
        lines[-1] += " [M] 级 FAIL 阻断，不得自动放行。"
    return "\n".join(lines) + "\n"


class _BlockArgParser(argparse.ArgumentParser):
    """参数错误统一 exit 1（阻断码）——argparse 默认 exit 2 撞 WARN 码
    （族纪律：naming_precheck v1.0.1 评审 5 先例；v1.0.3 收官回填批次补齐）。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"错误: {message}。下一步: 按用法核对参数后重试。", file=sys.stderr)
        raise SystemExit(1)


def main() -> int:
    ap = _BlockArgParser(
        description="Agent Skill V8 安全扫描器（secret 正则+熵 / 端点比对 / 交互 / 危险关键词）")
    ap.add_argument("skill_dir", help="待扫描技能根目录（含 SKILL.md）")
    ap.add_argument("--out", help="报告落盘路径（建议 .verification/m1-s/security-scan.md）")
    ap.add_argument("--allow-url", action="append", default=[],
                    help="端点白名单（域名如 docs.python.org 或 URL 前缀），可重复；豁免须留痕")
    a = ap.parse_args()

    if a.out is not None and not a.out.strip():
        print("错误: --out 为空字符串。下一步: 传有效报告路径或省略 --out 仅stdout输出。",
              file=sys.stderr)
        return 1

    skill_dir = Path(a.skill_dir)
    if not skill_dir.is_dir():
        print(f"错误: 目录不存在: {skill_dir}。下一步: 核对路径后重试。", file=sys.stderr)
        return 1

    rows, stats = scan(skill_dir, a.allow_url)
    report = build_report(skill_dir, rows, stats, a.allow_url)
    print(report)

    if a.out:
        outp = Path(a.out)
        try:
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text(report, encoding="utf-8", newline="\n")
            print(f"[已落盘] {outp}")
        except OSError as e:
            print(f"[FAIL] 报告落盘失败: {outp} — {e}。下一步: 检查路径权限或改用其他 --out 路径。", file=sys.stderr)
            return 1

    has_fail = any(r["level"] == "FAIL" for r in rows)
    has_warn = any(r["level"] == "WARN" for r in rows)
    return 1 if has_fail else (2 if has_warn else 0)


if __name__ == "__main__":
    sys.exit(main())
