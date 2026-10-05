"""lint.security —— 安全机械筛查（SEC）。

**强度定位（必须先说清楚）**：
官方规范页**没有**安全条款。这里的安全规则全部是本项目收紧（HOUSE），
其中只有"高置信度密钥格式"与"私钥块"记 FAIL——它们的误报率接近零；
其余（熵、通用赋值、下载即执行、混淆、外传、未声明端点）一律 WARN，
因为关键词/熵这类判据"命中不等于恶意"，终判属语义评审层（M5）。
旧体系把这批检查做成 FAIL，代价是把 `print("never bypass confirmation")`
这类正当文本也判成违规，最终训练出"无视告警"的习惯。

**为什么不用官方 `compatibility` 的自述信任模型**：技能自己声明自己的端点，
恶意技能当然会把自己写成"已声明"。因此 SEC-007 只把"代码里出现而未声明"当作
信号（WARN），并明确不承诺"已声明即可信"。

**脱敏**：所有密钥类证据一律 `mask_secret`，报告会被归档/分享，不能成为第二个泄露面。

**扫描范围**：包内全部文本文件（含 references/、assets/ 里的样例）。
刻意不做"样例目录豁免"——旧体系正是在这里留了后门，使真正坏的样例永远不会失败。
"""

from __future__ import annotations

from dataclasses import dataclass

import re

from ..report import FAIL, INFO, PASS, WARN, Result, Rule
from .shared import (
    LintContext,
    URL_RE,
    mask_secret,
    res,
    shannon_entropy,
    summarize,
)

RULES: dict[str, Rule] = {
    "SEC-001": Rule(
        "SEC-001",
        "不得包含真实密钥/私钥",
        "HOUSE",
        "本项目收紧（官方规范无安全条款）；判据为各厂商密钥的强特征前缀",
        "移除密钥并改用环境变量；如已提交过，务必作废并轮换该凭据",
    ),
    "SEC-002": Rule(
        "SEC-002",
        "赋值形式的疑似凭据须人工确认",
        "HOUSE",
        "本项目收紧；判据为「凭据字段名 + 引号值」，命中不等于违规",
        "确认是否为真实凭据；示例值请写成 <YOUR_API_KEY> 这类占位形态",
    ),
    "SEC-003": Rule(
        "SEC-003",
        "高熵字符串须人工确认（可能是密钥）",
        "HOUSE",
        "本项目收紧；熵阈值 4.5，仅作补充网（十六进制串天然不会命中）",
        "确认该串用途；若是密钥请移入环境变量，若是样例请改为明显占位形态",
    ),
    "SEC-004": Rule(
        "SEC-004",
        "禁止「下载即执行」链",
        "HOUSE",
        "本项目收紧；判据为 curl/wget/iwr 直接管道进 shell",
        "改为先下载到文件、校验哈希、再执行；或直接内置该脚本",
    ),
    "SEC-005": Rule(
        "SEC-005",
        "禁止混淆式动态执行（base64 + eval/exec）",
        "HOUSE",
        "本项目收紧；此类形态无法静态审计",
        "改为明文代码；确需动态执行时写明来源与校验方式",
    ),
    "SEC-006": Rule(
        "SEC-006",
        "URL 中不得携带凭据（query 参数或 userinfo）",
        "HOUSE",
        "本项目收紧；判据为 query 出现 token/apikey/password 等字段，"
        "或 URL 里出现 `user:password@host` 形态",
        "凭据改走请求头或环境变量，不要放在 URL 里（URL 会进日志与浏览器历史）",
    ),
    "SEC-007": Rule(
        "SEC-007",
        "代码文件中的外部端点宜在 frontmatter 中声明",
        "HOUSE",
        "本项目收紧；仅作提示，不代表已声明即安全",
        "在 `compatibility` 里写明需要访问哪些网络端点（便于使用者判断是否放行）",
    ),
    "SEC-008": Rule(
        "SEC-008",
        "不得含隐藏字符（双向控制符 / 零宽字符）",
        "HOUSE",
        "社区已知的隐写注入形态（Trojan Source、零宽字符藏指令）；官方规范未覆盖",
        "把隐藏字符删掉。双向控制符能让同一段内容「读起来」与「实际执行」不一致；"
        "零宽字符可以把指令藏进看起来无害的文本里——这类内容一律按不可信处理",
    ),
}

