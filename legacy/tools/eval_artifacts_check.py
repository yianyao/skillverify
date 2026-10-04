#!/usr/bin/env python3
"""eval_artifacts_check.py — 评测期产物 schema/统计校验器（S 工具链，Q-1~Q-9）。

落实《验证补全工程·跨会话任务书》甲档工具二：测试期（eval 阶段）产物校验
9 项。检查项编号 Q-1~Q-9 为工具本地编号；方案条目映射（§6.2/§6.4/§7.3.3/
§7.4.5/§7.6.1/§7.6.2/§7.6.3/V12/V25）见任务书 §一甲档表。

定位（与既有工具分工）:
  - deliver_check.py EX-3 只查 grading.json 存在性；本工具查逐项 schema
    （不改冻结的 deliver_check，独立实现）。
  - check_skill.py A 门管编写期形态；本工具只管评测产物（.verification 下
    queryset/split/timing/grading/benchmark/runs/评审留痕）。
  - Q-6/Q-7 统计一律从产物文件重算，不吃手填 summary（任务书 §三.3）。
  - Q-6 恒过/恒挂/摇摆清单输出为机械判定，处置归人工；语义归乙档
    （LL-7 双评一致性复核归 W 组评审）。

版本: v1.1（2026-10-03 第 5 步独立自查轮）—
      ⑨Q-6 多 runs.json 合并统计（原只取 runs_files[0]，与 Q-7 遍历全部的
        口径分裂——多 runs.json 场景下恒态/摇摆统计静默不完整；任一文件
        解析失败仍 FAIL，全部可解析才合并重算）。
      v1.0.1（2026-10-03 首轮外部评审处置）—
      ①Q-2 补 train ⊆ 全量集对称校验（原仅查 validation，越集的 train 文件
        只要比例在带内即静默 PASS——§6.4.2"切分集 ⊆ 全量集"系对称约束）；
      ②Q-8 证据列取值改显式 or 链（原 dict.get 默认值仅键不存在时生效，
        长列名在场但值为空串时不会回退短列名，造成误报缺证据）；
      ③Q-4 递归 where 路径改拼接（原深层嵌套组仅保留最外层键，定位失准）；
      ④Q-5 delta 空 dict 不再判缺失（§7.6.1 只要求 delta 对照在场，结构
        在场即可；指标是否全零属统计语义非 schema）；
      ⑤Q-6 恒过/恒挂清单附样本数 ×n（单次运行不足以论断"恒"）；
      ⑥Q-9 标记判定简化为 exists()（原 endswith("-1") 分支冗余且易误伤）；
      ⑦报告判定统计注明口径（PASS/FAIL 分母 + WARN/SKIP/INFO 计数）；
      ⑧测试 34→49 组：补 Q-2 train 越集/交集非空/--split 个数/frozen 幽灵
        条目/Q-4 无断言数组与嵌套组 where/Q-6 摇摆与无标注/Q-7 多池独立/
        Q-8 证据过短与表头不识别/Q-9 文件形态标志物/--queryset 显式/
        --min-count 20 等回归。
      运行环境: Python ≥3.9（Path.is_relative_to）；家族兼容性基线 3.10+。

检查项（Q 系）:
  Q-1  查询集 schema        条数下限（--min-count，默认 12 个人版；全量 20 建议）、
                            正负例配比（12=6/6；20=各 8–10；其余各 40%–60%）、
                            should_trigger 布尔、id 唯一、必要字段齐全 → FAIL（§6.2）
  Q-2  切分校验             split 文件存在（--split 显式指定缺文件 → FAIL；内联
                            subset 无切分信息 → SKIP）、train/validation 比例
                            60/40±5pp、切分集 ⊆ 全量集、frozen.sha256 哈希冻结
                            一致（只读）→ FAIL（§6.4.1–6.4.2）
  Q-3  timing.json schema   total_tokens/duration_ms 数值、缺失即 FAIL；
                            产物不存在 → SKIP（§7.3.3）
  Q-4  grading.json 断言    每断言 text/passed(布尔)/evidence 齐全 + summary 与
                            断言重算一致（不吃手填）→ FAIL；产物不存在 → SKIP
                            （§7.2.6/§7.4.5）
  Q-5  benchmark.json       with_skill/without_skill 两组 pass_rate/time_seconds/
                            tokens 数值 + delta 数值型 → FAIL；产物不存在 → SKIP
                            （§7.6.1）
  Q-6  模式审查统计         恒过/恒挂/高摇摆（rate∈[0.4,0.6]）断言清单输出
                            → WARN（机械判定，处置归人工）（§7.6.2）
  Q-7  离群值               单次运行 token/耗时 > 3× 均值 → WARN；样本 <3 或无
                            数值 → SKIP（§7.6.3）
  Q-8  评审留痕完整性       record_review 产出记录行必备字段（日期/判定/证据/
                            双评标记）→ 缺失 WARN；语义一致性归 LL-7（V12）
  Q-9  迭代状态清理对账     .verification 工作区文件盘点与留痕声明对账
                            → INFO（信息供给，不判 FAIL）（V25）

用法:
    python eval_artifacts_check.py <artifacts-dir>                  # 校验 .verification 产物
    python eval_artifacts_check.py <artifacts-dir> --out report.md  # 同时落盘报告
    python eval_artifacts_check.py <dir> --queryset qs.json --split train.json,val.json
    python eval_artifacts_check.py <dir> --min-count 20             # 全量口径

退出码: 0=全 PASS/INFO；1=任一 FAIL；2=无 FAIL 但有 WARN。SKIP 不计警告
（产物缺失系预期形态，区别于 schema 错误 FAIL）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

VERSION = "v1.1"
MIN_COUNT_DEFAULT = 12          # Q-1 条数下限（个人版；全量 20 建议）
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NUMERIC_KEYS = ("total_tokens", "duration_ms")           # Q-3（§7.3.3）
RUN_METRIC_KEYS = ("total_tokens", "duration_ms",        # Q-7 离群统计指标
                   "time_seconds", "tokens")
# Q-9 盘点对象（.verification 工作区标志性文件/目录）
WS_MARKERS = (".iteration-baseline", "frozen.sha256", "llm-review-log.md",
              "trigger-eval", "iteration-1")

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}


class _BlockArgParser(argparse.ArgumentParser):
    """参数错误统一 exit 1（阻断码）——argparse 默认 exit 2 撞 WARN 码
    （家族纪律：全工具对齐）。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"错误: {message}。下一步: 按用法核对参数后重试。", file=sys.stderr)
        raise SystemExit(1)


