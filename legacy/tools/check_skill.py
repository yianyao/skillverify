#!/usr/bin/env python3
"""check_skill.py — Agent Skill 格式门 A 权威校验器（S 工具链）。

落实《Agent-Skill 生命周期验证方案》§13 A1–A11（A6 按项目收紧 <300 判）
与《规范条目总表》478–488 行口径。机械可判定项全部脚本化；语义项
（A8"均有触发条件"、--help 内容正确性）不在本工具范围，分别留 H/LLM。

检查项（A 门）:
  A1  skills-ref validate     官方 CLI（PyPI skills-ref，入口名 agentskills；npm 同名包
                              系第三方占用勿用）在场则实检（validate 非零→WARN）；缺席记
                              SKIP（等效覆盖=A2–A11）
  A2  目录结构合规            SKILL.md 位于根目录且为文件
  A3  name 合规               正则 ^[a-z0-9]+(-[a-z0-9]+)*$、长 1–64、与目录名一致
  A4  description 合规        长度 1–1024 非空
  A5  compatibility 合规      若存在则长度 1–500
  A6  SKILL.md 行数           < 上限（默认 300，项目收紧；官方 500 可用 --lines 覆盖）；
                              达上限 80%（V27 预警线，300→240 / 500→400）时 WARN 提示拆分评估
  A7  换行符为 LF             字节级检测（b"\\r" 同时覆盖 CRLF 与孤立 \\r）
  A8  引用路径形态            SKILL.md 内引用均为相对路径且仅一层（禁绝对路径/~/、禁 ../、禁两级以上）；
                              提取前先剥离 URL，避免 https://.../scripts/foo 之类片段误报
  A9  脚本无交互式输入        scripts/*.py 检索 input(/getpass/read -p/confirm 等 8 类模式
                              （文本级匹配，宁可误报不漏报，命中须人工复核）
  A10 脚本 --help 可运行       退出码 0 且 stdout 非空（内容正确性→W-14）
  A11 frontmatter 可解析       含 name、description 两键（缩进续行视为多行值，不误报"无冒号"）

附加机械检（不计入 A 门判定，INFO 级）:
  X1  UTF-8 无 BOM（§10.4）
  X2  evals/evals.json 可 JSON 解析且含 queries 数组（§15.7 交付物，存在时才检）

用法:
    python check_skill.py <skill_dir>                   # 校验单个技能
    python check_skill.py <skill_dir> --out report.md   # 同时落盘报告
    python check_skill.py <skill_dir> --lines 500       # 覆盖 A6 行数上限（官方口径）

退出码: 0=全 PASS（A1 SKIP 不计入警告级）；1=任一 FAIL；2=无 FAIL 但有 WARN。

版本: v1.1.4（2026-10-03 复检）— 报告头补版本标识（v1.1.3 补 VERSION 常量但报告
      头漏写，审计者从落盘报告看不到版本，与补常量初衷相悖）。
      v1.1.3（2026-10-03 收官回填批次）— 补 VERSION 常量（v1.1.2 及以前版本仅记
      docstring，评审全量盘点时曾漏计）；--lines 正整数校验（--lines 0/负数原使
      A6 无条件 FAIL，现 fail-fast exit 1——对齐 token_budget/local_gate 族惯例）。
      v1.1.2（2026-10-03 追加评审 2 条）— A1 探测改官方入口名 agentskills 优先
      （npm 第三方占用包 bin 名恰为 skills-ref，并存环境不得优先命中第三方）；
      参数解析改 _BlockArgParser（--lines abc 等参数错误统一 exit 1，不再撞 WARN 码
      ——naming_precheck v1.0.1 评审 5 纪律回填，原 v1.1d 冻结时该口径未成型）。
      v1.1.1（2026-10-03 T 项考证）— A1 探测扩官方入口名 agentskills（PyPI skills-ref
      0.1.1，anthropics/agentskills）；npm 同名包系第三方占用已在注释警示。
      v1.1（2026-10-02 外部评审修订）— S-1 行数口径改 splitlines；S-2/S-3 A1 真检测
      + SKIP 不计警告；S-4 A6 增 80% 预警线；P-1 孤立 \\r；P-2 剥离 URL；P-3 多行值
      续行不误报；P-4 A9 证据加注；P-5 A2 早退加 INFO。
      v1.1b（2026-10-02 第二轮评审，6 条 [P] 健壮性）— A10 stdout None 归一；X2 防
      非 dict 根 + OSError；A9/A2 后读取防 OSError（失败跳过并提示/早退）；总结论
      措辞分级（WARN 需书面评估、SKIP 仅记录）。
      v1.1c（2026-10-02 第三轮评审）— 2.1[S] A9 读取失败改 WARN（覆盖不全≠零命中
      通过）；2.2 删 A8 abs_misc 死代码过滤；2.3 WARN+SKIP 并存时总结论并列展示。
      v1.1d（2026-10-02 第四轮评审）— 2.1[S] 解析前剥 BOM（X1 专职报警，A11 不再
      误报区块缺失）；2.2 URL 剥离扩展 file://；2.3 A10 补捕 OSError；2.4 A9/A10
      共用一次 glob；2.5 INFO 行排序位次固定。
留痕: 报告由 --out 指定落盘路径（建议 .verification/m1-s/format-gate.md）。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_LINE_LIMIT = 300  # 项目收紧（官方 500）；--lines 覆盖
VERSION = "v1.1.4"

# A9 交互式输入模式（§8.3.1 + 总表补全：Python/Shell/JS 三族）
INTERACTIVE_PAT = (
    "input(", "getpass", "read -p", "confirm(", "readline(",
    "inquirer", "prompt_toolkit", "click.confirm",
)

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def load_skill_md(skill_dir: Path) -> tuple[str, bytes, dict, list[str]]:
    """读 SKILL.md，解析 frontmatter。返回 (text, raw, fm, fm_parse_notes)。"""
    raw = (skill_dir / "SKILL.md").read_bytes()
    # v1.1d 2.1 [S]：X1 专职报 BOM；此处剥离后再解析，避免 BOM 致 ^--- 不匹配
    # 而使 A11 误报"frontmatter 区块缺失"（与 host_compat 的 utf-8-sig 口径对齐）
    raw_for_parse = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
    text = raw_for_parse.decode("utf-8", errors="replace")
    fm: dict[str, str] = {}
    notes: list[str] = []
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", text, re.S)
    if not m:
        notes.append("frontmatter 区块缺失（首部无 --- 界定）")
        return text, raw, fm, notes
    for ln in m.group(1).split("\n"):
        if ln[:1] in (" ", "\t"):
            continue  # 缩进续行 = YAML 多行值/列表项（P-3），不做顶层键值解析
        if ":" in ln:
            k, _, v = ln.partition(":")
            k = k.strip()
            if re.fullmatch(r"[a-z][a-z0-9-]*", k):
                fm[k] = v.strip()
            else:
                notes.append(f"frontmatter 键名不合规: {k!r}")
        elif ln.strip():
            notes.append(f"frontmatter 行无冒号: {ln.strip()[:40]!r}")
    return text, raw, fm, notes


def check(skill_dir: Path, line_limit: int) -> list[dict]:
    rows: list[dict] = []

    def add(aid: str, title: str, level: str, ev: str) -> None:
        rows.append(dict(aid=aid, title=title, level=level, ev=ev))

    skill_md = skill_dir / "SKILL.md"

    # A2 目录结构
    if not skill_md.is_file():
        add("A2", "SKILL.md 位于根目录", "FAIL",
            f"{skill_md} 不存在或不是文件。下一步: 核对 --skill-dir 是否指向技能根目录")
        add("INFO", "后续检查未执行", "INFO",
            "因 A2 FAIL，A3–A11 无法运行（P-5）")
        return rows  # 无 SKILL.md 时后续全部无法执行，直接返回
    add("A2", "SKILL.md 位于根目录", "PASS", str(skill_md))

    # 2.5 [P]：is_file() 只保证存在不保证可读（权限/占用）；读取失败则后续文本类检查全部无法执行
    try:
        text, raw, fm, fm_notes = load_skill_md(skill_dir)
    except OSError as e:
        add("A11", "frontmatter 可解析且含 name/description", "FAIL",
            f"SKILL.md 读取失败（权限/占用）: {e}")
        add("INFO", "后续检查未执行", "INFO", "因 SKILL.md 读取失败，A3–A10 无法运行")
        return rows

    # A11 frontmatter
    if fm.get("name") and fm.get("description"):
        lvl = "PASS" if not fm_notes else "WARN"
        ev = f"keys={sorted(fm)}" + (f"；注: {'; '.join(fm_notes)}" if fm_notes else "")
        add("A11", "frontmatter 可解析且含 name/description", lvl, ev)
    else:
        add("A11", "frontmatter 可解析且含 name/description", "FAIL",
            f"解析键={sorted(fm)}（缺 name/description）；{'; '.join(fm_notes) or '区块可能缺失'}")

    # A3 name
    name = fm.get("name", "")
    if not name:
        add("A3", "name 正则/长度/与目录一致", "FAIL", "frontmatter 无 name 键")
    elif not NAME_RE.fullmatch(name):
        add("A3", "name 正则/长度/与目录一致", "FAIL",
            f"name={name!r} 不匹配 ^[a-z0-9]+(-[a-z0-9]+)*$")
    elif not (1 <= len(name) <= 64):
        add("A3", "name 正则/长度/与目录一致", "FAIL", f"name 长度 {len(name)} 超出 1–64")
    elif name != skill_dir.name:
        add("A3", "name 正则/长度/与目录一致", "FAIL",
            f"name={name!r} 与目录名 {skill_dir.name!r} 不一致")
    else:
        add("A3", "name 正则/长度/与目录一致", "PASS", f"name={name}，与目录一致")

    # A4 description
    desc = fm.get("description", "")
    if not desc:
        add("A4", "description 长度 1-1024 非空", "FAIL", "description 为空或缺失")
    elif len(desc) > 1024:
        add("A4", "description 长度 1-1024 非空", "FAIL", f"长度 {len(desc)} > 1024")
    else:
        add("A4", "description 长度 1-1024 非空", "PASS", f"长度 {len(desc)}")

    # A5 compatibility
    comp = fm.get("compatibility")
    if comp is None:
        add("A5", "compatibility 长度 1-500（若存在）", "PASS", "未声明（允许缺省）")
    elif 1 <= len(comp) <= 500:
        add("A5", "compatibility 长度 1-500（若存在）", "PASS", f"长度 {len(comp)}")
    else:
        add("A5", "compatibility 长度 1-500（若存在）", "FAIL", f"长度 {len(comp)} 超出 1–500")

    # A6 行数（项目收紧；口径=splitlines，即编辑器/GitHub 显示行数，末尾换行不多计——S-1）
    n_lines = len(text.splitlines())
    warn_line = line_limit * 4 // 5  # V27 预警线=上限 80%（300→240，500→400）——S-4
    if n_lines < warn_line:
        add("A6", f"SKILL.md 行数 <{line_limit}", "PASS",
            f"{n_lines} 行" + ("（项目收紧口径）" if line_limit == DEFAULT_LINE_LIMIT else "（--lines 覆盖口径）"))
    elif n_lines < line_limit:
        add("A6", f"SKILL.md 行数 <{line_limit}", "WARN",
            f"{n_lines} 行，已达 V27 预警线（≥{warn_line}）。下一步: 启动拆分评估（外移到 references/）")
    else:
        add("A6", f"SKILL.md 行数 <{line_limit}", "FAIL",
            f"{n_lines} 行 ≥ {line_limit}。下一步: 按 V27 强制拆分到 references/ 并复跑本工具")

    # A7 LF（P-1：b"\\r" 同时覆盖 CRLF 与孤立 \\r）
    add("A7", "换行符为 LF", "PASS" if b"\r" not in raw else "FAIL",
        "LF only" if b"\r" not in raw else "检出 CR（CRLF 或孤立 \\r）。下一步: 全文件转 LF 后复跑")

    # A8 引用路径形态（机械部分；"均有触发条件"为语义项留 H）
    # P-2/v1.1d 2.2：先剥离 URL（含 file://），避免 https://host/scripts/foo、
    # file:///home/x/references/g.md 之类片段被当作相对引用
    text_no_url = re.sub(r"(?:https?|file)://\S+", "", text)
    ref_pat = re.compile(r"(?:references|scripts|assets|evals)/[\w./-]+")
    refs = ref_pat.findall(text_no_url)
    bad_form: list[str] = []
    for r in refs:
        if re.match(r"^[A-Za-z]:[\\/]", r) or r.startswith("~"):
            bad_form.append(f"绝对路径: {r}")
        if ".." in r:
            bad_form.append(f"越级 ../: {r}")
        if r.count("/") > 1:
            bad_form.append(f"超过一层: {r}")
    # v1.1c 2.2 [P]：abs_misc 已在 pattern 层面限定为盘符开头（[A-Za-z]:[\\/]），
    # 与 ref_pat 的 references|scripts|... 前缀不可能重合，原二次过滤为死代码，删除。
    abs_misc = re.findall(r"(?<![\w./-])[A-Za-z]:[\\/][^\s`'\"<>\)\]]+", text_no_url)
    if bad_form or abs_misc:
        add("A8", "引用为相对路径且仅一层", "FAIL",
            "; ".join((bad_form + [f"正文绝对路径: {a}" for a in abs_misc[:3]])))
    else:
        add("A8", "引用为相对路径且仅一层", "PASS",
            f"{len(set(refs))} 个相对引用全部合规；存在性核对: " + check_ref_existence(skill_dir, refs))

    # A9 交互式输入（scripts_glob 与 A10 共用，v1.1d 2.4 合并两次 glob）
    bad_a9: list[str] = []
    a9_read_err: list[str] = []
    scripts_glob = sorted(skill_dir.glob("scripts/*.py"))
    for py in scripts_glob:
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError as e:  # 2.4 [P]：glob 保证存在但不保证可读（权限/占用）
            a9_read_err.append(f"{py.name}: 读取失败（{e.strerror or e}）")
            continue
        for pat in INTERACTIVE_PAT:
            if pat in src:
                bad_a9.append(f"{py.name}: {pat}")
    # v1.1c 2.1 [S]：读取失败 = 覆盖不全，不能算"零命中通过"——记 WARN（命中才 FAIL）
    a9_level = "FAIL" if bad_a9 else ("WARN" if a9_read_err else "PASS")
    a9_ev = (
        "; ".join(bad_a9) + "（文本级匹配可能误报，命中须人工复核——P-4）" if bad_a9
        else (f"{len(scripts_glob)} 个脚本检索 8 类模式零命中"
              + (f"；但 {len(a9_read_err)} 个脚本未检查到" if a9_read_err else ""))
    ) + ("；" + "; ".join(a9_read_err) if a9_read_err else "")
    add("A9", "脚本无交互式输入", a9_level, a9_ev)

    # A10 脚本 --help（复用 A9 的 scripts_glob）
    a10_bad: list[str] = []
    scripts = scripts_glob
    for py in scripts:
        try:
            p = subprocess.run(
                [sys.executable, str(py), "--help"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=15, stdin=subprocess.DEVNULL,
            )
            if p.returncode != 0 or not (p.stdout or "").strip():
                # 2.1 [P]：stdout 统一经 (p.stdout or "") 归一，防罕见平台 None → AttributeError
                stdout_empty = not (p.stdout or "").strip()
                a10_bad.append(f"{py.name}: exit={p.returncode}, stdout={'空' if stdout_empty else '有'}")
        except subprocess.TimeoutExpired:
            a10_bad.append(f"{py.name}: --help 超时挂起")
        except OSError as e:  # v1.1d 2.3 [P]：解释器无法启动等罕见场景，不崩掉整份报告
            a10_bad.append(f"{py.name}: --help 调用失败（{e}）")
    add("A10", "脚本 --help 可运行", "FAIL" if a10_bad else ("PASS" if scripts else "WARN"),
        "; ".join(a10_bad) if a10_bad else (f"{len(scripts)} 个脚本全部 exit=0 且有输出（内容正确性→W-14）" if scripts else "无 scripts/ 目录"))

    # X1 BOM（附加，INFO）
    add("X1", "UTF-8 无 BOM（附加）", "INFO" if not raw.startswith(b"\xef\xbb\xbf") else "WARN",
        "无 BOM" if not raw.startswith(b"\xef\xbb\xbf") else "检出 BOM（§10.4 建议移除）")

    # X2 evals.json（附加，INFO）
    evals = skill_dir / "evals" / "evals.json"
    if evals.is_file():
        try:
            data = json.loads(evals.read_text(encoding="utf-8"))
            if not isinstance(data, dict):  # 2.2 [P]：合法 JSON 但根非对象（list/str/num）
                add("X2", "evals.json 可解析（附加）", "WARN",
                    f"JSON 根类型为 {type(data).__name__}，非对象；应含 queries 数组")
            else:
                ok = isinstance(data.get("queries"), list) and bool(data["queries"])
                add("X2", "evals.json 可解析（附加）", "INFO" if ok else "WARN",
                    f"queries={len(data.get('queries', []))} 条" if ok else "可解析但 queries 数组缺失或为空")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            add("X2", "evals.json 可解析（附加）", "WARN", f"解析失败: {e}")
        except OSError as e:  # 2.3 [P]：文件存在但不可读（权限/占用）
            add("X2", "evals.json 可解析（附加）", "WARN", f"读取失败: {e}")
    else:
        add("X2", "evals.json 可解析（附加）", "INFO", "无 evals/evals.json（§15.7 交付场景需补）")

    return rows


def check_ref_existence(skill_dir: Path, refs: list[str]) -> str:
    """引用存在性核对（WARN 级旁证：代码块内的用法示例可能合法不存在）。"""
    uniq = sorted(set(refs))
    missing = [r for r in uniq if not (skill_dir / r).exists()]
    if not uniq:
        return "无引用"
    if missing:
        return f"{len(uniq) - len(missing)}/{len(uniq)} 存在，缺失={missing}（若为用法示例可忽略，正文中真实引用缺失须修复）"
    return f"{len(uniq)}/{len(uniq)} 全部存在"


class _BlockArgParser(argparse.ArgumentParser):
    """参数错误统一 exit 1（阻断码）——argparse 默认 exit 2 撞 WARN 码
    （naming_precheck v1.0.1 评审 5 纪律，v1.0.3 error() 覆写口径全工具对齐；
    check_skill v1.1d 冻结时该口径未成型，v1.1.2 回填）。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"错误: {message}。下一步: 按用法核对参数后重试。", file=sys.stderr)
        raise SystemExit(1)