#: 高置信度密钥（强特征前缀；误报率接近零）
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS Access Key ID", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub 令牌", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{22,})\b")),
    ("OpenAI 风格密钥", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("Stripe 生产密钥", re.compile(r"\bsk_live_[A-Za-z0-9]{20,}\b")),
    ("Slack 令牌", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API Key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("GitLab 令牌", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("npm 令牌", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("HuggingFace 令牌", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("SendGrid 密钥", re.compile(r"\bSG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}")),
    ("私钥块", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)

#: 通用赋值型（字段名 + 引号值，≥8 字符）
GENERIC_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd|access[_-]?key"
    r"|private[_-]?key|client[_-]?secret)\b\s*[:=]\s*[\"']([^\"']{8,})[\"']"
)
#: shell 风格无引号赋值（旧体系完全漏掉这一类）
SHELL_SECRET_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:API|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL)[A-Z0-9_]*)=([A-Za-z0-9_+/=-]{12,})"
)

#: 占位/样例值（命中即不报；对**所有**分支生效——旧体系只对通用赋值分支去噪，
#: 结果 AWS 官方文档里的 AKIAIOSFODNN7EXAMPLE 会被判成真实密钥）
PLACEHOLDER_MARKERS = (
    "example", "sample", "placeholder", "changeme", "change-me", "dummy", "fake",
    "redacted", "your_", "your-", "xxxx", "todo", "tbd", "not-a-real", "<", ">",
    "insert", "abcdef123456",
)

#: 熵扫描的 token 形态
ENTROPY_TOKEN_RE = re.compile(r"[A-Za-z0-9+/=_\-]{20,}")
ENTROPY_MIN = 4.5
ENTROPY_MAX_TOKEN = 200

DL_EXEC_RE = re.compile(
    r"(?:curl|wget)\b[^\n]{0,200}(?:\|\s*(?:sudo\s+)?(?:ba|z)?sh\b|&&\s*(?:ba)?sh\b)"
    r"|\b(?:iwr|Invoke-WebRequest)\b[^\n]{0,200}\|\s*(?:iex|Invoke-Expression)\b",
    re.I,
)
OBFUSCATION_RE = re.compile(
    r"(?:eval|exec)\s*\(\s*base64\.b64decode"
    r"|eval\s+\"?\$?\(?\s*echo\s+\S+\s*\|\s*base64"
    r"|FromBase64String\s*\([^\n]{0,120}\)\s*\)?\s*\|\s*(?:iex|Invoke-Expression)"
    r"|\beval\s*\(\s*atob\s*\("
    r"|\bnew\s+Function\s*\(\s*atob\s*\(",
    re.I,
)
#: 任意 scheme 都算（凭据进 URL 就是进日志，与协议无关）
_URL_SCHEME = r"[a-z][a-z0-9+.\-]*://"
EXFIL_URL_RE = re.compile(
    # query 里带凭据字段
    _URL_SCHEME + r"\S+[?&](?:token|apikey|api_key|access_key|password|passwd|"
    r"secret|auth|session)="
    # 或 URL 的 userinfo 里直接写 `user:password@host`
    r"|" + _URL_SCHEME + r"[^\s/?#@]+:[^\s/?#@]+@",
    re.I,
)
#: 常见公共端点（无需声明；只覆盖"引用文档/包仓库"这类噪音源）
DEFAULT_ALLOWED_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "0.0.0.0", "::1", "example.com", "example.org",
     "schemas.android.com", "www.w3.org", "w3.org", "json-schema.org",
     "pypi.org", "files.pythonhosted.org", "python.org", "docs.python.org",
     "peps.python.org", "github.com", "raw.githubusercontent.com", "api.github.com",
     "npmjs.com", "registry.npmjs.org", "nodejs.org", "deno.land", "jsr.io",
     "bun.sh", "rubygems.org", "agentskills.io", "creativecommons.org",
     "opensource.org", "apache.org", "gnu.org"}
)


def _is_placeholder(value: str) -> bool:
    low = value.lower()
    return any(marker in low for marker in PLACEHOLDER_MARKERS)