def _ev(text: str) -> str:
    """证据净化：报告为 markdown 表格，竖线/换行会破坏行结构。"""
    return (str(text).replace("|", "｜").replace("\r\n", " ")
            .replace("\n", " ").replace("\r", " "))


def _is_num(x: object) -> bool:
    """数值判定（bool 是 int 子类，须显式排除——true/false 不是合法 token 数）。"""
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _load_json(path: Path) -> tuple[object, str]:
    """utf-8-sig 读 JSON。返回 (对象, "") 或 (None, 错误信息)。"""
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as e:
        return None, f"读取失败（{e.strerror or e}）"
    try:
        return json.loads(raw), ""
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败（第 {e.lineno} 行: {e.msg}）"


def rglob_files(root: Path, name: str) -> list[Path]:
    """递归收集指定文件名（is_symlink 前置，家族纪律）。"""
    out = [p for p in sorted(root.rglob(name))
           if p.is_file() and not p.is_symlink()
           and not any(part in SKIP_DIRS for part in p.relative_to(root).parts)]
    return out


# ------------------------------------------------------------- Q-1 ----

def parse_queryset(data: object) -> tuple[list[dict] | None, str]:
    """queryset 数据规整：兼容 {queries:[...]} 与裸数组两形态。"""
    if isinstance(data, dict):
        qs = data.get("queries")
        if isinstance(qs, list):
            return qs, ""
        return None, "顶层无 queries 数组"
    if isinstance(data, list):
        return data, ""
    return None, "顶层既非对象也非数组"


