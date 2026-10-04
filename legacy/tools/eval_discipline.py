#!/usr/bin/env python3
"""eval_discipline.py — Agent Skill 评测纪律三门（V21 断言时机 + V28 写回一致性 + V29 iteration 基线）。

落实《Agent-Skill 生命周期验证方案》V 系列三行（承载方式：合一独立脚本——
三门同属 E/X 阶段评测与迭代留痕纪律、输入同源（评测产物 + 基线文件），
沿 token_budget.py（V11+V17 两门合一）先例；手段表已核：V21 H/S 的机械半、
V28 S、V29 S/C 均机械可判，纯脚本承载成立，无需 K 编排）：

  V21 [M] 断言添加时机与初始用例数：初始 2–3 条；断言必须在首轮输出后添加
          （时间戳晚于首轮产出）——语义半（未提前定义 PASS/FAIL）归 H，本工具只做机械半
  V28 [S] 写入一致性核对：description 选定版本写回 frontmatter 后，核对落盘内容
          与选定版本哈希一致（防写回丢失/截断/变形）
  V29 [S] iteration 历史基线：每轮验收通过的 iteration 以 .iteration-baseline 记录，
          比对防止历史结果被覆盖（落实 §15.4 迭代留痕；record/verify 双模式）

检查项:
  V21-1 初始用例数     evals/evals.json 解析（cases 或 queries 数组）——当前数量记 INFO
                       （"初始 2–3 条"为流程纪律，终态无法机械验证初始值，须 run-log 留痕
                       佐证，语义归 H）；evals.json 缺失/解析失败 → FAIL
  V21-2 断言时机       evals.json 含断言形态（cases[].assertions 或顶层 assertions）时：
                       优先 assertions_added_at 时间戳字段（ISO 8601），否则 mtime 启发式
                       （evals.json mtime 须晚于 workspace 首轮 outputs 最早文件——启发式
                       口径：mtime 可被复制/迁移重置，须在原始工作区运行；证据内显式声明）；
                       cases 结构存在但断言全空 → WARN 提示补断言（不与"非断言形态"
                       的 SKIP 混同——评审 3）；触发查询集（queries）或未提供 workspace
                       → SKIP（人工留痕佐证，SKIP 不计警告）
  V28-1  写回一致性    --description-final <file> 或 --description-text <text> 提供选定
                       版本 → 与 SKILL.md frontmatter description 逐字符比对（SHA256 一致）；
                       未提供 → SKIP（未做 description 优化轮属常态，人工留痕佐证）
  V29-1  基线在场      .verification/.iteration-baseline 存在 → 解析校验必填字段
                       （iteration/accepted_at/version）；缺失 → WARN（已经过 E 阶段验收
                       的技能须补落；从未进入验收属常态，人工判断，不假 PASS 也不误阻断）
  V29-2  防覆盖比对    基线含 snapshot 块（record 模式生成的新格式：iteration 目录
                       文件清单 + SHA256）→ 逐文件比对现状，不一致 FAIL（历史被覆盖）；
                       旧格式（自由键值、哈希外引）→ SKIP + 提示 record 升级
  COV    扫描覆盖      读取失败计覆盖缺口，PASS 行降 WARN 不假 PASS

record 模式（--mode record）: 写/更新 .iteration-baseline——兼容既有键值格式
（iteration/accepted_at/version/acceptance_report/…）并追加 snapshot 块
（--snapshot-dir 可选，指定快照目录，通常为评测工作区或 .verification/iteration-N/，
逐文件 SHA256 清单），使 V29-2 具备机械比对依据。不提供 --snapshot-dir 时
基线为键值格式（V29-2 SKIP，无机械比对依据）——stderr 明示提示（评审 4）。

退出码: 0=全 PASS（SKIP 不计警告，与 check_skill A1 SKIP 口径一致）；
1=任一 FAIL 或参数错误（阻断）；2=无 FAIL 但有 WARN。
所有参数错误（缺参自查 + argparse 解析错误含类型转换失败）统一 exit 1
（_BlockArgParser 覆写 error()——naming_precheck v1.0.1 评审 5 纪律全工具对齐）。

用法:
    python eval_discipline.py <skill_dir> [--workspace <eval-workspace>]
                              [--description-final <file> | --description-text <text>]
                              [--mode record --version v1.0 --iteration 1
                               [--acceptance-report <path>] [--snapshot-dir <dir>]]
                              [--out report.md]

注: 本工具只做机械初筛。"未提前定义 PASS/FAIL""初始 2–3 条是否属实"等流程语义
由 H 承担（E-H 行）；基线缺席是否阻断由人工按技能所处阶段判断。
SKIP 行为"本工具口径下不适用/依据未提供"，均须人工留痕佐证，不豁免上游条款。

版本: v1.0.1（2026-10-03 首轮外部评审 7 条全核实处置——
      ①snapshot_dir_files SKIP 判定改快照根相对路径（p.parts 绝对路径会把祖先
        目录名 venv 等误判清空快照，高）；②无秒 ISO 补秒 parse_iso_ts
        （Python 3.10 fromisoformat 兼容，防误 FAIL）；③cases 空断言新形态
        cases-no-asserts → V21-2 WARN；④record 缺 --snapshot-dir stderr 提示
        +docstring 明确可选；⑤parse_baseline 行内无空格 snapshot:{…} 兼容；
      ⑥空 --description-text fail-fast exit 1；⑦必填字段口径注释）
      v1.0（2026-10-03 建成，S1④ 待办）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- 常量表 ----

VERSION = "v1.0.1"

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}

FM_KEY_RE = re.compile(r"[a-z][a-z0-9-]*")
# 基线键允许下划线（accepted_at / snapshot_sha256_skill_md——llm-review 旧格式即此形态，
# FM_KEY_RE 不认下划线会把必填字段解析丢——开发期自测暴露）
BASELINE_KEY_RE = re.compile(r"[a-z][a-z0-9_-]*")

BASELINE_FIELDS_REQUIRED = ("iteration", "accepted_at", "version")
# V29-1 必填仅上三项（缺失 → WARN 补全/re-record）；其余键（acceptance_report/note/…）可选
ISO_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
# 无秒形态补秒用：Python 3.7–3.10 的 fromisoformat 要求时:分:秒，无秒抛 ValueError
# → 走"格式非法"分支误 FAIL（评审 2）。负向断言避免重复补已带秒/带小数的时间。
TS_PAD_RE = re.compile(r"([T ]\d{2}:\d{2})(?![\d:])")


# ---------------------------------------------------------------- 基础设施 ----

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_iso_ts(s: str) -> datetime | None:
    """ISO 时间戳解析（Python 3.10 兼容口径）：无秒形态先补 ':00'
    （3.7–3.10 fromisoformat 要求时:分:秒，否则 ValueError → 误判"格式非法"FAIL）。
    非法返回 None。"""
    norm = s.strip().replace("Z", "+00:00")
    norm = TS_PAD_RE.sub(r"\1:00", norm)
    try:
        return datetime.fromisoformat(norm)
    except ValueError:
        return None


def load_frontmatter_description(skill_md: Path) -> tuple[str | None, str | None]:
    """读 frontmatter description（与 naming_precheck/security_scan 同口径：剥 BOM、
    缩进续行并入）。返回 (description, err)；文件读失败 → (None, err)。"""
    try:
        raw = skill_md.read_bytes()
    except OSError as e:
        return None, f"{e.strerror or e}"
    raw = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
    text = raw.decode("utf-8", errors="replace")
    m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        return None, "frontmatter 缺失或格式非法"
    fm: dict[str, str] = {}
    last_key: str | None = None
    for ln in m.group(1).split("\n"):
        if ln[:1] in (" ", "\t"):
            if last_key:
                fm[last_key] = (fm[last_key] + " " + ln.strip()).strip()
            continue
        if ":" in ln:
            k, _, v = ln.partition(":")
            k = k.strip()
            if FM_KEY_RE.fullmatch(k):
                fm[k] = v.strip()
                last_key = k
            else:
                last_key = None
    return fm.get("description"), None


def load_evals(skill_dir: Path) -> tuple[dict | None, str | None]:
    """读 evals/evals.json。返回 (dict, None) / (None, "缺失") / (None, "解析失败: …")。"""
    p = skill_dir / "evals" / "evals.json"
    if not p.is_file():
        return None, "缺失"
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as e:
        return None, f"解析失败: {e}"


def parse_evals_shape(evals: dict) -> tuple[str, int, list | None]:
    """识别 evals.json 形态。返回 (形态, 用例数, 断言列表或 None)。
    断言形态: cases[].assertions 或顶层 assertions；触发查询集形态: queries。
    cases 结构存在但断言全空 → "cases-no-asserts"（V21-2 记 WARN 提示补断言，
    不与"非断言形态"的 SKIP 混同——评审 3）。"""
    cases = evals.get("cases")
    if isinstance(cases, list):
        n = len(cases)
        asserts = [a for c in cases if isinstance(c, dict)
                   for a in (c.get("assertions") or [])]
        if asserts:
            return "cases", n, asserts
        return "cases-no-asserts", n, None
    if isinstance(evals.get("assertions"), list):
        return "assertions", len(evals["assertions"]), evals["assertions"]
    if isinstance(evals.get("queries"), list):
        return "queries", len(evals["queries"]), None
    return "unknown", 0, None


def earliest_output_mtime(workspace: Path) -> tuple[float | None, int, list[str]]:
    """扫描 workspace 下 iteration-*/eval-*/{with_skill,without_skill,old_skill}/outputs/
    的最早文件 mtime。返回 (最早 mtime 或 None, 产出文件数, 读取失败文件列表)。"""
    earliest: float | None = None
    n_files = 0
    errors: list[str] = []
    if not workspace.is_dir():
        return None, 0, ["workspace 目录不存在"]
    for it in sorted(workspace.glob("iteration-*")):
        for ev in sorted(it.glob("eval-*")):
            for lane in ("with_skill", "without_skill", "old_skill"):
                outp = ev / lane / "outputs"
                if not outp.is_dir():
                    continue
                for p in sorted(outp.rglob("*")):
                    if not p.is_file() or p.is_symlink():
                        continue
                    if any(part in SKIP_DIRS for part in p.relative_to(workspace).parts):
                        continue
                    n_files += 1
                    try:
                        mt = p.stat().st_mtime
                    except OSError as e:
                        errors.append(f"{p.relative_to(workspace)}（{e.strerror or e}）")
                        continue
                    if earliest is None or mt < earliest:
                        earliest = mt
    return earliest, n_files, errors


def parse_baseline(path: Path) -> tuple[dict[str, str], dict | None, str | None]:
    """解析 .iteration-baseline。兼容两种格式：
    旧式自由键值（llm-review M 阶段形态，返回 (kv, None, None)）；
    新式含 snapshot: JSON 块（record 生成，返回 (kv, snapshot, None)）。
    读失败 → ({}, None, err)。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return {}, None, f"{e.strerror or e}"
    kv: dict[str, str] = {}
    snapshot: dict | None = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        payload = s[len("snapshot:"):].strip() if s.startswith("snapshot:") else None
        if payload is not None and (not payload or payload.startswith("{")):
            # 新式 snapshot 行：独立行后跟缩进 JSON 块（record 口径），或行内 JSON
            # （"snapshot: {…}" / "snapshot:{…}" 无空格变体同认——评审 5；
            #  payload 非 JSON 的 "snapshot: <值>" 不在此分支，落下方普通键值处理）
            if payload:
                try:
                    snapshot = json.loads(payload)
                except json.JSONDecodeError as e:
                    return kv, None, f"snapshot 块解析失败: {e}"
                i += 1
                continue
            buf: list[str] = []
            i += 1
            while i < len(lines) and (lines[i][:1] in (" ", "\t")):
                buf.append(lines[i].strip())
                i += 1
            try:
                snapshot = json.loads(" ".join(buf))
            except json.JSONDecodeError as e:
                return kv, None, f"snapshot 块解析失败: {e}"
            continue
        if ":" in ln and ln[:1] not in (" ", "\t"):
            k, _, v = ln.partition(":")
            k = k.strip()
            if BASELINE_KEY_RE.fullmatch(k):
                kv[k] = v.strip()
        i += 1
    return kv, snapshot, None


