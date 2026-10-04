#!/usr/bin/env python3
"""w_static_lint.py — 编写期静态补检器（S 工具链，L-1~L-18）。

落实《验证补全工程·跨会话任务书》甲档工具一：编写期（write 阶段）静态补检
18 项。检查项编号 L-1~L-18 为工具本地编号（V1–V29、A1–A11、DEP/EX 均已占用）；
方案条目映射（V14/§1.8/§2.1.3/…）见任务书 §一甲档表。

定位（与既有工具分工）:
  - check_skill.py（A 门）覆盖 SKILL.md 自身形态；本工具补编写期静态项
    （全包卫生、frontmatter 深检、引用链二层层深、i18n 启发式、行数漂移等）。
  - 语义终判项不落本工具：LL-1~LL-8 归乙档 LLM 列表（W 组评审承担）。
  - L-17/L-18 为机械半初筛（WARN），终判归 LLM/人工（LL-2/LL-6）。

版本: v1.1（2026-10-03 第 5 步独立自查轮）—
      ①L-7 链图分支失真修复（chain 在 ref2 循环内累积，一文档引 2 个二层文件
        时兄弟分支被串成假链 "a.md → b.md → c.md"——链图系人工复核证据，改
        per-branch 输出）；
      ②L-15/L-17 行号修正（原在剥 frontmatter 后的 body 上 enumerate 却以
        "SKILL.md:N" 报告，行号系正文相对值非文件真实行号，人工核对扑空——
        补 frontmatter 行偏移）；
      ③判定统计口径对齐 eval_artifacts_check v1.0.1（PASS/FAIL 分母明示 +
        WARN/SKIP/INFO 单独计数）。
      v1.0.1（2026-10-03 首轮外部评审处置，2 P0 + 6 一致性 + 8 覆盖缺口全采纳；
      另 1 条考证不采纳：n_binary"二进制跳过"计数语义与报告头措辞一致——二进制
      文件确实不参与内容扫描）—
      ①L-5 内联/嵌套数组"引号先剥后判"假阳性修复（"1.0"/"true" 引号形式系
        YAML str 合规写法，改 _nonstr_item 先判引号再判裸值）；
      ②L-12 补 is_binary 过滤（此前 is_binary 仅计数未使用，含 0x0D 的素材类
        二进制文件被误判 CR → FAIL，假阳性落在阻断级）；
      ③L-14 补扫 frontmatter 缩进叶值（多行 metadata 的 CJK 值经 kv 顶层行内值
        收集时为空串被过滤，此前漏检）；
      ④L-3 空/缺失 frontmatter（---\n--- 形态 split 落空）由静默 PASS 改 WARN
        早发现 + 重复键 dict.fromkeys 去重保序；
      ⑤--host 词条回显保原始大小写（原 main 预 lowercase 使标签恒小写）；
      ⑥L-7 docstring 扫描面措辞修正（围栏外 SKILL.md 全文，含 frontmatter——
        frontmatter 内 references/ 引用同为真实路径引用，纳入扫描系设计非缺陷）；
      ⑦测试 21→28 组：补 L-5 引号数组 / L-12 二进制 / L-11 默认黑名单+--host /
        L-16 旧式 SKIP 与 snapshot JSON 形态 / L-9 超限 / L-13 无规则 / L-2 特许名 /
        L-3 空 frontmatter / L-14 多行 CJK / L-3 重复键去重回归。

检查项（L 系）:
  L-1  同义变体目录名      技能根出现 docs/utils/lib/helpers/doc/misc → FAIL（V14）
  L-2  无关文件            __pycache__/*.pyc/.DS_Store/Thumbs.db/*.tmp/*.log → FAIL；
                           扩展名白名单（.py/.md/.json/.txt/.yaml/.yml/.toml/.cfg/.ini/
                           .sh/.js + 素材类〔assets/ 标准承载〕+ LICENSE/.git* 特许名）
                           外 → WARN；单文件 >1MB → WARN（§1.8）
  L-3  frontmatter 顶层键  官方解析器允许集 name/description/license/compatibility/
                           metadata/allowed-tools 之外的顶层键 → FAIL（§2.1.3）
  L-4  跨行 plain scalar   frontmatter 值含 |/ > 块标量或跨行未闭合形态 → FAIL（§2.3.8）
  L-5  metadata 值类型     叶值须为 str 或 str 数组；裸数字/布尔/内联 dict 数字值 → FAIL（§2.6.1）
  L-6  allowed-tools 格式  空格/逗号分隔 tool 名形态 → 不合规 WARN（§2.7.1）
  L-7  引用深度            二级引用扫描：A8 已检一层，此处补第二层与链图输出；
                           链断 → FAIL，深度 >2 层 → WARN（§3）。
                           扫描面=代码围栏外 SKILL.md 全文（含 frontmatter——其中
                           references/ 引用同为真实路径引用，纳入扫描系设计）；
                           围栏内用法示例/占位路径非引用链；
                           二层下钻仅对 .md/.txt 文档类目标（代码内引用归 DEP-5）
  L-8  Gotchas 节          SKILL.md 标题含 Gotchas/陷阱/注意事项任一 → 缺失 WARN（§5.5.1）
  L-9  templates/assets    templates/ 单文件 >300 行（模板内联超限）→ WARN；
                           素材类扩展名置于 assets/ 外 → WARN（§5.5.6）
  L-10 全包宿主路径        全包文本扫 ~/、$HOME、盘符路径（A8 仅 SKILL.md，此处扩全包）
                           → FAIL（§10.1）
  L-11 宿主专属黑名单      宿主专属路径/工具名 → WARN（--host 增补黑名单词；默认通用）（§10.2）
  L-12 全包 LF + 无 BOM    A7/X1 仅 SKILL.md，此处扩全包（二进制跳过）→ FAIL（§10.3/§10.4）
  L-13 .gitattributes      存在且含 eol=lf 类规则行 → 缺失/无规则 WARN（§10.6）
  L-14 i18n 混入           description 全英文而其余 frontmatter 值含 CJK → WARN（§11.1）
  L-15 代码块命令混译      SKILL.md code fence 内命令行形态混入 CJK → WARN（§11.2）
  L-16 行数漂移            SKILL.md 哈希 vs .verification/.iteration-baseline 记录：
                           不一致 → WARN（告知 V27 拆分复核义务）；基线无 SKILL.md
                           哈希记录 → SKIP；无基线 → INFO（V27 机械半）
  L-17 笼统指引初筛        "详见 references/" 后无具体文件名、孤立"更多示例"无路径
                           → WARN（语义终判归 LL-2）（§4.1.7 机械半）
  L-18 恶意特征初筛        下载执行链（curl|wget→sh）/eval+base64 混淆/凭据外传 URL
                           → WARN（终判归 LL-6）（§9.1 机械半）

用法:
    python w_static_lint.py <skill_dir>                  # 静态补检单个技能
    python w_static_lint.py <skill_dir> --out report.md  # 同时落盘报告
    python w_static_lint.py <skill_dir> --host workbuddy # 增补宿主专属黑名单词（逗号分隔）

退出码: 0=全 PASS/INFO；1=任一 FAIL；2=无 FAIL 但有 WARN。SKIP 不计警告。

局限（显式声明）:
  - L-4/L-5 为 YAML 子集启发式（行级解析，不支持锚点/流式嵌套深层形态），
    解析不了的结构不误判，交 A1 官方 validate 兜底。
  - L-7 链断判定对"代码块内用法示例"同样生效（与 A8 的存在性旁证口径不同：
    本工具按任务书判 FAIL，示例性引用应改写为不含真实路径的占位形态）。
  - L-10/L-11/L-18 为文本级匹配，宁可误报不漏报，命中须人工复核。
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

VERSION = "v1.1"
MAX_SCAN_BYTES = 2 * 1024 * 1024    # 内容扫描上限（对齐 security_scan 口径）
BIG_FILE_BYTES = 1 * 1024 * 1024    # L-2 单文件体积阈值（§1.8）
TEMPLATE_LINE_LIMIT = 300           # L-9 模板内联行数上限（对齐 A6 项目收紧线）
SKIP_DIRS = {".git", ".verification", "node_modules", ".venv", "venv"}
# 注意：__pycache__ 不入 SKIP_DIRS——它本身是 L-2 的检查对象（垃圾文件）

FORBIDDEN_DIRS = {"docs", "utils", "lib", "helpers", "doc", "misc"}  # L-1（V14）

FM_TOP_KEYS = {"name", "description", "license", "compatibility",
               "metadata", "allowed-tools"}  # L-3（§2.1.3 官方解析器允许集）

ALLOWED_EXTS = {".py", ".md", ".json", ".txt", ".yaml", ".yml", ".toml",
                ".cfg", ".ini", ".sh", ".js"}  # L-2 扩展名白名单（§1.8）
SPECIAL_NAMES = {"license", "license.txt", "license.md", "notice",
                 ".gitignore", ".gitattributes", "makefile", "dockerfile"}

JUNK_FILE_RE = re.compile(
    r"(?:^|/)(?:__pycache__|\.DS_Store|Thumbs\.db)$"
    r"|\\(?:__pycache__|\.DS_Store|Thumbs\.db)$"
    r"|\\[^\\/]*\.(?:pyc|tmp|log)$"
    r"|/[^/]*\.(?:pyc|tmp|log)$", re.I)

ASSET_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
              ".pdf", ".zip", ".mp3", ".mp4", ".woff", ".woff2", ".ttf"}

TOP_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)[ \t]*:")
NUMBER_BOOL_RE = re.compile(r"-?\d+(?:\.\d+)?|true|false|null|yes|no|on|off", re.I)

# L-7 引用形态（一层口径与 A8 一致；二层补 templates/）
REF_PAT = re.compile(r"(?:references|scripts|assets|evals|templates)/[\w./-]+")
URL_RE = re.compile(r"(?:https?|file)://\S+")

# L-10 宿主绝对路径（§10.1）——~ 限定 ~/、~\ 形态（裸 ~ 出现在"约~3"类文本不算，
# 宁缺勿滥：误报盘符/家目录路径以外的普通文本会把本工具变成噪音源）
HOSTPATH_RE = re.compile(
    r"(?<![\w.])~[/\\]"
    r"|\$\{?(?:HOME|USERPROFILE|HOMEPATH)\}?"
    r"|(?<![\w.])[A-Za-z]:[\\/][^\s`'\"<>\)\]]")

# L-11 宿主专属黑名单（默认通用集；§10.2）
HOST_SPECIFIC_DEFAULT = {
    ".workbuddy": "WorkBuddy 工作区",
    ".claude": "Claude 配置",
    ".cursor": "Cursor 配置",
    "workbuddy.cn": "WorkBuddy 服务域",
    "claude.ai": "Claude 服务域",
    "codebuddy": "CodeBuddy",
}

# L-15 代码块内命令行形态（§11.2）
CMD_LINE_RE = re.compile(
    r"^\s*(?:\$\s*|>\s*|PS [A-Za-z]:\\>\s*)?"
    r"(?:pip3?|npm|npx|pnpm|yarn|uvx?|python3?|node|deno|bun|git|curl|wget|"
    r"bash|sh\b|cd\b|ls\b|mkdir|rm\b|cp\b|mv\b|docker|kubectl)\b")
CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

# L-17 笼统指引初筛（§4.1.7 机械半；语义终判归 LL-2）
VAGUE_REFS_RE = re.compile(
    r"(?:详见|参见|参考)\s*references/\s*(?![\w./-]+\.(?:md|txt|py|json))")
VAGUE_MORE_RE = re.compile(r"更多示例")

# L-18 恶意特征初筛（§9.1 机械半；终判归 LL-6）
DL_EXEC_RE = re.compile(
    r"(?:curl|wget)\b[^\n]{0,200}(?:\|\s*(?:sudo\s+)?(?:ba|z)?sh\b|&&\s*(?:ba)?sh\b)")
EVAL_B64_RE = re.compile(
    r"(?:eval|exec)\s*\(\s*base64\.b64decode"
    r"|eval\s+\"?\$?\(?\s*echo\s+\S+\s*\|\s*base64")
EXFIL_URL_RE = re.compile(
    r"https?://\S+[?&](?:token|apikey|api_key|access_key|password|secret|auth)=\S+",
    re.I)


class _BlockArgParser(argparse.ArgumentParser):
    """参数错误统一 exit 1（阻断码）——argparse 默认 exit 2 撞 WARN 码
    （家族纪律：naming_precheck v1.0.1 评审 5 起 error() 覆写口径全工具对齐）。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"错误: {message}。下一步: 按用法核对参数后重试。", file=sys.stderr)
        raise SystemExit(1)