def _scan_secrets(ctx: LintContext) -> tuple[list[str], list[str], list[str]]:
    """返回 (高置信度命中, 通用赋值命中, 熵命中)；同一行只报一次（按严重度优先）。"""
    strong: list[str] = []
    generic: list[str] = []
    entropy: list[str] = []
    for rec in ctx.inventory.texts:
        for lineno, line in enumerate((rec.text or "").split("\n"), 1):
            hit_strong = False
            for label, pattern in SECRET_PATTERNS:
                for match in pattern.finditer(line):
                    value = match.group(0)
                    if _is_placeholder(value):
                        continue
                    strong.append(f"{rec.rp}:{lineno} [{label}] {mask_secret(value)}")
                    hit_strong = True
            if hit_strong:
                continue
            hit_generic = False
            for match in GENERIC_SECRET_RE.finditer(line):
                if _is_placeholder(match.group(2)):
                    continue
                generic.append(
                    f"{rec.rp}:{lineno} {match.group(1)}={mask_secret(match.group(2))}")
                hit_generic = True
            if not hit_generic:
                for match in SHELL_SECRET_RE.finditer(line):
                    if _is_placeholder(match.group(2)):
                        continue
                    generic.append(
                        f"{rec.rp}:{lineno} {match.group(1)}={mask_secret(match.group(2))}")
                    hit_generic = True
            if hit_generic:
                continue
            for match in ENTROPY_TOKEN_RE.finditer(line):
                token = match.group(0)
                if len(token) > ENTROPY_MAX_TOKEN or "://" in token:
                    continue
                if _is_placeholder(token) or len(set(token)) < 8:
                    continue
                if shannon_entropy(token) >= ENTROPY_MIN:
                    entropy.append(f"{rec.rp}:{lineno} {mask_secret(token)}")
                    break
    return strong, generic, entropy


def _scan_patterns(ctx: LintContext) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {"dl": [], "obf": [], "exfil": []}
    for rec in ctx.inventory.texts:
        for lineno, line in enumerate((rec.text or "").split("\n"), 1):
            if DL_EXEC_RE.search(line):
                buckets["dl"].append(f"{rec.rp}:{lineno}")
            if OBFUSCATION_RE.search(line):
                buckets["obf"].append(f"{rec.rp}:{lineno}")
            if EXFIL_URL_RE.search(line):
                buckets["exfil"].append(f"{rec.rp}:{lineno}")
    return buckets


#: 从 frontmatter 里抠出"声明过的外部主机"（声明是散文，所以按形态提取而不是整段子串比对）
DECLARED_HOST_RE = re.compile(r"[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}")


def _declared_hosts(ctx: LintContext) -> set[str]:
    """frontmatter/正文里出现过的外部主机名（小写）。

    早先的实现是 `host in declared`——**整段子串匹配**：声明了 `example.com` 而代码里写
    `api.example.com` 会被判成"未声明"（误报），而声明里随便出现过的字符串又会放过一切。
    这里改成先提取候选主机，再按**域名边界**比较（相等或其子域）。
    """
    text = (ctx.meta_text() or "").lower()
    return {match.group(0).strip(".") for match in DECLARED_HOST_RE.finditer(text)}


def _host_allowed(host: str, allowed: set[str]) -> bool:
    """相等，或是某个已声明主机的子域（`api.example.com` ⊆ `example.com`；反之不成立）。"""
    return any(host == base or host.endswith("." + base) for base in allowed if base)


def _scan_endpoints(ctx: LintContext) -> list[str]:
    """代码文件里出现、且未在 frontmatter 中声明的外部主机（按主机去重）。"""
    allowed = set(DEFAULT_ALLOWED_HOSTS) | _declared_hosts(ctx)
    found: dict[str, str] = {}
    for rec in ctx.inventory.texts:
        if not rec.is_code:
            continue
        for match in URL_RE.finditer(rec.text or ""):
            url = match.group(0)
            host = re.sub(r"^\w+://", "", url).split("/")[0].split(":")[0].lower()
            if not host or _host_allowed(host, allowed):
                continue
            found.setdefault(host, f"{rec.rp}: {host}")
    return sorted(found.values())


@dataclass
class SecurityFacts:
    """安全扫描的**结构化事实**（供规则与 audit 共用，不是从证据文本里抠的）。"""

    strong_secrets: list[str]      # 高置信度密钥/私钥命中
    credential_urls: list[str]     # URL 里携带凭据参数（SEC-006）
    endpoints: list[str]           # 包内出现的网络端点（SEC-007 的扫描结果）


def facts(ctx: LintContext) -> SecurityFacts:
    """把安全扫描的事实暴露成结构：规则用它拼证据，audit 直接消费它。"""
    strong, _generic, _entropy = _scan_secrets(ctx)
    return SecurityFacts(
        strong_secrets=strong,
        credential_urls=_scan_patterns(ctx)["exfil"],
        endpoints=_scan_endpoints(ctx),
    )


#: 双向控制符（Trojan Source 形态：让同一段内容「读起来」与「实际执行」不一致）
BIDI_RE = re.compile("[\u202a-\u202e\u2066-\u2069]")
#: 其它不可见字符。**故意不含 U+200D（ZWJ）**——emoji 序列里它是合法的。
INVISIBLE_RE = re.compile("[\u200b\u200c\u200e\u200f\u2060-\u2064\ufeff]")


