#!/usr/bin/env python3
"""deliver_check.py — Agent Skill 存在性/schema 门七项（交付物 + 运行产物 schema + license + B1 留档）。

落实《Agent-Skill 生命周期验证方案》S1⑥ 收官批次（承载方式：独立脚本——
存在性核对/JSON schema 校验/关键词留痕初筛均机械可判，沿 dep_check 合一先例；
检查项编号 EX-1~7 为工具本地编号，V1–V29 已被 V 系列占用，映射在各行标题显式标注）：

  EX-1 [§15.7/M1-7 M] 交付物存在性：SKILL.md + evals/evals.json（编写期产物）→
          缺失 FAIL；acceptance-report.md（验收报告，M1 时点项）→ 缺失 WARN
  EX-2 [§7.7.4/E3-2 M] feedback.json 落盘 + 键结构校验：双文档口径同认——
          A 操作手册/清单 `text/passed/evidence` 结构；B 总表 §7.7.4 键=用例目录名
          值=反馈文本（空字符串=通过）；未产出 SKIP（E3 复核后须落盘并复检）
  EX-3 [§7.2.6/E-S M] grading.json schema：字段名必须 text/passed/evidence、
          summary 必须为 passed/failed/total/pass_rate；未见 summary → WARN
          （门 D 类工件人工甄别）；未产出 SKIP
  EX-4 [§2.4.1–§2.4.2/V15 S] license：frontmatter license 字段长度启发式
          （>120 字符或多行 → WARN 条款内嵌嫌疑）+ 随包 LICENSE 文件存在性；
          均未声明 → SKIP（内部使用不适用；对外交付时 V15 升 [M] 须补齐）
  EX-5 [§5.1.3/B1-1 S] 反向测试记录存在性：.verification/ 下 md/txt 关键词
          初筛（"反向测试"）——未见 → WARN（留档可能在技能树外素材档案，人工确认）
  EX-6 [§5.1.6/B1-2 S] 执行→修订闭环记录：.verification/ 下 iteration-N 目录
          （含文件）在场核对——手段表口径"核对 iteration 记录"
  EX-7 [§5.1.9/B1-3 S] 执行轨迹分析记录：.verification/ 下关键词（"轨迹"）
          初筛——未见 → WARN

口径声明（机械初筛局限，均写入证据）：
- B1 三类记录无全项目固定文件名约定——关键词初筛 + 人工确认留档位置（清单 §0
  口径："记录是否存在"可脚本核对，结论裁决归 H）
- feedback/grading 为测试期运行产物：W 阶段未产出属预期 → SKIP 不计警告
  （人工留痕佐证），进入 E3/E 阶段后须落盘并复检
- license 第三方素材许可留档核对（V15 后半）为文档口径，机械部分仅核对随包
  LICENSE 文件在场
- frontmatter 解析为 YAML 子集（license 单键 + 缩进续行计数），不做全量 YAML
- BOM：SKILL.md 读入用 utf-8-sig 剥 BOM（对齐 host_compat 口径）
- references//assets/ 内 feedback/grading.json=示例口径——不判 FAIL 降 WARN 人工甄别
  （对齐 dep_check DEP-3）；B 口径 feedback 按"全字符串值 dict"机械判定，键名
  无 / 或 - 分隔时提示误命中元数据文件可能；grading summary 值类型弱检（非数值 WARN）

退出码: 0=全 PASS（SKIP 不计警告，对齐 check_skill A1 口径）；
1=任一 FAIL 或参数错误（阻断）；2=无 FAIL 但有 WARN。
全部参数错误（缺参自查 + argparse 解析错误）统一 exit 1（_BlockArgParser，
撞码纪律全工具对齐）；缺参自查消息含"用法"（V6 冒烟 C2 契约）。

用法:
    python deliver_check.py <skill_dir> [--out report.md]

注: 本工具只做存在性/结构初筛；记录内容质量（B1 结论、反馈具体性）归 L/H，
B1-4 终审、E3-1 逐用例复核、V15 第三方素材合规裁决均不在本工具范围。

版本: v1.0.2（2026-10-03 二轮追加评审 3 条处置；v1.0.1 同日首轮 8 条
      （1 高+2 中+1 中弱改进+3 低+1 极低=8：6 改代码+1 docstring+1 保留现状），
      S1⑥ 收官批次）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- 常量表 ----

VERSION = "v1.0.2"

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}

LICENSE_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING",
                 "COPYING.md", "COPYING.txt")

FM_LICENSE_RE = re.compile(r"^license[ \t]*:[ \t]*(.*)[ \t]*$", re.M)

ITERATION_DIR_RE = re.compile(r"^iteration-\d+$")

# license 字段长度启发式：超过视为"条款内嵌嫌疑"（完整条款须移随包 LICENSE）
LICENSE_LEN_WARN = 120

SUMMARY_KEYS = {"passed", "failed", "total", "pass_rate"}

RECORD_EXTS = (".md", ".txt")

KW_REVERSE = "反向测试"   # §5.1.3 "删掉会错吗"记录
KW_TRACE = "轨迹"          # §5.1.9 执行轨迹分析记录


# ---------------------------------------------------------------- 基础设施 ----

def frontmatter_block(md_text: str) -> str:
    """取 SKILL.md frontmatter 块（首行 --- 至次个 ---）。非 frontmatter 返回空。
    起手剥 BOM——\\ufeff 非 str.strip() 空白且 utf-8 codec 不剥（须 utf-8-sig），
    不剥则首行 "\\ufeff---" 判空整块（与 host_compat utf-8-sig 口径对齐）。"""
    md_text = md_text.lstrip("\ufeff")
    lines = md_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i])
    return ""


def license_field(fm: str) -> tuple[str | None, int, bool]:
    """frontmatter license 单键抽取。返回 (值或 None, 多行续行数, 是否多 license 键)。
    YAML 子集口径。块标量（| > 及其修饰）视为已声明，返回指示符本身+续行数
    （→ 多行 WARN 依据）；重复顶层键 YAML 语义非法，第三返回值供人工甄别。"""
    ms = list(FM_LICENSE_RE.finditer(fm))
    if not ms:
        return None, 0, False
    dup = len(ms) > 1
    m = ms[0]
    val = m.group(1).strip().strip("\"'")
    after = fm[m.end():].splitlines()

    def count_cont() -> int:
        rest = after[1:] if after and after[0] == "" else after  # 跳过 license 行自身余量
        n = 0
        for ln in rest:
            if ln[:1] in (" ", "\t") and ln.strip():
                n += 1
            else:
                break
        return n

    if val in ("|", ">", "|-", ">-", "|+", ">+"):
        return val, count_cont(), dup
    if not val:
        return None, count_cont(), dup
    return val, 0, dup


def iter_vfiles(skill_dir: Path) -> list[tuple[Path, str]]:
    """遍历 .verification/ 下 md/txt 文本文件（记录留痕扫描域）。
    仅 .md/.txt——.log/.rst/.yaml 等漏检属关键词初筛局限（docstring 声明）。"""
    out: list[tuple[Path, str]] = []
    vd = skill_dir / ".verification"
    if not vd.is_dir():
        return out
    for p in sorted(vd.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(vd).parts):
            continue
        if p.suffix.lower() not in RECORD_EXTS:
            continue
        try:
            out.append((p, p.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return out


def find_json_files(skill_dir: Path, name: str) -> list[Path]:
    """技能树内 rglob 指定 json（.verification 为留痕主域，一并扫描）。"""
    hits: list[Path] = []
    for p in sorted(skill_dir.rglob(name)):
        if not p.is_file() or p.is_symlink():
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(skill_dir).parts):
            continue
        hits.append(p)
    return hits


def is_sample_path(p: Path, skill_dir: Path) -> bool:
    """references//assets/ 内文件=示例口径（不判 FAIL，降 WARN 人工甄别——
    与 dep_check DEP-3 对 pyproject/夹具的处置一致）。"""
    return any(x in ("references", "assets")
               for x in p.relative_to(skill_dir).parts[:-1])


def walk_assertion_dicts(node, found: list[dict]) -> None:
    """递归收集含断言形态（有 text 键的 dict）的节点。"""
    if isinstance(node, dict):
        if isinstance(node.get("text"), str):
            found.append(node)
        for v in node.values():
            walk_assertion_dicts(v, found)
    elif isinstance(node, list):
        for v in node:
            walk_assertion_dicts(v, found)


def validate_grading(data, rel: str) -> tuple[list[str], list[str]]:
    """§7.2.6 grading.json schema。返回 (fails, warns)。"""
    fails: list[str] = []
    warns: list[str] = []
    if not isinstance(data, dict):
        return [f"{rel}: 顶层非 JSON 对象"], []
    entries: list[dict] = []
    walk_assertion_dicts(data, entries)
    if len(entries) > 20:
        warns.append(f"{rel}: 断言项 {len(entries)} 条超检查上限，仅检查前 20 条"
                     f"（另 {len(entries) - 20} 条未检查）——全量核对须人工")
    for e in entries[:20]:
        t = e["text"][:24]
        if "passed" not in e:
            fails.append(f"{rel}: 断言项 \"{t}…\" 缺 passed 字段"
                         "（字段名须为 text/passed/evidence，§7.2.6）")
        elif not isinstance(e["passed"], bool):
            fails.append(f"{rel}: 断言项 \"{t}…\" passed 非布尔")
        if "evidence" not in e:
            warns.append(f"{rel}: 断言项 \"{t}…\" 无 evidence")
    if "summary" in data:
        s = data["summary"]
        if not isinstance(s, dict) or not SUMMARY_KEYS.issubset(s):
            keys = sorted(s) if isinstance(s, dict) else type(s).__name__
            fails.append(f"{rel}: summary 字段不符（须为 passed/failed/total/"
                         f"pass_rate，§7.2.6）——实际 {keys}")
        else:
            # 弱类型检查：规范原文仅约定字段名，但 passed/failed/total/pass_rate
            # 语义上应为数值——字符串数字（"1"）等记 WARN 人工甄别
            bad = [k for k in sorted(SUMMARY_KEYS)
                   if isinstance(s[k], bool)
                   or not isinstance(s[k], (int, float))]
            if bad:
                warns.append(f"{rel}: summary 键 {bad} 值非数值——语义应为 "
                             "int/float，类型人工甄别（规范仅约定字段名）")
    else:
        warns.append(f"{rel}: 未见 summary{sorted(SUMMARY_KEYS)}"
                     "——测试期工作区产物须含；门 D 类工件人工甄别")
    # 无断言条目一律 WARN——含"只有 summary 不列明细"形态（语义上不合理，
    # 汇总须有明细支撑）与全不可识别形态，均人工甄别
    if not entries:
        warns.append(f"{rel}: 未识别出断言形态条目"
                     + ("——仅有 summary 不列明细，汇总须有明细支撑" if "summary" in data
                        else "——结构人工甄别"))
    return fails, warns


def validate_feedback(data, rel: str) -> tuple[list[str], list[str], str | None]:
    """feedback.json 双文档口径校验。返回 (fails, warns, 命中格式)。"""
    fails: list[str] = []
    warns: list[str] = []
    if isinstance(data, list):
        entries: list[dict] = []
        walk_assertion_dicts(data, entries)
        if entries:
            return [], warns, "A（操作手册/清单 text/passed/evidence 结构，列表形态）"
        if not data:
            warns.append(f"{rel}: 空数组——E3 复核反馈未落任何条目")
            return [], warns, None
        return [f"{rel}: 列表项不匹配 text/passed/evidence 结构（§7.7.4）"], [], None
    if not isinstance(data, dict):
        return [f"{rel}: 顶层非 JSON 对象/数组"], [], None
    if data and all(isinstance(v, str) for v in data.values()):
        empty = [k for k, v in data.items() if not v.strip()]
        ev = f"{rel}: 口径 B（总表 §7.7.4 键=用例目录名→反馈文本）"
        if empty:
            warns.append(f"{ev}；{len(empty)} 个用例空反馈=通过（§7.7.3）")
        # 弱约束：B 口径按"全字符串值 dict"机械判定，键应形如用例目录名
        # （含 / 或 - 分隔）——无任何分隔符时提示误命中元数据文件的可能
        if not any("/" in k or "-" in k for k in data):
            warns.append(f"{rel}: 口径 B 键名均无 / 或 - 分隔符——若为误命中的"
                         "元数据文件（键应为用例目录名）须人工甄别")
        return [], warns, "B"
    entries = []
    walk_assertion_dicts(data, entries)
    if entries:
        return [], warns, "A（操作手册/清单 text/passed/evidence 结构）"
    if not data:
        warns.append(f"{rel}: 空对象——E3 复核反馈未落任何条目"
                     "（全通过也应逐用例留键，空字符串=通过）")
        return [], warns, None
    return [f"{rel}: 结构不匹配双文档口径（A text/passed/evidence 或 "
            "B 键=用例目录名→文本，§7.7.4）"], [], None


# ---------------------------------------------------------------- 检查主体 ----

def deliver_check(skill_dir: Path) -> tuple[list[dict], dict]:
    """返回 (报告行, 统计)。行: dict(vid,title,level,ev)。"""
    rows: list[dict] = []
    n_read_err = 0
    read_err_files: list[str] = []

    def add(vid: str, title: str, level: str, ev: str) -> None:
        rows.append(dict(vid=vid, title=title, level=level, ev=ev))

    # ---- EX-1 交付物存在性（§15.7/M1-7）----
    missing: list[str] = []
    skill_md = skill_dir / "SKILL.md"
    md_text: str | None = None
    if skill_md.is_file():
        try:
            # utf-8-sig 剥 BOM（对齐 host_compat 口径）；errors=replace 容坏字节
            md_text = skill_md.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as e:
            n_read_err += 1
            read_err_files.append(f"SKILL.md（{e.strerror or e}）")
            missing.append("SKILL.md（读取失败）")
    else:
        missing.append("SKILL.md")
    evals_json = None
    for cand in ("evals/evals.json", "evals.json"):
        p = skill_dir / cand
        if p.is_file():
            evals_json = p
            break
    if evals_json is None:
        missing.append("evals/evals.json")
    report_md = skill_dir / ".verification" / "acceptance-report.md"
    if missing:
        add("EX-1", "交付物存在性（SKILL.md + evals.json + 验收报告，§15.7/M1-7）", "FAIL",
            "缺失: " + ", ".join(missing)
            + "——编写期产物（SKILL.md/evals.json）缺失阻断；验收报告为 M1 时点项")
    elif not report_md.is_file():
        add("EX-1", "交付物存在性（SKILL.md + evals.json + 验收报告，§15.7/M1-7）", "WARN",
            ".verification/acceptance-report.md 未出——M1 终检时点项（W/E 阶段"
            "预期缺失，进入 M1 前须补齐；SKILL.md+evals.json 已在场）")
    else:
        add("EX-1", "交付物存在性（SKILL.md + evals.json + 验收报告，§15.7/M1-7）", "PASS",
            "SKILL.md + evals/evals.json + .verification/acceptance-report.md 齐备")

    # ---- EX-2 feedback.json 落盘 + schema（§7.7.4/E3-2）----
    fb_files = find_json_files(skill_dir, "feedback.json")
    if not fb_files:
        add("EX-2", "feedback.json 落盘与结构（text/passed/evidence，§7.7.4/E3-2）", "SKIP",
            "技能树内未产出 feedback.json——E3 人工复核运行产物（W 阶段预期缺失，"
            "SKIP 不计警告；进入 E3 后须落盘并复检）")
    else:
        fails: list[str] = []
        warns: list[str] = []
        fmts: list[str] = []
        for p in fb_files[:5]:
            rel = p.relative_to(skill_dir).as_posix()
            sample = is_sample_path(p, skill_dir)
            try:
                data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except (OSError, json.JSONDecodeError) as e:
                if sample:
                    warns.append(f"{rel}: 示例口径解析失败（references//assets/ 内，"
                                 "人工甄别）")
                else:
                    fails.append(f"{rel}: 解析失败（{e}）")
                    n_read_err += 1
                    read_err_files.append(rel)
                continue
            f, w, fmt = validate_feedback(data, rel)
            if sample:
                warns += w
                warns.append(f"{rel}: 位于 references//assets/——示例口径，"
                             "人工甄别" + (f"（结构违规 {len(f)} 项不判 FAIL）"
                                           if f else ""))
                continue
            fails += f
            warns += w
            if fmt:
                fmts.append(f"{rel}（口径 {fmt}）")
        if fails:
            ev = "; ".join(fails[:3]) + "——feedback.json 落盘且结构正确为 [M]"
            if warns:
                ev += "；WARN 并列: " + "; ".join(warns[:2])
            add("EX-2", "feedback.json 落盘与结构（text/passed/evidence，§7.7.4/E3-2）",
                "FAIL", ev)
        elif fmts:
            ev = "; ".join(fmts[:3]) + "——双文档口径同认"
            if warns:
                ev += "；" + "; ".join(warns[:2])
            add("EX-2", "feedback.json 落盘与结构（text/passed/evidence，§7.7.4/E3-2）",
                "PASS", ev)
        else:
            add("EX-2", "feedback.json 落盘与结构（text/passed/evidence，§7.7.4/E3-2）",
                "WARN", "; ".join(warns[:3]) + "——人工复核留痕口径")

    # ---- EX-3 grading.json schema（§7.2.6/E-S）----
    gr_files = find_json_files(skill_dir, "grading.json")
    if not gr_files:
        add("EX-3", "grading.json schema（text/passed/evidence + summary 四键，§7.2.6）",
            "SKIP", "技能树内未产出 grading.json——测试期运行产物（未进入测试工作区"
            "属预期，SKIP 不计警告）")
    else:
        fails: list[str] = []
        warns: list[str] = []
        for p in gr_files[:5]:
            rel = p.relative_to(skill_dir).as_posix()
            sample = is_sample_path(p, skill_dir)
            try:
                data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except (OSError, json.JSONDecodeError) as e:
                if sample:
                    warns.append(f"{rel}: 示例口径解析失败（references//assets/ 内，"
                                 "人工甄别）")
                else:
                    fails.append(f"{rel}: 解析失败（{e}）")
                    n_read_err += 1
                    read_err_files.append(rel)
                continue
            f, w = validate_grading(data, rel)
            if sample:
                warns += w
                warns.append(f"{rel}: 位于 references//assets/——示例口径，"
                             "人工甄别" + (f"（结构违规 {len(f)} 项不判 FAIL）"
                                           if f else ""))
                continue
            fails += f
            warns += w
        if fails:
            ev = "; ".join(fails[:3]) + "——字段名须为 text/passed/evidence，" \
                 "summary 须为 passed/failed/total/pass_rate（§7.2.6）"
            if warns:
                ev += "；WARN 并列: " + "; ".join(warns[:2])
            add("EX-3", "grading.json schema（text/passed/evidence + summary 四键，§7.2.6）",
                "FAIL", ev)
        elif warns:
            add("EX-3", "grading.json schema（text/passed/evidence + summary 四键，§7.2.6）",
                "WARN", "; ".join(warns[:3]) + "——无字段违规，人工甄别项")
        else:
            ev = f"{len(gr_files)} 个 grading.json 断言字段口径合规"
            add("EX-3", "grading.json schema（text/passed/evidence + summary 四键，§7.2.6）",
                "PASS", ev)

    # ---- EX-4 license（§2.4.1–2.4.2/V15）----
    lic_val, lic_cont, lic_dup = (None, 0, False)
    if md_text is not None:
        lic_val, lic_cont, lic_dup = license_field(frontmatter_block(md_text))
    lic_file = next((n for n in LICENSE_FILES if (skill_dir / n).is_file()), None)
    if lic_val is None and lic_file is None:
        add("EX-4", "license 许可合规初筛（§2.4.1–2.4.2/V15）", "SKIP",
            "frontmatter 无 license 字段且无随包 LICENSE 文件——内部使用不适用"
            "（对外交付时 V15 升 [M]：须声明许可、完整条款随包、第三方素材许可留档）")
    else:
        warns: list[str] = []
        if lic_dup:
            warns.append("frontmatter 含多个 license 键——YAML 重复顶层键非法，"
                         "人工甄别（工具取首个判定）")
        if lic_val is not None:
            if len(lic_val) > LICENSE_LEN_WARN or lic_cont:
                warns.append(f"license 字段 {len(lic_val)} 字符/{lic_cont} 续行——"
                             "条款内嵌嫌疑，完整条款须移随包 LICENSE 文件（§2.4.2）")
            if lic_file is None:
                warns.append(f"license 字段已声明（{lic_val[:20]}）但随包无 "
                             f"{'/'.join(LICENSE_FILES[:3])} 等 LICENSE 文件——§2.4.2")
        ev = []
        ev.append(f"license 字段: {lic_val[:30] if lic_val else '无'}"
                  if lic_val else "license 字段: 无（随包 LICENSE 在场）")
        ev.append(f"随包 LICENSE 文件: {lic_file or '无'}")
        if warns:
            add("EX-4", "license 许可合规初筛（§2.4.1–2.4.2/V15）", "WARN",
                "; ".join(warns) + "；" + "；".join(ev)
                + "；第三方素材许可留档归人工核对（V15 后半）")
        else:
            add("EX-4", "license 许可合规初筛（§2.4.1–2.4.2/V15）", "PASS",
                "；".join(ev) + "；字段简短、条款随包口径合规"
                "（第三方素材许可留档归人工核对）")

    # ---- EX-5/6/7 B1 三类留档存在性（关键词/目录初筛 + 人工确认）----
    vfiles = iter_vfiles(skill_dir)
    if not vfiles and not (skill_dir / ".verification").is_dir():
        add("EX-5", "反向测试记录存在性（§5.1.3/B1-1）", "SKIP",
            "无 .verification/ 目录——编写期留痕未建（人工确认记录位置）")
        add("EX-6", "执行→修订闭环记录（§5.1.6/B1-2）", "SKIP",
            "无 .verification/ 目录——iteration 记录未建（人工确认记录位置）")
        add("EX-7", "执行轨迹分析记录（§5.1.9/B1-3）", "SKIP",
            "无 .verification/ 目录——轨迹分析留痕未建（人工确认记录位置）")
    else:
        hit_rev = [p for p, t in vfiles if KW_REVERSE in t]
        hit_trace = [p for p, t in vfiles if KW_TRACE in t]
        iters = []
        vd = skill_dir / ".verification"
        if vd.is_dir():
            for d in sorted(vd.rglob("*")):
                if d.is_dir() and ITERATION_DIR_RE.match(d.name) \
                        and any(x.is_file() for x in d.rglob("*")):
                    if not any(part in SKIP_DIRS
                               for part in d.relative_to(vd).parts):
                        iters.append(d)
        if hit_rev:
            add("EX-5", "反向测试记录存在性（§5.1.3/B1-1）", "PASS",
                f".verification/ 内 {len(hit_rev)} 个文件含\"{KW_REVERSE}\"留痕"
                f"（如 {hit_rev[0].relative_to(skill_dir).as_posix()}）——"
                "记录内容质量归 L/H（B1-4）")
        else:
            add("EX-5", "反向测试记录存在性（§5.1.3/B1-1）", "WARN",
                f".verification/ 内 md/txt 未检出\"{KW_REVERSE}\"留痕——关键词初筛"
                "局限：记录可能在技能树外素材档案或以他名留档，人工确认")
        if iters:
            names = ", ".join(d.name for d in iters[:3])
            add("EX-6", "执行→修订闭环记录（§5.1.6/B1-2）", "PASS",
                f".verification/ 下 iteration 记录在场: {names}"
                f"（共 {len(iters)} 个）——手段表口径\"核对 iteration 记录\"")
        else:
            add("EX-6", "执行→修订闭环记录（§5.1.6/B1-2）", "WARN",
                ".verification/ 下未见 iteration-N 目录（含文件）——真实执行→修订"
                "闭环留痕人工确认（K 流程可能在案他处）")
        if hit_trace:
            add("EX-7", "执行轨迹分析记录（§5.1.9/B1-3）", "PASS",
                f".verification/ 内 {len(hit_trace)} 个文件含\"{KW_TRACE}\"留痕"
                f"（如 {hit_trace[0].relative_to(skill_dir).as_posix()}）——"
                "轨迹三类缺陷归因质量归 L/H")
        else:
            add("EX-7", "执行轨迹分析记录（§5.1.9/B1-3）", "WARN",
                f".verification/ 内 md/txt 未检出\"{KW_TRACE}\"分析留痕——"
                "关键词初筛局限，人工确认留档位置")

    # ---- COV 覆盖行 + 覆盖不全降级 ----
    cov_parts = ["EX-1~7 SKILL.md+evals.json+验收报告+feedback/grading schema"
                 "+license+B1 留档（.verification/ 全树）"]
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


# ---------------------------------------------------------------- 报告与入口 ----

class _BlockArgParser(argparse.ArgumentParser):
    """参数错误统一 exit 1（阻断码）——argparse 默认 exit 2 撞 WARN 码
    （撞码纪律全工具对齐）。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"错误: {message}。下一步: 按用法核对参数后重试。", file=sys.stderr)
        raise SystemExit(1)