def _ev(text: str) -> str:
    """证据净化：报告为 markdown 表格，竖线/换行会破坏行结构。"""
    return (str(text).replace("|", "｜").replace("\r\n", " ")
            .replace("\n", " ").replace("\r", " "))


# ------------------------------------------------------------- 文件清单 ----

class FileRec:
    """单个包内文件的扫描记录。"""
    __slots__ = ("rel", "path", "size", "is_binary", "text", "raw", "read_err")

    def __init__(self, rel: Path, path: Path) -> None:
        self.rel = rel
        self.path = path
        self.size = -1
        self.is_binary = False
        self.text: str | None = None
        self.raw: bytes | None = None
        self.read_err = ""


def build_inventory(skill_dir: Path) -> tuple[list[FileRec], int, int]:
    """包内文件清单。返回 (记录列表, 二进制跳过数, 读取失败数)。

    is_symlink() 前置（家族纪律——is_file() 会跟随符号链接，扫描范围蔓延）。
    >MAX_SCAN_BYTES 只做体积类检查，不做内容扫描（超限数由调用方按 size 判）。
    """
    recs: list[FileRec] = []
    n_read_err = 0
    for p in sorted(skill_dir.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        rel = p.relative_to(skill_dir)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        rec = FileRec(rel, p)
        try:
            rec.size = p.stat().st_size
        except OSError as e:
            rec.read_err = f"stat 失败（{e.strerror or e}）"
            n_read_err += 1
            recs.append(rec)
            continue
        if rec.size > MAX_SCAN_BYTES:
            recs.append(rec)  # 只做体积类检查
            continue
        try:
            rec.raw = p.read_bytes()
        except OSError as e:
            rec.read_err = f"读取失败（{e.strerror or e}）"
            n_read_err += 1
            recs.append(rec)
            continue
        # 二进制探测：NUL 字节 sniff（家族纪律：本工具扩 security_scan 的
        # 扩展名黑名单为内容嗅探，未知扩展名的二进制文件不再误扫）
        rec.is_binary = b"\x00" in rec.raw[:8192]
        if not rec.is_binary:
            # 读码一律 utf-8-sig（家族纪律；BOM 剥除交 L-12 按裸字节判定）
            rec.text = rec.raw.decode("utf-8-sig", errors="replace")
        recs.append(rec)
    n_binary = sum(1 for r in recs if r.is_binary)
    return recs, n_binary, n_read_err


# ---------------------------------------------------------- frontmatter ----

def split_frontmatter(text: str) -> tuple[str | None, str]:
    """拆 frontmatter。返回 (块文本或 None, 去头正文)。"""
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", text, re.S)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def top_keys(fm_block: str) -> list[tuple[str, str]]:
    """顶层键序列 [(key, 行内值)]——只认列 0 键行（缩进行属多行值/列表/嵌套）。"""
    out: list[tuple[str, str]] = []
    for ln in fm_block.split("\n"):
        m = TOP_KEY_RE.match(ln)
        if m:
            out.append((m.group(1), ln.split(":", 1)[1].strip()))
    return out


# ------------------------------------------------------------- 检查主体 ----

def strip_fences(text: str) -> str:
    """剥代码围栏内容（围栏行置空保行号）：围栏内是用法示例/占位路径，
    不是真实引用链——实弹考证（llm-review SKILL.md:68 `scripts/foo.py`
    系 dep_check 历轮已甄别过的调用示例占位路径）后收窄扫描面。"""
    out: list[str] = []
    in_fence = False
    for ln in text.split("\n"):
        if ln.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else ln)
    return "\n".join(out)