def check_q1(items: list[dict] | None, min_count: int) -> tuple[str, str]:
    """Q-1 查询集 schema（§6.2.1–6.2.7/6.2.10 机械部分）。"""
    if items is None:
        return "FAIL", "查询集结构不可解析（无 queries 数组/非 JSON 数组）"
    bad: list[str] = []
    n = len(items)
    if n < min_count:
        bad.append(f"条数 {n} < 下限 {min_count}（个人版 12/全量 20，--min-count 可配）")
    ids: list[str] = []
    no_bool: list[str] = []
    miss_field: list[str] = []
    pos = neg = 0
    for it in items:
        if not isinstance(it, dict):
            miss_field.append("（非对象条目）")
            continue
        qid = it.get("id")
        if qid is None or not str(qid).strip():
            miss_field.append("缺 id")
        else:
            ids.append(str(qid))
        if not isinstance(it.get("query"), str) or not it.get("query", "").strip():
            miss_field.append(f"{qid or '?'}: 缺 query")
        st = it.get("should_trigger")
        if not isinstance(st, bool):
            no_bool.append(f"{qid or '?'}: should_trigger={st!r} 非布尔")
        elif st:
            pos += 1
        else:
            neg += 1
        if "subset" not in it:
            miss_field.append(f"{qid or '?'}: 缺 subset")
    if len(ids) != len(set(ids)):
        dup = sorted({x for x in ids if ids.count(x) > 1})
        bad.append(f"id 重复: {', '.join(dup)}")
    if no_bool:
        bad.append(f"should_trigger 非布尔: {'; '.join(no_bool[:4])}"
                   + ("…" if len(no_bool) > 4 else ""))
    if miss_field:
        bad.append(f"必要字段缺失: {'; '.join(miss_field[:4])}"
                   + ("…" if len(miss_field) > 4 else ""))
    if n and pos + neg == n:
        if n == 12 and not (pos == 6 and neg == 6):
            bad.append(f"配比 {pos}/{neg} ≠ 6/6（12 条口径 §6.2.1）")
        elif n == 20 and not (8 <= pos <= 10 and 8 <= neg <= 10):
            bad.append(f"配比 {pos}/{neg} 越出 8–10/8–10（20 条口径 §6.2.1）")
        elif n not in (12, 20) and not (0.4 <= pos / n <= 0.6):
            bad.append(f"配比 {pos}/{neg} 越出 40%–60% 带")
    level = "FAIL" if bad else "PASS"
    ev = "; ".join(bad) if bad else (
        f"{n} 条（正 {pos}/负 {neg}），id 唯一、should_trigger 全布尔、必要字段齐全"
        + ("（达全量 20 建议线）" if n >= 20 else f"（达个人版下限 {min_count}）"))
    return level, ev


# ------------------------------------------------------------- Q-2 ----

def check_q2(qs_path: Path | None, items: list[dict] | None,
             split_arg: str, q1_skip: bool) -> tuple[str, str]:
    """Q-2 切分校验（§6.4.1–6.4.2）。只读冻结文件。"""
    if q1_skip or qs_path is None or items is None:
        return "SKIP", "查询集缺失，切分不可验"
    all_ids = {str(it.get("id")) for it in items if isinstance(it, dict) and it.get("id")}
    bad: list[str] = []
    if split_arg:
        parts = [s.strip() for s in split_arg.split(",") if s.strip()]
        if len(parts) != 2:
            return "FAIL", f"--split 须为 train,val 两个文件，实得 {len(parts)} 个"
        split_ids: dict[str, set[str]] = {}
        for label, sp in zip(("train", "validation"), parts):
            fp = Path(sp)
            if not fp.is_file():
                bad.append(f"{label} 切分文件不存在: {sp}")
                continue
            data, err = _load_json(fp)
            if err:
                bad.append(f"{label} 切分文件: {err}")
                continue
            sub_items, perr = parse_queryset(data)
            if perr:
                bad.append(f"{label} 切分文件: {perr}")
                continue
            split_ids[label] = {str(x.get("id")) for x in sub_items
                                if isinstance(x, dict) and x.get("id")}
    else:
        sub_map: dict[str, list[str]] = {}
        for it in items:
            if isinstance(it, dict) and it.get("id") is not None:
                sub_map.setdefault(str(it.get("subset")), []).append(str(it.get("id")))
        if set(sub_map) <= {None, ""} or not any(k in ("train", "validation")
                                                 for k in sub_map):
            return "SKIP", "查询集无 train/validation 切分信息（可 --split 显式指定后复检）"
        split_ids = {k: set(v) for k, v in sub_map.items() if k in ("train", "validation")}

    tr, va = split_ids.get("train", set()), split_ids.get("validation", set())
    tot = len(tr) + len(va)
    if tot:
        share = len(tr) / tot
        if not (0.55 <= share <= 0.65):
            bad.append(f"train 占比 {share:.0%} 越出 60/40±5pp（§6.4.1；train {len(tr)}/validation {len(va)}）")
    # v1.0.1 评审 Bug 1：切分集 ⊆ 全量系对称约束——原仅查 validation，
    # 越集的 train 文件只要比例在带内即静默 PASS
    for label, s in (("train", tr), ("validation", va)):
        outside = sorted(s - all_ids)
        if outside:
            bad.append(f"{label} 含全量集外 id: {', '.join(outside[:4])}"
                       + ("…" if len(outside) > 4 else ""))
    if tr & va:
        bad.append(f"train/validation 交集非空: {', '.join(sorted(tr & va)[:4])}")

    frozen_note = ""
    frozen = qs_path.parent / "frozen.sha256"
    if frozen.is_file():
        try:
            for ln in frozen.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                toks = ln.split()
                if len(toks) < 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", toks[0]):
                    continue
                ref = qs_path.parent / toks[-1]
                if not ref.is_file():
                    frozen_note += f"；冻结清单含不存在的文件: {toks[-1]}"
                    continue
                import hashlib
                actual = hashlib.sha256(ref.read_bytes()).hexdigest()
                if actual.lower() != toks[0].lower():
                    bad.append(f"哈希冻结不一致: {toks[-1]}（记录 {toks[0][:12]}…实测 {actual[:12]}…）"
                               "——冻结文件禁改，若系有意重建须走变更留痕")
        except OSError as e:
            frozen_note += f"；frozen.sha256 读取失败: {e}"
    else:
        frozen_note = "；无 frozen.sha256 冻结记录（首轮构造期属预期）"

    level = "FAIL" if bad else "PASS"
    ev = ("; ".join(bad) if bad else
          f"train {len(tr)}/validation {len(va)}"
          + (f"（train {len(tr) / tot:.0%}）" if tot else "")
          + "，⊆ 全量且无交集" + frozen_note)
    return level, ev