_ORDER = {"EX-1": 1, "EX-2": 2, "EX-3": 3, "EX-4": 4,
          "EX-5": 5, "EX-6": 6, "EX-7": 7, "COV": 50}


def build_report(skill_dir: Path, rows: list[dict], stats: dict) -> str:
    has_fail = any(r["level"] == "FAIL" for r in rows)
    has_warn = any(r["level"] == "WARN" for r in rows)
    judged = [r for r in rows if r["level"] in ("PASS", "FAIL")]
    skips = sum(1 for r in rows if r["level"] == "SKIP")
    lines = [
        "# 存在性/schema 门报告（deliver_check.py）",
        "",
        f"- 技能: {skill_dir.name}（{skill_dir}）",
        f"- 工具版本: {VERSION}",
        "- 口径: §15.7/M1-7 交付物（[M]）/§7.7.4+E3-2 feedback.json（[M]）"
        "/§7.2.6 grading.json（[M]）/§2.4.1–2.4.2+V15 license（[S]）"
        "/§5.1.3+§5.1.6+§5.1.9 B1 留档（[S]）；SKIP 不计警告（须人工留痕佐证）",
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
        "B1 三类记录的关键词初筛局限（留档可能在技能树外素材档案）与 feedback/grading"
        " 为测试期运行产物（未产出属预期）均已写入证据；记录内容质量（B1-4 终审、"
        "E3-1 逐用例复核、反馈具体性、V15 第三方素材合规）归 L/H，不在本工具范围。",
    ]
    if has_fail:
        lines[-1] += " [M] FAIL 阻断：先处置再进入下一阶段。"
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = _BlockArgParser(
        description="Agent Skill 存在性/schema 门七项（§15.7 交付物 / §7.7.4+§7.2.6 "
                    "运行产物 schema / §2.4+V15 license / B1 留档）")
    ap.add_argument("skill_dir", nargs="?", help="待检技能目录（含 SKILL.md）")
    ap.add_argument("--out", help="报告落盘路径（建议 .verification/m1-s/deliver-check.md）")
    a = ap.parse_args()

    if not a.skill_dir:
        print("错误: 缺技能目录参数。用法: python deliver_check.py <skill_dir> [--out report.md]。",
              file=sys.stderr)
        return 1

    skill_dir = Path(a.skill_dir)
    if not skill_dir.is_dir():
        print(f"错误: 目录不存在: {skill_dir}。下一步: 核对路径后重试。", file=sys.stderr)
        return 1

    rows, stats = deliver_check(skill_dir)
    report = build_report(skill_dir, rows, stats)
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