def _nonstr_item(raw: str) -> bool:
    """裸 token 才判数字/布尔；带引号形式（"1.0"、"true"）按 YAML 语义是 str，
    系 §2.6.1 合规写法——先剥引号再判定会把引号 str 误判为数字/布尔
    （v1.0.1 评审 Bug 1：单值分支本先判引号，仅两处数组分支中招）。"""
    t = raw.strip()
    if t[:1] in "\"'":
        return False
    return bool(NUMBER_BOOL_RE.fullmatch(t))


def run_checks(skill_dir: Path, recs: list[FileRec], host_extra: list[str]
               ) -> list[dict]:
    rows: list[dict] = []

    def add(lid: str, title: str, level: str, ev: str) -> None:
        rows.append(dict(lid=lid, title=title, level=level, ev=_ev(ev)))

    skill_md = next((r for r in recs if r.rel.as_posix() == "SKILL.md"), None)
    fm_text = skill_md.text if skill_md and skill_md.text is not None else ""
    fm_block, body = split_frontmatter(fm_text)
    fm_lines = fm_block.split("\n") if fm_block is not None else []
    # v1.1 自查②：body 系剥 frontmatter 后文本，body 内 enumerate 行号须加
    # frontmatter 偏移才是 SKILL.md 文件真实行号（L-15/L-17 证据用）
    body_line_off = fm_text[:len(fm_text) - len(body)].count("\n")
    keys = top_keys(fm_block) if fm_block is not None else []
    kv = {k: v for k, v in keys}

    # ---- L-1 同义变体目录名黑名单（V14）----
    bad_dirs = sorted({r.rel.parts[0] for r in recs
                       if len(r.rel.parts) > 1 and r.rel.parts[0].lower() in FORBIDDEN_DIRS})
    add("L-1", "同义变体目录名黑名单（docs/utils/lib/helpers/doc/misc）",
        "FAIL" if bad_dirs else "PASS",
        f"检出禁用目录: {', '.join(bad_dirs)}（V14：改用 references/scripts/assets 标准承载）"
        if bad_dirs else "技能根无禁用目录名")

    # ---- L-2 无关文件（§1.8）----
    junk: list[str] = []
    wrong_ext: list[str] = []
    oversized: list[str] = []
    for r in recs:
        rp = r.rel.as_posix()
        if JUNK_FILE_RE.search(rp):
            junk.append(rp)
            continue
        ext = r.rel.suffix.lower()
        if ext not in ALLOWED_EXTS and ext not in ASSET_EXTS \
                and r.rel.name.lower() not in SPECIAL_NAMES:
            wrong_ext.append(rp)
        if r.size > BIG_FILE_BYTES:
            oversized.append(f"{rp}（{r.size // 1024}KB）")
    l2_bad: list[str] = []
    if junk:
        l2_bad.append(f"垃圾文件: {', '.join(junk[:6])}" + ("…" if len(junk) > 6 else ""))
    l2_level = "FAIL" if junk else ("WARN" if (wrong_ext or oversized) else "PASS")
    if wrong_ext:
        l2_bad.append(f"白名单外扩展名（人工确认归置）: {', '.join(wrong_ext[:6])}"
                      + ("…" if len(wrong_ext) > 6 else ""))
    if oversized:
        l2_bad.append(f"单文件 >1MB: {', '.join(oversized[:4])}")
    add("L-2", "无关文件/白名单外/体积", l2_level,
        "; ".join(l2_bad) if l2_bad else f"全包 {len(recs)} 文件均在白名单与体积阈内")

    # ---- L-3 frontmatter 顶层键白名单（§2.1.3）----
    # v1.0.1 评审 2.6：重复键 dict.fromkeys 去重保序（YAML 后键覆盖前键，重复列举误导）
    unknown = list(dict.fromkeys(k for k, _ in keys if k not in FM_TOP_KEYS))
    if fm_block is None:
        # v1.0.1 评审 2.4：空 frontmatter（---\n---）等形态 split 落空，原先静默 PASS
        add("L-3", "frontmatter 顶层键白名单", "WARN",
            "未解析到 frontmatter 区块（首部无 --- 界定或空区块）——键白名单不可验，"
            "A1 官方 validate 兜底；若确无 frontmatter 属编写期早发现")
    else:
        add("L-3", "frontmatter 顶层键白名单",
            "FAIL" if unknown else "PASS",
            f"官方允许集外的顶层键: {', '.join(unknown)}（§2.1.3：官方解析器将拒绝或忽略）"
            if unknown else f"顶层键 {sorted(kv) or '（空）'} 全在允许集")

    # ---- L-4 跨行 plain scalar / 块标量（§2.3.8）----
    l4_hits: list[str] = []
    for i, ln in enumerate(fm_lines):
        m = TOP_KEY_RE.match(ln)
        if not m:
            continue
        val = ln.split(":", 1)[1].strip()
        j = i + 1
        while j < len(fm_lines) and not fm_lines[j].strip():
            j += 1
        nxt = fm_lines[j] if j < len(fm_lines) else None
        indented = bool(nxt) and nxt[:1] in (" ", "\t")
        is_list = bool(nxt) and re.match(r"^[ \t]+-\s", nxt) is not None
        is_nest = bool(nxt) and re.match(r"^[ \t]+[A-Za-z][\w-]*[ \t]*:", nxt) is not None
        if re.match(r"^[|>][+-]?\d*[ \t]*$", val):
            l4_hits.append(f"{m.group(1)}: 块标量（{val}）形态")
        elif val == "" and indented and not is_list and not is_nest:
            l4_hits.append(f"{m.group(1)}: 空值后跟跨行 plain scalar")
        elif val and indented and not is_list and not is_nest:
            l4_hits.append(f"{m.group(1)}: 跨行未闭合 plain scalar")
    add("L-4", "frontmatter 块标量/跨行 plain scalar", "FAIL" if l4_hits else "PASS",
        "; ".join(l4_hits) + "（§2.3.8：官方解析器按单行标量解析，跨行形态语义丢失）"
        if l4_hits else "全部值为单行标量/合法列表/嵌套映射")

    # ---- L-5 metadata 值类型（§2.6.1）----
    if "metadata" not in kv:
        add("L-5", "metadata 值类型（str 或 str 数组）", "PASS", "未声明 metadata（允许缺省）")
    else:
        meta_inline = kv["metadata"]
        bad5: list[str] = []
        if meta_inline.startswith("{"):
            if re.search(r"[{,]\s*[\w.-]+\s*:\s*(?:-?\d|true|false|null)\s*[,}]",
                         meta_inline, re.I):
                bad5.append(f"内联 dict 含非 str 值: {meta_inline[:60]}")
        elif meta_inline.startswith("["):
            items = [x.strip() for x in meta_inline[1:-1].split(",") if x.strip()]
            bad = [x for x in items if _nonstr_item(x)]
            if bad:
                bad5.append(f"内联数组含非 str 项: {', '.join(bad)}")
        else:
            meta_idx = next((i for i, ln in enumerate(fm_lines)
                             if TOP_KEY_RE.match(ln)
                             and ln.split(":", 1)[0].strip() == "metadata"), None)
            if meta_idx is not None:
                for cl in fm_lines[meta_idx + 1:]:
                    if TOP_KEY_RE.match(cl):
                        break  # 到下一个顶层键为止
                    cm = re.match(r"^[ \t]+([\w.-]+)[ \t]*:[ \t]*(.+?)[ \t]*$", cl)
                    if not cm:
                        continue  # 嵌套块头/列表项/注释
                    v = cm.group(2)
                    if v.startswith("{"):
                        bad5.append(f"{cm.group(1)}: 内联 dict（应展开为映射）")
                    elif v.startswith("["):
                        items = [x.strip() for x in v[1:-1].split(",") if x.strip()]
                        if any(_nonstr_item(x) for x in items):
                            bad5.append(f"{cm.group(1)}: 数组含非 str 项")
                    elif v[:1] in "\"'":
                        continue  # 带引号 str
                    elif NUMBER_BOOL_RE.fullmatch(v):
                        bad5.append(f"{cm.group(1)}: 裸值 {v!r} 解析为数字/布尔（须加引号）")
        add("L-5", "metadata 值类型（str 或 str 数组）", "FAIL" if bad5 else "PASS",
            "; ".join(bad5) + "（§2.6.1：官方解析器仅接受 str/str 数组）"
            if bad5 else "metadata 叶值均为 str 形态")

    # ---- L-6 allowed-tools 格式（§2.7.1）----
    at = kv.get("allowed-tools", "")
    if not at:
        add("L-6", "allowed-tools 格式（tool 名形态）", "PASS", "未声明（允许缺省）")
    else:
        tokens = [t for t in re.split(r"[,\s]+", at) if t]
        tool_re = re.compile(r"^(?:mcp__[\w-]+(?:__[\w-]+)+"
                             r"|[A-Za-z][\w-]*(?:\([\w*:./, -]*\))?)$")
        bad_toks = [t for t in tokens if not tool_re.match(t)]
        add("L-6", "allowed-tools 格式（tool 名形态）", "WARN" if bad_toks else "PASS",
            f"非 tool 名形态的记号: {', '.join(bad_toks)}（§2.7.1：空格/逗号分隔的 tool 名）"
            if bad_toks else f"{len(tokens)} 个 tool 名形态合规")

    # ---- L-7 引用深度（§3：A8 一层已检，此处补第二层与链图）----
    l7_broken: list[str] = []
    l7_deep: list[str] = []
    l7_chains: list[str] = []
    # 引用提取后统一剥尾部句点：[\w./-]+ 会把句尾"."一起捕获（"See x.md."→"x.md."），
    # 且 Win32 路径解析剥尾部点会令 is_file() 误真，t1_rec 查找落空后静默跳过
    l1_refs = sorted({r.rstrip(".") for r in
                      REF_PAT.findall(URL_RE.sub("", strip_fences(fm_text)))})
    for ref in l1_refs:
        t1 = skill_dir / ref
        chain = f"SKILL.md → {ref}"
        if not t1.is_file():
            l7_broken.append(f"一层引用断链: {ref}")
            continue
        t1_rec = next((r for r in recs if r.path == t1), None)
        # 二层下钻只对文档类目标有意义：代码内引用（import/调用）归 dep_check
        # DEP-5 管辖，脚本 docstring 里的用法示例不是"引用链"
        if t1_rec is None or t1_rec.text is None or t1.suffix.lower() not in (".md", ".txt"):
            l7_chains.append(chain)
            continue
        # v1.1 自查①：chain 在 ref2 循环内累积会把兄弟分支串成假链
        # （"a.md → b.md → c.md"）——改 per-branch 输出
        l2_refs = sorted({r.rstrip(".") for r in
                          REF_PAT.findall(URL_RE.sub("", strip_fences(t1_rec.text)))})
        if not l2_refs:
            l7_chains.append(chain)
            continue
        for ref2 in l2_refs:
            t2 = (skill_dir / ref2) if (skill_dir / ref2).is_file() \
                else (t1.parent / ref2)
            branch = f"{chain} → {ref2}"
            if not t2.is_file():
                l7_broken.append(f"二层引用断链: {ref} → {ref2}")
                continue
            t2_rec = next((r for r in recs if r.path == t2), None)
            if t2_rec is not None and t2_rec.text is not None \
                    and REF_PAT.search(URL_RE.sub("", t2_rec.text)):
                l7_deep.append(f"{ref} → {ref2} → …（三层及以上）")
            l7_chains.append(branch)
    l7_level = "FAIL" if l7_broken else ("WARN" if l7_deep else "PASS")
    l7_ev = "; ".join(l7_broken + l7_deep) if (l7_broken or l7_deep) \
        else f"{len(l1_refs)} 条一层引用链深 ≤2"
    if l7_chains:
        l7_ev += "；链图: " + " ｜ ".join(l7_chains[:6]) + ("…" if len(l7_chains) > 6 else "")
    add("L-7", "引用链二层扫描与深度", l7_level, l7_ev
        + ("（§3：>2 层须评估外移/改直链）" if l7_deep else ""))

    # ---- L-8 Gotchas 节（§5.5.1）----
    heads = [ln.lstrip("# \t") for ln in body.split("\n")
             if re.match(r"^#{1,6}\s+\S", ln)]
    has_gotcha = any(re.search(r"gotchas|陷阱|注意事项", h, re.I) for h in heads)
    add("L-8", "SKILL.md 含 Gotchas/陷阱/注意事项节", "PASS" if has_gotcha else "WARN",
        "标题命中: " + next(h for h in heads
                            if re.search(r"gotchas|陷阱|注意事项", h, re.I))[:40]
        if has_gotcha else "全文标题未命中 Gotchas/陷阱/注意事项（§5.5.1 建议补经验教训节）")

    # ---- L-9 templates/assets 归置（§5.5.6）----
    l9_hits: list[str] = []
    for r in recs:
        rp = r.rel.as_posix()
        if r.rel.parts[0] == "templates" and r.text is not None:
            n_lines = len(r.text.splitlines())
            if n_lines > TEMPLATE_LINE_LIMIT:
                l9_hits.append(f"{rp}: {n_lines} 行 > {TEMPLATE_LINE_LIMIT}（模板内联超限，"
                               "应参数化或外移）")
        if r.rel.suffix.lower() in ASSET_EXTS and r.rel.parts[0] != "assets":
            l9_hits.append(f"{rp}: 素材类文件应归置 assets/")
    add("L-9", "templates 内联与 assets 归置", "WARN" if l9_hits else "PASS",
        "; ".join(l9_hits[:6]) + ("…" if len(l9_hits) > 6 else "")
        if l9_hits else "templates/ 无超限，素材类文件均在 assets/ 内或无素材")

    # ---- L-10 全包宿主路径（§10.1）----
    l10_hits: list[str] = []
    for r in recs:
        if r.text is None:
            continue
        for lineno, line in enumerate(r.text.splitlines(), 1):
            if HOSTPATH_RE.search(line):
                l10_hits.append(f"{r.rel.as_posix()}:{lineno}: {line.strip()[:50]}")
    add("L-10", "全包宿主绝对路径（~/、$HOME、盘符）", "FAIL" if l10_hits else "PASS",
        "; ".join(l10_hits[:6]) + (f" 等 {len(l10_hits)} 处" if len(l10_hits) > 6 else "")
        + "（§10.1：改为包内相对路径）" if l10_hits else "全包文本零命中")

    # ---- L-11 宿主专属黑名单（§10.2）----
    blacklist = dict(HOST_SPECIFIC_DEFAULT)
    for tok in host_extra:
        if tok:
            blacklist[tok.lower()] = f"--host 增补（{tok}）"
    l11_hits: list[str] = []
    for r in recs:
        if r.text is None:
            continue
        for lineno, line in enumerate(r.text.splitlines(), 1):
            low = line.lower()
            for pat, label in blacklist.items():
                if pat in low:
                    l11_hits.append(f"{r.rel.as_posix()}:{lineno}: [{label}] "
                                    f"{line.strip()[:40]}")
                    break
    add("L-11", "宿主专属路径/工具名", "WARN" if l11_hits else "PASS",
        "; ".join(l11_hits[:6]) + (f" 等 {len(l11_hits)} 处" if len(l11_hits) > 6 else "")
        + "（§10.2：宿主专属耦合须声明或解耦，人工复核）" if l11_hits
        else f"默认黑名单 {len(blacklist)} 词 + --host 增补 {len(host_extra)} 词零命中")

    # ---- L-12 全包 LF + 无 BOM（§10.3/§10.4）----
    l12_hits: list[str] = []
    for r in recs:
        if r.raw is None or r.is_binary:
            # v1.0.1 评审 Bug 2：is_binary 此前仅计数未使用——二进制文件（PNG CRC
            # 段/pyc 字符串池等）天然含 0x0D，不滤会误判 CR → FAIL（阻断级假阳性）
            continue
        probs = []
        if b"\r" in r.raw:
            probs.append("CR")
        if r.raw.startswith(b"\xef\xbb\xbf"):
            probs.append("BOM")
        if probs:
            l12_hits.append(f"{r.rel.as_posix()}（{'+'.join(probs)}）")
    add("L-12", "全包 LF 换行 + 无 BOM", "FAIL" if l12_hits else "PASS",
        "; ".join(l12_hits[:6]) + (f" 等 {len(l12_hits)} 个文件" if len(l12_hits) > 6 else "")
        + "（§10.3/§10.4：转 LF/去 BOM 后复跑）" if l12_hits
        else "全部已扫描文件 LF 无 BOM（二进制/超限跳过）")

    # ---- L-13 .gitattributes（§10.6）----
    ga = skill_dir / ".gitattributes"
    if not ga.is_file():
        add("L-13", ".gitattributes eol=lf 规则", "WARN",
            "缺 .gitattributes（§10.6 建议补 '* text eol=lf'）")
    else:
        try:
            ga_text = ga.read_text(encoding="utf-8-sig", errors="replace")
            if re.search(r"eol\s*=\s*lf", ga_text, re.I):
                add("L-13", ".gitattributes eol=lf 规则", "PASS", "在场且含 eol=lf 规则行")
            else:
                add("L-13", ".gitattributes eol=lf 规则", "WARN",
                    "在场但无 eol=lf 类规则行（§10.6）")
        except OSError as e:
            add("L-13", ".gitattributes eol=lf 规则", "WARN", f"读取失败: {e}")

    # ---- L-14 i18n 混入（§11.1）----
    desc = kv.get("description", "")
    others = {k: v for k, v in kv.items()
              if k not in ("description", "name", "allowed-tools") and v}
    # v1.0.1 评审 2.3：多行 metadata 的行内值为空串会被上面的 kv 过滤——
    # 补扫 frontmatter 缩进叶值（metadata: 下钻的 note_zh: 中文说明 等）
    for ln in fm_lines:
        if ln[:1] in (" ", "\t"):
            m14 = re.match(r"^[ \t]+([\w.-]+)[ \t]*:[ \t]*(.+?)[ \t]*$", ln)
            if m14 and m14.group(2):
                others[f"metadata.{m14.group(1)}"] = m14.group(2)
    cjk_others = {k: v for k, v in others.items() if CJK_RE.search(v)}
    if desc and not CJK_RE.search(desc) and cjk_others:
        add("L-14", "frontmatter i18n 一致性", "WARN",
            f"description 全英文而其余键含 CJK: {', '.join(cjk_others)}"
            "（§11.1：统一语言或补译）")
    else:
        add("L-14", "frontmatter i18n 一致性", "PASS",
            "description 与其余键语言形态一致（description 空/CJK/其余全 ASCII 均不判）")

    # ---- L-15 代码块命令混译（§11.2）----
    l15_hits: list[str] = []
    in_fence = False
    for lineno, line in enumerate(body.split("\n"), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence and CMD_LINE_RE.match(line) and CJK_RE.search(line):
            l15_hits.append(f"SKILL.md:{lineno + body_line_off}: {line.strip()[:50]}")
    add("L-15", "代码块内命令未翻译启发式", "WARN" if l15_hits else "PASS",
        "; ".join(l15_hits[:6]) + (f" 等 {len(l15_hits)} 处" if len(l15_hits) > 6 else "")
        + "（§11.2：命令保持原文，注释另行翻译）" if l15_hits else "代码块命令行无 CJK 混入")

    # ---- L-16 行数漂移（V27 机械半）----
    if skill_md is None or skill_md.raw is None:
        add("L-16", "SKILL.md 行数漂移（基线哈希比对）", "SKIP", "SKILL.md 不可读，无法比对")
    else:
        cur_hash = hashlib.sha256(skill_md.raw).hexdigest()
        n_lines = len((skill_md.text or "").splitlines())
        bl = skill_dir / ".verification" / ".iteration-baseline"
        if not bl.is_file():
            add("L-16", "SKILL.md 行数漂移（基线哈希比对）", "INFO",
                f"当前 {n_lines} 行（sha256 {cur_hash[:12]}…）；无 .iteration-baseline"
                "（首轮编写期属预期；验收后经 eval_discipline record 生成）")
        else:
            try:
                bl_text = bl.read_text(encoding="utf-8-sig", errors="replace")
                recorded = set(re.findall(
                    r"(?i)snapshot_sha256_skill_md[ \t]*[:=][ \t]*\"?([0-9a-f]{64})",
                    bl_text)) | set(re.findall(
                        r'"SKILL\.md"[ \t]*:[ \t]*"([0-9a-f]{64})"', bl_text))
                if not recorded:
                    add("L-16", "SKILL.md 行数漂移（基线哈希比对）", "SKIP",
                        "基线在但无 SKILL.md 哈希记录（旧式键值基线），哈希比对不可机械执行")
                elif cur_hash in recorded:
                    add("L-16", "SKILL.md 行数漂移（基线哈希比对）", "PASS",
                        f"当前 {n_lines} 行，哈希与基线一致")
                else:
                    add("L-16", "SKILL.md 行数漂移（基线哈希比对）", "WARN",
                        f"当前 {n_lines} 行（sha256 {cur_hash[:12]}…）与基线记录不一致"
                        "——V27 拆分复核义务：核对行数是否逼近上限并评估拆分")
            except OSError as e:
                add("L-16", "SKILL.md 行数漂移（基线哈希比对）", "SKIP", f"基线读取失败: {e}")

    # ---- L-17 笼统指引初筛（§4.1.7 机械半）----
    l17_hits: list[str] = []
    for lineno, line in enumerate(body.split("\n"), 1):
        if VAGUE_REFS_RE.search(line):
            l17_hits.append(f"SKILL.md:{lineno + body_line_off}: references/ 后无具体文件名")
        elif VAGUE_MORE_RE.search(line) \
                and not re.search(r"references/|scripts/|assets/|\.\w{2,4}\b", line):
            l17_hits.append(f"SKILL.md:{lineno + body_line_off}: 孤立\"更多示例\"无路径")
    add("L-17", "笼统指引模式初筛", "WARN" if l17_hits else "PASS",
        "; ".join(l17_hits[:6]) + (f" 等 {len(l17_hits)} 处" if len(l17_hits) > 6 else "")
        + "（机械初筛；是否实质笼统归 LL-2 LLM 终判）" if l17_hits
        else "笼统指引模式零命中")

    # ---- L-18 恶意特征初筛（§9.1 机械半）----
    l18_hits: list[str] = []
    for r in recs:
        if r.text is None:
            continue
        for lineno, line in enumerate(r.text.splitlines(), 1):
            kind = ("下载执行链" if DL_EXEC_RE.search(line)
                    else "eval+base64 混淆" if EVAL_B64_RE.search(line)
                    else "凭据外传 URL" if EXFIL_URL_RE.search(line)
                    else None)
            if kind:
                l18_hits.append(f"{r.rel.as_posix()}:{lineno}: [{kind}] {line.strip()[:40]}")
    add("L-18", "恶意特征模式初筛", "WARN" if l18_hits else "PASS",
        "; ".join(l18_hits[:6]) + (f" 等 {len(l18_hits)} 处" if len(l18_hits) > 6 else "")
        + "（仅初筛；终判归 LL-6 LLM + 人工，security_scan 语义审计不豁免）"
        if l18_hits else "三类恶意特征模式零命中")

    return rows


# ----------------------------------------------------------------- main ----

def main() -> int:
    ap = _BlockArgParser(description="编写期静态补检器（L-1~L-18，任务书甲档工具一）")
    ap.add_argument("skill_dir", help="待检技能根目录（含 SKILL.md）")
    ap.add_argument("--out", help="报告落盘路径（建议 .verification/write/static-lint.md）")
    ap.add_argument("--host", default="",
                    help="增补宿主专属黑名单词（逗号分隔，L-11 用）")
    a = ap.parse_args()

    if a.out is not None and not a.out.strip():
        print("错误: --out 不接受空串。下一步: 去掉 --out 或给出有效落盘路径。",
              file=sys.stderr)
        return 1

    skill_dir = Path(a.skill_dir)
    if not skill_dir.is_dir():
        print(f"错误: 目录不存在: {skill_dir}。下一步: 核对路径后重试。", file=sys.stderr)
        return 1
    if not (skill_dir / "SKILL.md").is_file():
        print(f"错误: {skill_dir} 下无 SKILL.md（本工具以技能包为检索单位）。"
              "下一步: 核对 --skill-dir 是否指向技能根目录。", file=sys.stderr)
        return 1

    recs, n_binary, n_read_err = build_inventory(skill_dir)
    # v1.0.1 评审 2.5：保原始大小写供报告回显（匹配小写化收敛到 run_checks 的
    # blacklist[tok.lower()] 单点，原先 main 预 .lower() 使回显恒小写）
    host_extra = [t.strip() for t in a.host.split(",") if t.strip()]
    rows = run_checks(skill_dir, recs, host_extra)

    has_fail = any(r["level"] == "FAIL" for r in rows)
    has_warn = any(r["level"] == "WARN" for r in rows)
    has_skip = any(r["level"] == "SKIP" for r in rows)
    judged = [r for r in rows if r["level"] in ("PASS", "FAIL")]
    # v1.1 自查③：统计口径对齐 eval_artifacts_check——分母只含 PASS/FAIL，
    # WARN/SKIP/INFO 单独计数（"x/y PASS" 无口径注明易被读成全量通过率）
    n_warn = sum(1 for r in rows if r["level"] == "WARN")
    n_skip = sum(1 for r in rows if r["level"] == "SKIP")
    n_info = sum(1 for r in rows if r["level"] == "INFO")

    suffix_notes: list[str] = []
    if has_warn:
        suffix_notes.append("WARN（需书面评估）")
    if has_skip:
        suffix_notes.append("SKIP（仅记录）")
    suffix = f"；附 {' + '.join(suffix_notes)}" if suffix_notes else ""
    lines = [
        "# 编写期静态补检报告（w_static_lint.py " + VERSION + "）",
        "",
        f"- 技能: {skill_dir.name}（{skill_dir}）",
        f"- 口径: 任务书甲档工具一 L-1~L-18；扫描文件 {len(recs)}"
        f"（二进制跳过 {n_binary}，读取失败 {n_read_err}）；"
        f"宿主黑名单增补词 {len(host_extra)}",
        f"- 总结论: {'FAIL（存在阻断项）' if has_fail else 'PASS'}{suffix}",
        "",
        "| 项 | 检查内容 | 结论 | 证据 |",
        "|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['lid']} | {r['title']} | {r['level']} | {r['ev']} |")
    lines += [
        "",
        f"> 判定统计: PASS/FAIL 判定 {sum(1 for r in judged if r['level'] == 'PASS')}/{len(judged)}"
        + f"（另 WARN {n_warn}；SKIP {n_skip}；INFO {n_info}）"
        + ("；L-17/L-18 为初筛（语义终判归 LL-2/LL-6），SKIP 不计警告。" if not has_fail
           else "；L 系 FAIL 阻断，当轮修复后复跑。"),
    ]
    report = "\n".join(lines) + "\n"

    print(report)
    if a.out:
        outp = Path(a.out)
        try:
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text(report, encoding="utf-8", newline="\n")
            print(f"[已落盘] {outp}")
        except OSError as e:
            print(f"[FAIL] 报告落盘失败: {outp} — {e}。下一步: 检查路径权限或改用其他 --out 路径。",
                  file=sys.stderr)
            return 1

    return 1 if has_fail else (2 if has_warn else 0)


if __name__ == "__main__":
    sys.exit(main())