def find_official_cli(which=shutil.which) -> str | None:
    """定位官方校验器 CLI。官方入口名 agentskills 优先——npm 第三方占用包
    （crazyyanchao/agentskillsjs）的 bin 名恰为 skills-ref，两 CLI 并存的环境
    若按包名优先会命中第三方，validate 结果不可信（v1.1.2 评审 1）。"""
    return which("agentskills") or which("skills-ref")


def main() -> int:
    ap = _BlockArgParser(description="Agent Skill 格式门 A 权威校验器（A1–A11 + 附加机械检）")
    ap.add_argument("skill_dir", help="待校验技能根目录（含 SKILL.md）")
    ap.add_argument("--out", help="报告落盘路径（建议 .verification/m1-s/format-gate.md）")
    ap.add_argument("--lines", type=int, default=DEFAULT_LINE_LIMIT,
                    help=f"A6 行数上限（默认 {DEFAULT_LINE_LIMIT}，项目收紧；官方 500 用 --lines 500）")
    a = ap.parse_args()

    if a.lines <= 0:
        print("错误: --lines 须为正整数（A6 行数上限）。下一步: 如 --lines 500。",
              file=sys.stderr)
        return 1

    skill_dir = Path(a.skill_dir)
    if not skill_dir.is_dir():
        print(f"错误: 目录不存在: {skill_dir}。下一步: 核对路径后重试。", file=sys.stderr)
        return 1

    # A1 skills-ref（S-2/S-3：官方 CLI 在场则实检，缺席记 SKIP；SKIP 不计入警告级 verdict）
    # T 项考证（2026-10-03）：官方包=PyPI skills-ref（anthropics/agentskills，Apache-2.0），
    # CLI 入口名 agentskills——npm 同名包系第三方占用（crazyyanchao/agentskillsjs，
    # 自述 demonstration only），勿经 npx 调用；官方入口名优先（v1.1.2 评审 1，
    # 并存环境不命中第三方），skills-ref 仅作别名兼容兜底
    skills_ref = find_official_cli()
    if skills_ref:
        try:
            p = subprocess.run(
                [skills_ref, "validate", str(skill_dir)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=60, stdin=subprocess.DEVNULL,
            )
            if p.returncode == 0:
                rows = [dict(aid="A1", title="skills-ref validate", level="PASS",
                             ev=f"官方 CLI validate 通过（exit=0）: {(p.stdout or '').strip()[:80]}")]
            else:
                rows = [dict(aid="A1", title="skills-ref validate", level="WARN",
                             ev=f"官方 CLI validate 非零退出（exit={p.returncode}）: "
                                f"{((p.stderr or '') + (p.stdout or '')).strip()[:120]}"
                                "（若为调用方式不符请人工复核）")]
        except (subprocess.TimeoutExpired, OSError) as e:
            rows = [dict(aid="A1", title="skills-ref validate", level="SKIP",
                         ev=f"官方 CLI 调用失败（{e}）；等效覆盖=A2–A11 机械项")]
    else:
        rows = [dict(aid="A1", title="skills-ref validate", level="SKIP",
                     ev="官方 CLI 未安装（pip install skills-ref==0.1.1，入口名 agentskills；"
                        "须在 PATH 含其 Scripts 的环境运行本工具方能自动实检）；"
                        "等效覆盖=A2–A11 机械项")]

    rows += check(skill_dir, a.lines)

    # 报告行序按 A1→A11→X 排列（避免实现顺序造成阅读跳跃）；INFO 类固定居 A11 之后（v1.1d 2.5）
    _order = {"A1": 1, "A2": 2, "A3": 3, "A4": 4, "A5": 5, "A6": 6, "A7": 7,
              "A8": 8, "A9": 9, "A10": 10, "A11": 11, "INFO": 50}
    rows.sort(key=lambda r: (_order.get(r["aid"], 99), r["aid"]))

    judged = [r for r in rows if r["level"] in ("PASS", "FAIL")]
    has_fail = any(r["level"] == "FAIL" for r in rows)
    has_warn = any(r["level"] == "WARN" for r in rows)  # S-2：SKIP 不触发警告级 verdict
    has_skip = any(r["level"] == "SKIP" for r in rows)

    # 2.6/v1.1c 2.3 [P]：分级措辞——WARN 与 SKIP 并存时并列展示，不互相隐藏
    suffix_notes: list[str] = []
    if has_warn:
        suffix_notes.append("WARN（需书面评估）")
    if has_skip:
        suffix_notes.append("SKIP（仅记录）")
    suffix = f"；附 {' + '.join(suffix_notes)}" if suffix_notes else ""
    lines = [
        "# 格式门 A 校验报告（check_skill.py " + VERSION + "）",
        "",
        f"- 技能: {skill_dir.name}（{skill_dir}）",
        f"- 口径: §13 A1–A11，A6 <{a.lines}（{'项目收紧' if a.lines == DEFAULT_LINE_LIMIT else '--lines 覆盖'}）；附加 X1/X2 不计入判定",
        f"- 总结论: {'FAIL（存在阻断项）' if has_fail else 'PASS'}{suffix}",
        "",
        "| 项 | 检查内容 | 结论 | 证据 |",
        "|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['aid']} | {r['title']} | {r['level']} | {r['ev']} |")
    lines += [
        "",
        f"> 判定统计: {sum(1 for r in judged if r['level'] == 'PASS')}/{len(judged)} PASS"
        + ("；A8 触发条件为语义项留 H，--help 内容正确性留 W-14。" if not has_fail else "；[M]/[S] 级 FAIL 阻断，不得自动放行。"),
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
            print(f"[FAIL] 报告落盘失败: {outp} — {e}。下一步: 检查路径权限或改用其他 --out 路径。", file=sys.stderr)
            return 1

    return 1 if has_fail else (2 if has_warn else 0)


if __name__ == "__main__":
    sys.exit(main())