def snapshot_dir_files(d: Path) -> tuple[dict[str, str], list[str]]:
    """目录快照：相对路径 → SHA256。返回 (清单, 读取失败列表)。"""
    out: dict[str, str] = {}
    errors: list[str] = []
    if not d.is_dir():
        return out, [f"快照目录不存在: {d}"]
    for p in sorted(d.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        # SKIP 判定只看快照根内的相对路径分量——p.parts 是绝对路径全部分量，
        # 会把祖先目录名（如工作区恰好位于 …/venv/… 下）误判为跳过而清空快照
        # （评审 1：对齐 earliest_output_mtime 的 relative_to 口径）
        rp = p.relative_to(d)
        if any(part in SKIP_DIRS for part in rp.parts):
            continue
        rel = rp.as_posix()
        try:
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError as e:
            errors.append(f"{rel}（{e.strerror or e}）")
    return out, errors


# ---------------------------------------------------------------- 检查主体 ----

def discipline_check(skill_dir: Path, workspace: Path | None,
                     desc_final_file: Path | None, desc_final_text: str | None
                     ) -> tuple[list[dict], dict]:
    """返回 (报告行, 统计)。行: dict(vid,title,level,ev)。"""
    rows: list[dict] = []
    n_read_err = 0
    read_err_files: list[str] = []

    def add(vid: str, title: str, level: str, ev: str) -> None:
        rows.append(dict(vid=vid, title=title, level=level, ev=ev))

    # ---- V21-1 评测集在场与用例数 ----
    evals, ev_err = load_evals(skill_dir)
    if ev_err == "缺失":
        add("V21-1", "评测集在场（evals/evals.json）", "FAIL",
            "evals/evals.json 缺失——§7.1.1 [M] 评测集为交付物，初始用例数不可验")
    elif ev_err:
        n_read_err += 1
        read_err_files.append(f"evals/evals.json（{ev_err}）")
        add("V21-1", "评测集在场（evals/evals.json）", "FAIL",
            f"evals.json {ev_err}——评测集不可解析，用例数与断言时机均不可验")
    else:
        shape, n, _ = parse_evals_shape(evals)
        if shape == "unknown":
            add("V21-1", "评测集在场（evals/evals.json）", "WARN",
                "evals.json 无 cases/assertions/queries 可识别数组——形态须人工确认")
        else:
            note = ("初始 2–3 条为流程纪律：终态数量无法机械验证初始值，"
                    "是否由 2–3 条起步须经 run-log 留痕佐证（语义归 H）")
            add("V21-1", "评测集在场（evals/evals.json）——用例数记录", "INFO",
                f"形态 {shape}、当前 {n} 条。{note}")

    # ---- V21-2 断言时机（S 机械半）----
    if ev_err or evals is None:
        add("V21-2", "断言添加时机（晚于首轮产出，§7.1.6）", "SKIP",
            "evals.json 缺失或不可解析——断言时机不可验（上游 V21-1 已 FAIL）")
    else:
        shape, n_shape, asserts = parse_evals_shape(evals)
        if shape == "cases-no-asserts":
            add("V21-2", "断言添加时机（晚于首轮产出，§7.1.6）", "WARN",
                f"evals.json 为 cases 评测集形态（{n_shape} 条用例）但断言数组全为空——"
                "§7 断言评测集应先补断言再评测（无断言则断言时机条款不可验）；补齐后复跑")
        elif asserts is None:
            add("V21-2", "断言添加时机（晚于首轮产出，§7.1.6）", "SKIP",
                f"evals.json 为 {shape} 形态（非 §7 断言评测集）——断言时机条款不适用；"
                "质量评估是否遵守断言时机由 runs.md/留痕人工佐证（H）")
        elif workspace is None:
            add("V21-2", "断言添加时机（晚于首轮产出，§7.1.6）", "SKIP",
                f"检测到 {len(asserts)} 条断言但未提供 --workspace（评测工作区）——"
                "无产出时间基线不可机械核对，请提供工作区路径或人工留痕佐证")
        else:
            earliest, n_out, out_errs = earliest_output_mtime(workspace)
            read_err_files.extend(out_errs)
            n_read_err += len(out_errs)
            if n_out == 0 or earliest is None:
                add("V21-2", "断言添加时机（晚于首轮产出，§7.1.6）", "WARN",
                    "workspace 内未发现 iteration-*/eval-*/…/outputs/ 产出文件——"
                    "时间基线缺失，不假 PASS（核对目录结构 §7.2.5 或人工佐证）")
            else:
                # 优先显式时间戳字段，mtime 启发式兜底
                added_at = str(evals.get("assertions_added_at") or "").strip()
                basis = ""
                late = False
                if added_at and ISO_TS_RE.match(added_at):
                    ts = parse_iso_ts(added_at)
                    if ts is not None:
                        late = ts.timestamp() > earliest
                        basis = f"assertions_added_at={added_at}（显式字段口径）"
                    else:
                        late = False
                        basis = f"assertions_added_at={added_at}（格式非法，按未晚于计）"
                else:
                    try:
                        evals_mt = (skill_dir / "evals" / "evals.json").stat().st_mtime
                        late = evals_mt > earliest
                        basis = (f"evals.json mtime 启发式口径（mtime 可被复制/迁移重置，"
                                 f"须在原始工作区运行；建议 record 显式 assertions_added_at 字段）")
                    except OSError as e:
                        n_read_err += 1
                        read_err_files.append(f"evals/evals.json（{e.strerror or e}）")
                        late = False
                        basis = "evals.json mtime 读取失败"
                verdict = "晚于" if late else "未晚于"
                add("V21-2", "断言添加时机（晚于首轮产出，§7.1.6）",
                    "PASS" if late else "FAIL",
                    f"断言 {verdict} 首轮产出（产出 {n_out} 文件、最早 "
                    f"{datetime.fromtimestamp(earliest).strftime('%Y-%m-%d %H:%M:%S')}）；{basis}"
                    "；'未提前定义 PASS/FAIL'语义归 H")

    # ---- V28-1 description 写回一致性 ----
    if desc_final_file is None and desc_final_text is None:
        add("V28-1", "description 写回一致性（选定版本 vs 落盘，§6.5.7）", "SKIP",
            "未提供 --description-final/--description-text——未做 description 优化轮属常态；"
            "若已做选定写回，须补依据文件复跑或人工核对留痕")
    else:
        if desc_final_file is not None:
            try:
                chosen = desc_final_file.read_text(encoding="utf-8").strip()
                src = f"选定版本文件 {desc_final_file.name}"
            except OSError as e:
                n_read_err += 1
                read_err_files.append(f"{desc_final_file}（{e.strerror or e}）")
                chosen = None
                src = ""
        else:
            chosen = desc_final_text.strip()
            src = "--description-text"
        fm_desc, fm_err = load_frontmatter_description(skill_dir / "SKILL.md")
        if fm_err:
            n_read_err += 1
            read_err_files.append(f"SKILL.md（{fm_err}）")
            add("V28-1", "description 写回一致性（选定版本 vs 落盘，§6.5.7）", "FAIL",
                f"SKILL.md 不可验: {fm_err}——A 门亦会 FAIL")
        elif chosen is None:
            add("V28-1", "description 写回一致性（选定版本 vs 落盘，§6.5.7）", "SKIP",
                "选定版本文件读取失败——不可验（详 COV 行）")
        elif fm_desc is None:
            add("V28-1", "description 写回一致性（选定版本 vs 落盘，§6.5.7）", "FAIL",
                "frontmatter 无 description——写回目标缺失")
        elif chosen == fm_desc:
            add("V28-1", "description 写回一致性（选定版本 vs 落盘，§6.5.7）", "PASS",
                f"{src} 与落盘 description 逐字符一致（sha256 {sha256_text(fm_desc)[:12]}…）")
        else:
            add("V28-1", "description 写回一致性（选定版本 vs 落盘，§6.5.7）", "FAIL",
                f"{src} 与落盘不一致（选定 sha256 {sha256_text(chosen)[:12]}… vs "
                f"落盘 {sha256_text(fm_desc or '')[:12]}…）——写回丢失/截断/变形，须修写回")

    # ---- V29-1/V29-2 iteration 基线 ----
    baseline_path = skill_dir / ".verification" / ".iteration-baseline"
    if not baseline_path.is_file():
        add("V29-1", "iteration 基线在场（.iteration-baseline，§15.4）", "WARN",
            "基线文件缺失——已经过 E 阶段验收的技能须 record 补落；"
            "从未进入验收属常态（人工判断本技能所处阶段，不假 PASS 亦不误阻断）")
        add("V29-2", "防覆盖比对（基线 snapshot vs 现状）", "SKIP",
            "无基线可比对")
    else:
        kv, snapshot, bs_err = parse_baseline(baseline_path)
        if bs_err:
            n_read_err += 1
            read_err_files.append(f".iteration-baseline（{bs_err}）")
            add("V29-1", "iteration 基线在场（.iteration-baseline，§15.4）", "FAIL",
                f"基线不可解析: {bs_err}——比对机制失效，须修复或 re-record")
            add("V29-2", "防覆盖比对（基线 snapshot vs 现状）", "SKIP",
                "基线不可解析——无可比内容")
        else:
            missing = [f for f in BASELINE_FIELDS_REQUIRED if not kv.get(f)]
            if missing:
                add("V29-1", "iteration 基线在场（.iteration-baseline，§15.4）", "WARN",
                    f"基线在场但缺必填字段 {missing}（须 iteration/accepted_at/version）——"
                    "补全或 re-record")
            else:
                add("V29-1", "iteration 基线在场（.iteration-baseline，§15.4）", "PASS",
                    f"iteration {kv['iteration']} / version {kv['version']} / "
                    f"accepted_at {kv['accepted_at']}")
            if snapshot is None:
                add("V29-2", "防覆盖比对（基线 snapshot vs 现状）", "SKIP",
                    "旧式键值基线（无 snapshot 块，哈希外引）——无机械比对依据，"
                    "建议 record 重落升级；历史防覆盖暂由人工留痕佐证")
            else:
                snap_dirs = snapshot.get("dirs") or {}
                if not snap_dirs:
                    add("V29-2", "防覆盖比对（基线 snapshot vs 现状）", "WARN",
                        "snapshot 块无 dirs 清单——record 时未指定 --snapshot-dir？")
                else:
                    mismatch: list[str] = []
                    n_cmp = 0
                    for label, entries in snap_dirs.items():
                        d = Path(str(entries.get("root", "")))
                        cur, cur_errs = snapshot_dir_files(d)
                        n_cmp += len(cur)
                        base_files = entries.get("files") or {}
                        for rel, h in base_files.items():
                            if rel not in cur:
                                mismatch.append(f"{label}/{rel}: 已删除")
                            elif cur[rel] != h:
                                mismatch.append(f"{label}/{rel}: 内容已变")
                        for rel in cur:
                            if rel not in base_files:
                                mismatch.append(f"{label}/{rel}: 基线外新增")
                        read_err_files.extend(f"{label}/{e}" for e in cur_errs)
                        n_read_err += len(cur_errs)
                    if mismatch:
                        add("V29-2", "防覆盖比对（基线 snapshot vs 现状）", "FAIL",
                            "; ".join(mismatch[:5]) +
                            (f"（另 {len(mismatch) - 5} 处略）" if len(mismatch) > 5 else "")
                            + "——历史结果被覆盖/篡改，违反 §15.4 迭代留痕")
                    else:
                        add("V29-2", "防覆盖比对（基线 snapshot vs 现状）", "PASS",
                            f"比对 {len(snap_dirs)} 个快照目录 {n_cmp} 文件，哈希全部一致")

    # ---- COV 覆盖行 + 覆盖不全降级 ----
    cov_parts = ["V21-1/2 评测产物、V28 写回依据、V29 基线"]
    if read_err_files:
        cov_parts.append("读取失败 " + "; ".join(read_err_files[:3]) +
                         ("（覆盖不全，PASS 行已同步降 WARN）" if n_read_err else ""))
    add("COV", "扫描覆盖", "WARN" if n_read_err else "INFO", "; ".join(cov_parts))

    if n_read_err:
        for r in rows:
            if r["level"] == "PASS":
                r["level"] = "WARN"
                r["ev"] += f"（WARN 缘由: {n_read_err} 个文件读取失败，覆盖不全）"

    stats = dict(read_err=n_read_err,
                 skips=sum(1 for r in rows if r["level"] == "SKIP"))
    return rows, stats


# ---------------------------------------------------------------- record 模式 ----

def record_baseline(skill_dir: Path, version: str, iteration: str,
                    accepted_at: str, acceptance_report: str | None,
                    snapshot_dir: Path | None) -> tuple[str, str | None]:
    """写/更新 .iteration-baseline（V29 record）。返回 (落盘文本, 错误或 None)。
    兼容既有键值格式 + 追加 snapshot 块（新式，V29-2 机械比对依据）。"""
    snap_lines: list[str] = []
    snap_obj: dict = {"dirs": {}}
    if snapshot_dir is not None:
        files, errs = snapshot_dir_files(snapshot_dir)
        if errs:
            return "", f"快照目录读取失败: {'; '.join(errs[:3])}"
        if not files:
            return "", f"快照目录无文件: {snapshot_dir}"
        snap_obj["dirs"][snapshot_dir.name] = {
            "root": str(snapshot_dir),
            "files": files,
        }
    lines = [
        f"iteration: {iteration}",
        f"accepted_at: {accepted_at}",
        f"version: {version}",
    ]
    if acceptance_report:
        lines.append(f"acceptance_report: {acceptance_report}")
    lines.append("note: V29 iteration 基线（eval_discipline.py record 生成）——验收通过时点快照，防历史结果覆盖")
    if snapshot_dir is not None:
        # 独立行 + 缩进 JSON（与 parse_baseline 的块形态口径一致）
        lines.append("snapshot:")
        lines.append("  " + json.dumps(snap_obj, ensure_ascii=False, sort_keys=True))
    text = "\n".join(lines) + "\n"
    out = skill_dir / ".verification" / ".iteration-baseline"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
    except OSError as e:
        return "", f"基线落盘失败: {out} — {e}"
    return text, None


# ---------------------------------------------------------------- 报告与入口 ----

class _BlockArgParser(argparse.ArgumentParser):
    """参数错误统一 exit 1（阻断码）——argparse 默认 exit 2 撞 WARN 码
    （naming_precheck v1.0.1 评审 5 纪律，v1.0.3 error() 覆写口径全工具对齐）。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"错误: {message}。下一步: 按用法核对参数后重试。", file=sys.stderr)
        raise SystemExit(1)


_ORDER = {"V21-1": 1, "V21-2": 2, "V28-1": 3, "V29-1": 4, "V29-2": 5, "COV": 50}


def build_report(skill_dir: Path, rows: list[dict], stats: dict,
                 workspace: Path | None, mode: str) -> str:
    has_fail = any(r["level"] == "FAIL" for r in rows)
    has_warn = any(r["level"] == "WARN" for r in rows)
    judged = [r for r in rows if r["level"] in ("PASS", "FAIL")]
    skips = sum(1 for r in rows if r["level"] == "SKIP")
    lines = [
        "# 评测纪律三门报告（eval_discipline.py）",
        "",
        f"- 技能: {skill_dir.name}（{skill_dir}）",
        f"- 工具版本: {VERSION}",
        f"- 模式: {mode}" + (f"；评测工作区: {workspace}" if workspace else "；未提供评测工作区（V21-2 相关行 SKIP）"),
        "- 口径: V21 断言时机（§7.1.5/§7.1.6，[M]，语义半归 H）/V28 写回一致性（§6.5.7，[S]）"
        "/V29 iteration 基线（§15.4，[S]）；SKIP 不计警告（须人工留痕佐证，不豁免上游条款）",
        f"- 总结论: {'FAIL（存在阻断项）' if has_fail else ('WARN（需人工复核）' if has_warn else 'PASS')}"
        + (f"（SKIP {skips} 行）" if skips else ""),
        "",
        "| 项 | 检查内容 | 结论 | 证据 |",
        "|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: (_ORDER.get(r["vid"], 99), r["vid"])):
        lines.append(f"| {r['vid']} | {r['title']} | {r['level']} | {r['ev']} |")
    lines += [
        "",
        f"> 判定统计: {sum(1 for r in judged if r['level'] == 'PASS')}/{len(judged)} PASS。"
        "初始用例数与'未提前定义 PASS/FAIL'属流程语义（H）；本工具 FAIL 不得自动改写评测产物或基线。",
    ]
    if has_fail:
        lines[-1] += " [M]/[S] FAIL 阻断：先处置再进入下一阶段。"
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = _BlockArgParser(
        description="Agent Skill 评测纪律三门（V21 断言时机 / V28 写回一致性 / V29 iteration 基线）")
    ap.add_argument("skill_dir", nargs="?", help="待检技能目录（含 SKILL.md 与 .verification/）")
    ap.add_argument("--workspace", help="评测工作区根（§7.2.5 结构 <skill>-workspace/）；V21-2 断言时机比对基线")
    ap.add_argument("--description-final", help="description 选定版本文件（V28-1 一致性依据）")
    ap.add_argument("--description-text", help="description 选定版本文本（V28-1 一致性依据，与 --description-final 二选一）")
    ap.add_argument("--mode", choices=("check", "record"), default="check",
                    help="check=三门检查（默认）；record=写/更新 V29 基线")
    ap.add_argument("--version", help="record: 验收通过版本号")
    ap.add_argument("--iteration", help="record: iteration 号")
    ap.add_argument("--accepted-at", help="record: 验收通过时点（ISO 8601，默认当前时间）")
    ap.add_argument("--acceptance-report", help="record: 验收报告路径留痕")
    ap.add_argument("--snapshot-dir", help="record: 快照目录（逐文件 SHA256 入基线 snapshot 块，V29-2 比对依据）")
    ap.add_argument("--out", help="报告落盘路径（建议 .verification/m1-s/eval-discipline.md）")
    a = ap.parse_args()

    if not a.skill_dir:
        print("错误: 缺技能目录参数。用法: python eval_discipline.py <skill_dir> "
              "[--workspace <dir>] [--description-final <file> | --description-text <text>] "
              "[--mode record --version V --iteration N [--snapshot-dir <dir>]] [--out report.md]。",
              file=sys.stderr)
        return 1

    skill_dir = Path(a.skill_dir)
    if not skill_dir.is_dir():
        print(f"错误: 目录不存在: {skill_dir}。下一步: 核对路径后重试。", file=sys.stderr)
        return 1

    if a.mode == "record":
        if not a.version or not a.iteration:
            print("错误: record 模式须 --version 与 --iteration。"
                  "用法: --mode record --version v1.0 --iteration 1 [--accepted-at ISO] "
                  "[--acceptance-report <path>] [--snapshot-dir <dir>]。", file=sys.stderr)
            return 1
        accepted_at = a.accepted_at or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        if not a.snapshot_dir:
            print("提示: 未指定 --snapshot-dir——基线为键值格式（无 snapshot 块），"
                  "V29-2 防覆盖将 SKIP（无机械比对依据）。下一步: 如需机械比对，"
                  "指定快照目录（评测工作区或 .verification/iteration-N/）后重落 record。",
                  file=sys.stderr)
        text, err = record_baseline(
            skill_dir, a.version, a.iteration, accepted_at,
            a.acceptance_report, Path(a.snapshot_dir) if a.snapshot_dir else None)
        if err:
            print(f"错误: {err}。下一步: 核对路径权限后重试。", file=sys.stderr)
            return 1
        print(f"[已落盘] {skill_dir / '.verification' / '.iteration-baseline'}")
        print(text, end="")
        return 0

    # check 模式互斥参数核对
    if a.description_final and a.description_text:
        print("错误: --description-final 与 --description-text 二选一。"
              "用法: 二者只提供一个作为 V28-1 选定版本依据。", file=sys.stderr)
        return 1
    if a.description_text is not None and not a.description_text.strip():
        print("错误: --description-text 为空——description 选定版本不应为空"
              "（空值会产生误导性的\"写回不一致\"FAIL）。"
              "下一步: 提供非空选定文本，或改用 --description-final <file>。",
              file=sys.stderr)
        return 1

    workspace = Path(a.workspace) if a.workspace else None
    if workspace is not None and not workspace.is_dir():
        print(f"错误: 评测工作区目录不存在: {workspace}。下一步: 核对路径后重试，"
              "或省略 --workspace（V21-2 记 SKIP）。", file=sys.stderr)
        return 1
    desc_file = Path(a.description_final) if a.description_final else None
    if desc_file is not None and not desc_file.is_file():
        print(f"错误: 选定版本文件不存在: {desc_file}。下一步: 核对路径后重试，"
              "或改用 --description-text。", file=sys.stderr)
        return 1

    rows, stats = discipline_check(skill_dir, workspace, desc_file, a.description_text)
    report = build_report(skill_dir, rows, stats, workspace, "check")
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

    has_fail = any(r["level"] == "FAIL" for r in rows)
    has_warn = any(r["level"] == "WARN" for r in rows)
    return 1 if has_fail else (2 if has_warn else 0)


if __name__ == "__main__":
    sys.exit(main())