def _scan_invisible(ctx: LintContext) -> tuple[list[str], list[str]]:
    """扫隐藏字符：返回 (双向控制符命中, 其它不可见字符命中)。"""
    bidi: list[str] = []
    invisible: list[str] = []
    for rec in ctx.inventory.texts:
        # 开头的 U+FEFF 是「文件带 BOM」——那归编码规则（ENC-003）管；
        # 这里只找**内容中间**的隐藏字符（隐写的判断依据是"藏在不该出现的地方"）。
        text = (rec.text or "").lstrip("\ufeff")
        for idx, line in enumerate(text.splitlines(), 1):
            for match in BIDI_RE.finditer(line):
                bidi.append(f"{rec.rp}:{idx} U+{ord(match.group(0)):04X}")
            for match in INVISIBLE_RE.finditer(line):
                invisible.append(f"{rec.rp}:{idx} U+{ord(match.group(0)):04X}")
    return bidi, invisible


def check(ctx: LintContext) -> list[Result]:
    out: list[Result] = []
    strong, generic, entropy = _scan_secrets(ctx)

    if strong:
        out.append(res(RULES["SEC-001"], FAIL, f"疑似真实密钥/私钥: {summarize(strong)}"))
    else:
        out.append(res(RULES["SEC-001"], PASS, "未命中高置信度密钥特征"))

    if generic:
        out.append(res(RULES["SEC-002"], WARN,
                       f"赋值形式的疑似凭据（须人工确认）: {summarize(generic)}"))
    else:
        out.append(res(RULES["SEC-002"], PASS, "未命中赋值形式的凭据"))

    if entropy:
        out.append(res(RULES["SEC-003"], WARN,
                       f"高熵字符串（熵 ≥{ENTROPY_MIN}，须人工确认）: {summarize(entropy)}"))
    else:
        out.append(res(RULES["SEC-003"], PASS, f"未命中高熵字符串（≥{ENTROPY_MIN} 且长度 ≥20）"))

    buckets = _scan_patterns(ctx)
    if buckets["dl"]:
        out.append(res(RULES["SEC-004"], WARN, f"下载即执行: {summarize(buckets['dl'])}"))
    else:
        out.append(res(RULES["SEC-004"], PASS, "无「下载即执行」链"))

    if buckets["obf"]:
        out.append(res(RULES["SEC-005"], WARN,
                       f"混淆式动态执行（base64+eval/exec）: {summarize(buckets['obf'])}"))
    else:
        out.append(res(RULES["SEC-005"], PASS, "无 base64+eval/exec 形态"))

    if buckets["exfil"]:
        out.append(res(RULES["SEC-006"], WARN,
                       f"URL 携带凭据参数: {summarize(buckets['exfil'])}"))
    else:
        out.append(res(RULES["SEC-006"], PASS, "无 URL 携带凭据参数"))

    # ---- SEC-008：隐藏字符 / 隐写注入 ----
    bidi, invisible = _scan_invisible(ctx)
    # 发现隐藏字符时**必须**把语义侧拉进来：机械层只能证明「有隐藏字符」，
    # 证明不了「它是不是在向 Agent 下指令」——那正是 W-17（指令注入）要判的。
    hint = "；这类内容一律按不可信处理，并务必跑语义评审的 W-17（指令注入）"
    if bidi:
        # 双向控制符在技能内容里没有正当用途，在代码里等于 Trojan Source → 客观缺陷
        out.append(res(RULES["SEC-008"], FAIL,
                       f"发现双向控制符（可让内容看起来与实际不一致）: {summarize(bidi)}{hint}"))
    elif invisible:
        out.append(res(RULES["SEC-008"], WARN,
                       f"发现不可见字符（可能是隐写或误贴）: {summarize(invisible)}{hint}"))
    else:
        out.append(res(RULES["SEC-008"], PASS, "未发现双向控制符或不可见字符"))

    if not any(rec.is_code for rec in ctx.inventory.texts):
        out.append(res(RULES["SEC-007"], INFO, "不适用：包内无代码文件"))
    else:
        endpoints = _scan_endpoints(ctx)
        if endpoints:
            out.append(res(RULES["SEC-007"], WARN,
                           f"代码中未声明的外部端点（仅作提示，声明≠可信）: "
                           f"{summarize(endpoints)}"))
        else:
            out.append(res(RULES["SEC-007"], PASS, "代码中的外部端点均已声明或属公共端点"))

    return out