# ------------------------------------------------------------- Q-3 ----

def check_q3(root: Path) -> tuple[str, str, list[Path]]:
    """Q-3 timing.json schema（§7.3.3）。产物缺失 → SKIP。"""
    files = rglob_files(root, "timing.json")
    if not files:
        return "SKIP", "无 timing.json（评测期未产出，属预期形态）", []
    bad: list[str] = []
    for fp in files:
        data, err = _load_json(fp)
        if err:
            bad.append(f"{fp.relative_to(root)}: {err}")
            continue
        units = data if isinstance(data, list) else [data]
        for i, unit in enumerate(units):
            tag = f"{fp.relative_to(root)}" + (f"[{i}]" if isinstance(data, list) else "")
            if not isinstance(unit, dict):
                bad.append(f"{tag}: 条目非对象")
                continue
            missing = [k for k in NUMERIC_KEYS if k not in unit]
            nonnum = [k for k in NUMERIC_KEYS
                      if k in unit and not _is_num(unit[k])]
            if missing:
                bad.append(f"{tag}: 缺 {', '.join(missing)}")
            if nonnum:
                bad.append(f"{tag}: 非数值 {', '.join(nonnum)}")
    level = "FAIL" if bad else "PASS"
    ev = "; ".join(bad) if bad else f"{len(files)} 个 timing.json 字段齐且为数值"
    return level, ev, files


# ------------------------------------------------------------- Q-4 ----

def _iter_assertion_groups(node: object) -> list[tuple[dict, list, str]]:
    """收集树中所有 {assertions: [...], summary?: {...}} 组（tag 标位置）。"""
    out: list[tuple[dict, list, str]] = []
    if isinstance(node, dict):
        if isinstance(node.get("assertions"), list):
            out.append((node, node["assertions"], ""))
        for k, v in node.items():
            if k == "assertions":
                continue
            # v1.0.1 评审 2.1：where 须拼接路径（原仅保留最外层键，深层嵌套定位失准）
            for grp, arr, child in _iter_assertion_groups(v):
                out.append((grp, arr, f"{k}/{child}" if child else k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            for grp, arr, _ in _iter_assertion_groups(v):
                out.append((grp, arr, f"[{i}]"))
    return out


def check_q4(root: Path) -> tuple[str, str]:
    """Q-4 grading.json 断言数组 schema + summary 重算对账（§7.2.6/§7.4.5）。"""
    files = rglob_files(root, "grading.json")
    if not files:
        return "SKIP", "无 grading.json（评测期未产出，属预期形态）"
    bad: list[str] = []
    for fp in files:
        rel = fp.relative_to(root)
        data, err = _load_json(fp)
        if err:
            bad.append(f"{rel}: {err}")
            continue
        groups = _iter_assertion_groups(data)
        if not groups:
            bad.append(f"{rel}: 无 assertions 数组（§7.4.5：断言须在 assertions 数组内）")
        for grp, arr, where in groups:
            tag = f"{rel}" + (f"/{where}" if where else "")
            passed_n = failed_n = 0
            for i, a in enumerate(arr):
                alabel = f"{tag}#{i}"
                if not isinstance(a, dict):
                    bad.append(f"{alabel}: 断言非对象")
                    continue
                if not isinstance(a.get("text"), str) or not a["text"].strip():
                    bad.append(f"{alabel}: 缺 text")
                if not isinstance(a.get("passed"), bool):
                    bad.append(f"{alabel}: passed 非布尔")
                elif a["passed"]:
                    passed_n += 1
                else:
                    failed_n += 1
                if not isinstance(a.get("evidence"), str) or not a["evidence"].strip():
                    bad.append(f"{alabel}: 缺 evidence（§7.5.1 PASS 须附证据）")
            summ = grp.get("summary")
            if isinstance(summ, dict):
                total = passed_n + failed_n
                rate = (passed_n / total) if total else 0.0
                recal = {"passed": passed_n, "failed": failed_n,
                         "total": total, "pass_rate": rate}
                mism = []
                for k, v in recal.items():
                    got = summ.get(k)
                    if not _is_num(got) or abs(float(got) - float(v)) > 1e-9:
                        mism.append(f"{k}: 手填 {got!r} ≠ 重算 {v!r}")
                if mism:
                    bad.append(f"{tag}/summary 与断言重算不一致: {'; '.join(mism)}"
                               "（任务书 §三.3：只从产物重算，不吃手填 summary）")
    level = "FAIL" if bad else "PASS"
    ev = "; ".join(bad) if bad else \
        f"{len(files)} 个 grading.json 断言 schema 完整且 summary 对账一致"
    return level, ev


# ------------------------------------------------------------- Q-5 ----

def check_q5(root: Path) -> tuple[str, str]:
    """Q-5 benchmark.json schema（§7.6.1：两组指标 + delta）。"""
    files = rglob_files(root, "benchmark.json")
    if not files:
        return "SKIP", "无 benchmark.json（评测期未产出，属预期形态）"
    bad: list[str] = []
    need = ("pass_rate", "time_seconds", "tokens")
    for fp in files:
        rel = fp.relative_to(root)
        data, err = _load_json(fp)
        if err:
            bad.append(f"{rel}: {err}")
            continue
        if not isinstance(data, dict):
            bad.append(f"{rel}: 顶层非对象")
            continue
        for side in ("with_skill", "without_skill"):
            grp = data.get(side)
            if not isinstance(grp, dict):
                bad.append(f"{rel}: 缺 {side} 组（§7.6.1 须两组对照）")
                continue
            miss = [k for k in need if k not in grp]
            nonnum = [k for k in need if k in grp and not _is_num(grp[k])]
            if miss:
                bad.append(f"{rel}/{side}: 缺 {', '.join(miss)}")
            if nonnum:
                bad.append(f"{rel}/{side}: 非数值 {', '.join(nonnum)}")
        # v1.0.1 评审 2.2：§7.6.1 只要求 delta 对照在场——空 dict 结构在场
        # 即可（指标全零被裁剪为空系统计语义，不属 schema 缺失）
        delta = data.get("delta")
        if not isinstance(delta, dict):
            bad.append(f"{rel}: 缺 delta 对照（§7.6.1 须含 delta）")
        else:
            nonnum = [k for k, v in delta.items() if not _is_num(v)]
            if nonnum:
                bad.append(f"{rel}/delta 非数值: {', '.join(nonnum)}")
    level = "FAIL" if bad else "PASS"
    ev = "; ".join(bad) if bad else f"{len(files)} 个 benchmark.json 两组指标 + delta 齐且为数值"
    return level, ev


# ------------------------------------------------------------- Q-6 ----

def check_q6(root: Path, items: list[dict] | None) -> tuple[str, str]:
    """Q-6 模式审查统计（§7.6.2 机械部分）：恒过/恒挂/高摇摆清单 → WARN。"""
    runs_files = rglob_files(root, "runs.json")
    if not runs_files:
        return "SKIP", "无 runs.json（触发实测未产出，属预期形态）"
    # v1.1 自查⑨：合并全部 runs.json（原只取首个，与 Q-7 遍历全部口径分裂，
    # 多 runs.json 场景下统计静默不完整）；任一文件解析失败仍 FAIL
    merged: list[dict] = []
    errs: list[str] = []
    for fp in runs_files:
        rel = str(fp.relative_to(root))
        data, err = _load_json(fp)
        if err:
            errs.append(f"{rel}: {err}")
            continue
        runs = data.get("runs") if isinstance(data, dict) else data
        if not isinstance(runs, list):
            errs.append(f"{rel}: 无 runs 数组")
            continue
        merged.extend(runs)
    if errs:
        return "FAIL", "; ".join(errs)
    bad: list[str] = []
    runs = merged
    by_id: dict[str, list[bool]] = {}
    unjudged: list[str] = []
    for r in runs:
        if not isinstance(r, dict) or r.get("query_id") is None:
            continue
        qid = str(r["query_id"])
        lv = r.get("loaded")
        if not isinstance(lv, bool):
            unjudged.append(qid)
            continue
        by_id.setdefault(qid, []).append(lv)
    expect = {str(it.get("id")): it.get("should_trigger") for it in (items or [])
              if isinstance(it, dict) and it.get("id") is not None}
    # v1.0.1 评审 2.3：清单项附样本数 ×n——单次运行不足以论断"恒"
    always_on: list[tuple[str, str]] = []    # (qid, 展示 tag) 恒过（全 true）
    always_off: list[tuple[str, str]] = []   # 恒挂（全 false）
    swing: list[str] = []        # 高摇摆 rate∈[0.4,0.6]
    for qid, lvs in sorted(by_id.items()):
        rate = sum(lvs) / len(lvs)
        n = len(lvs)
        if rate == 1.0:
            always_on.append((qid, f"{qid}(×{n})"))
        elif rate == 0.0:
            always_off.append((qid, f"{qid}(×{n})"))
        elif 0.4 <= rate <= 0.6:
            swing.append(f"{qid}(×{n}，{sum(lvs)}/{n})")
    # 有查询集标注时按标注归因：正例恒挂/负例恒过才是问题形态
    if expect:
        real_always_on = [t for q, t in always_on if expect.get(q) is False]
        real_always_off = [t for q, t in always_off if expect.get(q) is True]
        label_on = "恒过（负例全触发=误触发）"
        label_off = "恒挂（正例全不触发）"
    else:
        real_always_on = [t for _, t in always_on]
        real_always_off = [t for _, t in always_off]
        label_on = "恒过"
        label_off = "恒挂"
    if real_always_on:
        bad.append(f"{label_on}: {', '.join(real_always_on[:8])}"
                   + ("…" if len(real_always_on) > 8 else ""))
    if real_always_off:
        bad.append(f"{label_off}: {', '.join(real_always_off[:8])}"
                   + ("…" if len(real_always_off) > 8 else ""))
    if swing:
        bad.append(f"高摇摆（方差超阈）: {', '.join(swing[:8])}"
                   + ("…" if len(swing) > 8 else ""))
    if unjudged:
        bad.append(f"loaded 非布尔不可判: {', '.join(sorted(set(unjudged))[:4])}")
    ev = "; ".join(bad) if bad else (
        f"{len(by_id)} 条查询 × 各 {('、'.join(str(x) for x in sorted({len(v) for v in by_id.values()})))} 次："
        "无恒过/恒挂/高摇摆问题形态"
        + ("（按查询集标注归因）" if expect else "（无查询集标注，恒态仅清单呈现）"))
    level = "WARN" if bad else "PASS"
    if bad:
        ev += "（§7.6.2 机械判定，处置归人工；归因复核可交 LL-7）"
    return level, ev


# ------------------------------------------------------------- Q-7 ----

def check_q7(root: Path) -> tuple[str, str]:
    """Q-7 离群值（§7.6.3）：单次运行指标 > 3× 均值 → WARN。只重算不吃自述。

    按来源文件分池：runs.json 逐次记录与 timing.json 单次聚合值单位不同，
    混池会把聚合值误判为离群（首轮单测夹具实测）；池内样本 <3 不判。"""
    pools: dict[tuple[str, str], list[tuple[str, float]]] = {}
    for fp in rglob_files(root, "runs.json") + rglob_files(root, "timing.json"):
        data, err = _load_json(fp)
        if err:
            continue  # schema 问题归 Q-3/Q-6 管辖
        units = data if isinstance(data, list) else (
            data.get("runs") if isinstance(data, dict) and isinstance(data.get("runs"), list)
            else [data] if isinstance(data, dict) else [])
        rel = str(fp.relative_to(root))
        for i, u in enumerate(units):
            if not isinstance(u, dict):
                continue
            tag = f"{rel}[{i}]" if isinstance(data, list) else rel
            for k in RUN_METRIC_KEYS:
                if _is_num(u.get(k)):
                    pools.setdefault((rel, k), []).append((tag, float(u[k])))
    bad: list[str] = []
    checked: list[str] = []
    for (rel, k), arr in sorted(pools.items()):
        if len(arr) < 3:
            continue  # 样本不足不判（均值无意义）
        mean = sum(v for _, v in arr) / len(arr)
        if mean <= 0:
            continue
        outs = [(tag, v) for tag, v in arr if v > 3 * mean]
        checked.append(f"{rel}:{k}×{len(arr)}")
        for tag, v in outs:
            bad.append(f"{tag}: {k}={v:g} > 3×均值（{mean:g}）")
    if not checked:
        return "SKIP", f"无 ≥3 样本的运行指标池（可得: {', '.join(sorted({k for _, k in pools})) or '无'}），离群不可判"
    level = "WARN" if bad else "PASS"
    ev = ("; ".join(bad) + "（§7.6.3：轨迹诊断交 LLM）" if bad
          else f"离群检测覆盖 {', '.join(checked)}，无 >3× 均值项")
    return level, ev


# ------------------------------------------------------------- Q-8 ----

def check_q8(root: Path) -> tuple[str, str]:
    """Q-8 评审留痕记录完整性（V12 机械部分）：record_review 产出的记录行
    必备字段（日期/判定/证据/双评标记）——字段缺失 WARN，语义归 LL-7。"""
    log_files = [p for p in rglob_files(root, "*.md")
                 if re.search(r"(?:log|record)", p.name, re.I)]
    if not log_files:
        return "INFO", "无评审留痕 log/record 类文件（未跑 LLM 评审期，属预期形态）"
    bad: list[str] = []
    n_rows = 0
    for fp in log_files:
        rel = fp.relative_to(root)
        try:
            text = fp.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as e:
            bad.append(f"{rel}: 读取失败 {e}")
            continue
        lines = text.split("\n")
        header_idx = [i for i, ln in enumerate(lines)
                      if ln.startswith("|") and "日期" in ln and "判定" in ln]
        if not header_idx:
            continue
        for hi in header_idx:
            cols = [c.strip() for c in lines[hi].strip("|").split("|")]
            for ln in lines[hi + 2:]:  # 跳过分隔行 |---|
                if not ln.startswith("|"):
                    break
                cells = [c.strip() for c in ln.strip("|").split("|")]
                if not any(cells):
                    break
                n_rows += 1
                row = dict(zip(cols, cells))
                rid = row.get("提示词编号") or row.get("编号") or f"行{n_rows}"
                if not DATE_RE.match(row.get("日期", "")):
                    bad.append(f"{rel}:{rid}: 日期缺失/非 YYYY-MM-DD")
                if not row.get("判定", "").strip():
                    bad.append(f"{rel}:{rid}: 判定缺失")
                # v1.0.1 评审 Bug 2：dict.get 默认值仅键不存在时生效——长列名
                # 在场但空串时须显式回退短列名（or 链），否则误报缺证据
                evid = (row.get("输出证据（结论摘要/引用）")
                        or row.get("输出证据") or "")
                if len(evid.strip()) < 8:
                    bad.append(f"{rel}:{rid}: 证据缺失/过短（V12 须引用结论）")
                dual = row.get("是否双评", "").strip()
                if dual and dual not in ("是", "否"):
                    bad.append(f"{rel}:{rid}: 双评标记非 是/否（{dual}）")
                elif not dual:
                    bad.append(f"{rel}:{rid}: 双评 A/B 标记缺失")
    if not n_rows and not bad:
        return "INFO", f"{len(log_files)} 个留痕文件均无 V12 记录表（日期+判定列表头）"
    level = "WARN" if bad else "PASS"
    ev = ("; ".join(bad[:6]) + ("…" if len(bad) > 6 else "")
          + f"（{n_rows} 行记录，字段缺失 {len(bad)} 处；语义一致性归 LL-7）"
          if bad else f"{n_rows} 行记录必备字段齐全（日期/判定/证据/双评标记）")
    return level, ev


# ------------------------------------------------------------- Q-9 ----

def check_q9(root: Path) -> tuple[str, str]:
    """Q-9 迭代状态清理对账（V25）：.verification 工作区盘点——INFO 供给。"""
    found: list[str] = []
    missing: list[str] = []
    for marker in WS_MARKERS:
        # v1.0.1 评审 2.4：单分支 exists()——原 endswith("-1") 分支冗余且增补
        # 其他 -1 结尾标记时会误伤
        (found if (root / marker).exists() else missing).append(marker)
    iter_dirs = sorted({p.parent.name for p in rglob_files(root, "record-baseline.md")})
    bl = root / ".iteration-baseline"
    recon = ""
    if bl.is_file() and iter_dirs:
        recon = f"；基线在场且迭代快照目录 {', '.join(iter_dirs)} 在场"
    elif bl.is_file():
        recon = "；基线在场但未发现含 record-baseline.md 的迭代快照目录"
    elif iter_dirs:
        recon = f"；有迭代快照目录 {', '.join(iter_dirs)} 但根无 .iteration-baseline"
    else:
        recon = "；无基线与迭代快照（首轮编写期属预期）"
    ev = (f"工作区标志物: 在场 {found or '无'} / 缺 {missing or '无'}{recon}"
          "——V25 对账信息供给，不判 FAIL")
    return "INFO", ev


# ----------------------------------------------------------------- main ----

def main() -> int:
    ap = _BlockArgParser(description="评测期产物 schema/统计校验器（Q-1~Q-9，任务书甲档工具二）")
    ap.add_argument("artifacts_dir", help="评测产物目录（通常为技能 .verification/）")
    ap.add_argument("--out", help="报告落盘路径（建议 .verification/eval-artifacts-check.md）")
    ap.add_argument("--queryset", help="查询集路径（缺省 <dir>/trigger-eval/queryset.json）")
    ap.add_argument("--split", help="切分文件对 train,val（缺省用查询集内联 subset 字段）")
    ap.add_argument("--min-count", type=int, default=MIN_COUNT_DEFAULT,
                    help=f"Q-1 条数下限（默认 {MIN_COUNT_DEFAULT} 个人版；全量传 20）")
    a = ap.parse_args()

    if a.out is not None and not a.out.strip():
        print("错误: --out 不接受空串。下一步: 去掉 --out 或给出有效落盘路径。",
              file=sys.stderr)
        return 1

    root = Path(a.artifacts_dir)
    if not root.is_dir():
        print(f"错误: 目录不存在: {root}。下一步: 核对 --artifacts-dir 是否指向"
              " .verification 产物目录。", file=sys.stderr)
        return 1

    # ---- 查询集载入（Q-1/Q-2/Q-6 共用；缺失→SKIP 不计警告）----
    qs_path = Path(a.queryset) if a.queryset else root / "trigger-eval" / "queryset.json"
    q1_level, q1_ev = "SKIP", f"查询集缺失: {qs_path.relative_to(root) if qs_path.is_relative_to(root) else qs_path}（未产出，属预期形态）"
    q2_level, q2_ev = "SKIP", "查询集缺失，切分不可验"
    items = None
    if qs_path.is_file():
        data, err = _load_json(qs_path)
        if err:
            q1_level, q1_ev = "FAIL", f"{err}"
        else:
            items, perr = parse_queryset(data)
            if perr:
                q1_level, q1_ev = "FAIL", perr
                items = None
            else:
                q1_level, q1_ev = check_q1(items, a.min_count)
        q2_level, q2_ev = check_q2(qs_path, items, a.split or "", q1_level == "SKIP")

    q3_level, q3_ev, _ = check_q3(root)
    q4_level, q4_ev = check_q4(root)
    q5_level, q5_ev = check_q5(root)
    q6_level, q6_ev = check_q6(root, items)
    q7_level, q7_ev = check_q7(root)
    q8_level, q8_ev = check_q8(root)
    q9_level, q9_ev = check_q9(root)

    rows = [
        dict(lid="Q-1", title="查询集 schema（条数/配比/布尔/唯一/字段）", level=q1_level, ev=q1_ev),
        dict(lid="Q-2", title="切分校验（比例/⊆ 全量/哈希冻结）", level=q2_level, ev=q2_ev),
        dict(lid="Q-3", title="timing.json schema（total_tokens/duration_ms）", level=q3_level, ev=q3_ev),
        dict(lid="Q-4", title="grading.json 断言 schema + summary 对账", level=q4_level, ev=q4_ev),
        dict(lid="Q-5", title="benchmark.json 两组指标 + delta", level=q5_level, ev=q5_ev),
        dict(lid="Q-6", title="模式审查统计（恒过/恒挂/摇摆清单）", level=q6_level, ev=q6_ev),
        dict(lid="Q-7", title="离群值（>3× 均值）", level=q7_level, ev=q7_ev),
        dict(lid="Q-8", title="评审留痕记录完整性（V12）", level=q8_level, ev=q8_ev),
        dict(lid="Q-9", title="迭代状态清理对账（V25）", level=q9_level, ev=q9_ev),
    ]
    for r in rows:
        r["ev"] = _ev(r["ev"])

    has_fail = any(r["level"] == "FAIL" for r in rows)
    has_warn = any(r["level"] == "WARN" for r in rows)
    has_skip = any(r["level"] == "SKIP" for r in rows)
    judged = [r for r in rows if r["level"] in ("PASS", "FAIL")]
    # v1.0.1 评审 2.5：注明判定统计口径——分母只含 PASS/FAIL，其余级别单独计数
    n_warn = sum(1 for r in rows if r["level"] == "WARN")
    n_skip = sum(1 for r in rows if r["level"] == "SKIP")
    n_info = sum(1 for r in rows if r["level"] == "INFO")

    suffix_notes: list[str] = []
    if has_warn:
        suffix_notes.append("WARN（需书面评估）")
    if has_skip:
        suffix_notes.append("SKIP（产物缺失，仅记录）")
    suffix = f"；附 {' + '.join(suffix_notes)}" if suffix_notes else ""
    lines = [
        "# 评测期产物校验报告（eval_artifacts_check.py " + VERSION + "）",
        "",
        f"- 产物目录: {root}",
        f"- 口径: 任务书甲档工具二 Q-1~Q-9；条数下限 {a.min_count}"
        f"（--min-count）；查询集 {'显式指定' if a.queryset else '缺省 trigger-eval/queryset.json'}",
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
        + ("；Q-6/Q-7 为机械清单输出（处置归人工），产物缺失 SKIP 不计警告。" if not has_fail
           else "；Q 系 FAIL 阻断，当轮修复后复跑。"),
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
