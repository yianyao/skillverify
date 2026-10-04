#!/usr/bin/env python3
"""test_deliver_check.py — deliver_check.py 固化回归单测（S1⑥ 存在性/schema 门七项）。

以临时夹具固化建成实测结论：合规全 PASS（EX-1~7 + COV）、裸夹具三态
（EX-1 WARN 验收报告 M1 时点/EX-2-3 SKIP 未产出/EX-4 SKIP 未声明/EX-5-7 WARN
关键词初筛未见）、EX-1 交付物缺失 FAIL、feedback.json 双口径（B 键值文本/A
text-passed-evidence）+ 空对象 WARN + 结构不匹配 FAIL、grading.json schema
（缺 passed 字段 FAIL/summary 键不符 FAIL/无 summary WARN/evidence 缺 WARN）、
license 三态（短字段+LICENSE 文件 PASS/长字段内嵌 WARN/声明无随包 WARN）、
B1 留档关键词命中 PASS、退出码 0/1/2 + 参数错误统一 1 + --out 落盘；
评审 v1.0.1 回归：BOM 夹具 frontmatter 可解析、B 口径无分隔键 WARN、
summary 字符串数值 WARN、references/ 示例口径降 WARN 不 FAIL、重复 license 键 WARN。
任何 deliver_check.py 改动后必须先过本文件。
只读 + 临时目录夹具，无系统副作用。

用法: python tests/test_deliver_check.py    # 全过打印 ALL PASS，失败非零退出
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
passed: list[str] = []


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dc = load("deliver_check_under_test", TOOLS / "deliver_check.py")


def ok(msg: str) -> None:
    passed.append(msg)
    print(f"  PASS {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")
    sys.exit(1)


def levels(rows: list[dict]) -> dict[str, str]:
    return {r["vid"]: r["level"] for r in rows}


def row(rows: list[dict], vid: str) -> dict:
    return next(r for r in rows if r["vid"] == vid)


def run_exit(*args: str) -> int:
    return subprocess.run(
        [sys.executable, str(TOOLS / "deliver_check.py"), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30, stdin=subprocess.DEVNULL).returncode


def make_skill(root: Path, name: str) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: " + name + "\ndescription: 存在性门夹具技能描述\n---\n# t\n",
        encoding="utf-8", newline="\n")
    return d


GRADING_OK = {
    "summary": {"passed": 1, "failed": 0, "total": 1, "pass_rate": 1.0},
    "cases": [{"text": "输出含图表", "passed": True, "evidence": "L12 见 fig"}],
}
FEEDBACK_B = {"eval-1/case-1": "图缺轴标签，补轴后复核", "eval-1/case-2": ""}


def build_full_skill(d: Path) -> None:
    """合规夹具：全交付物 + license + 双 json + B1 留痕。"""
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: full-skill\ndescription: 存在性门夹具技能描述\n"
        "license: MIT\n---\n# t\n", encoding="utf-8", newline="\n")
    (d / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    (d / "evals").mkdir()
    (d / "evals" / "evals.json").write_text('{"cases": []}', encoding="utf-8")
    ver = d / ".verification"
    (ver / "iteration-1").mkdir(parents=True)
    (ver / "iteration-1" / "log.md").write_text(
        "# 迭代 1\n反向测试: 规则 R1 删掉后 agent 漏检查项——保留。\n"
        "轨迹分析: 无效步骤归因=指令太含糊。\n", encoding="utf-8")
    (ver / "acceptance-report.md").write_text(
        "# 验收报告: full-skill v1.0\n结论: 通过\n", encoding="utf-8")
    (ver / "feedback.json").write_text(
        json.dumps(FEEDBACK_B, ensure_ascii=False, indent=1), encoding="utf-8")
    (ver / "grading.json").write_text(
        json.dumps(GRADING_OK, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="deliv-test-"))
    try:
        # 0. 合规夹具：EX-1~7 全 PASS → exit 0
        sk = tmp / "full-skill"
        build_full_skill(sk)
        rows, _ = dc.deliver_check(sk)
        lv = levels(rows)
        for vid in ("EX-1", "EX-2", "EX-3", "EX-4", "EX-5", "EX-6", "EX-7"):
            if lv[vid] != "PASS":
                fail(f"合规夹具 {vid} 应 PASS: {lv[vid]}（{row(rows, vid)['ev'][:80]}）")
        ok("合规夹具：EX-1~7 全 PASS（交付物齐+双 json 合规+license+iteration+关键词留痕）")

        # 1. 裸夹具（SKILL.md+evals.json）：EX-1 WARN / 2,3,4 SKIP / 5,6,7 WARN → exit 2
        bare = make_skill(tmp, "bare-skill")
        (bare / "evals").mkdir()
        (bare / "evals" / "evals.json").write_text('{"cases": []}', encoding="utf-8")
        rows, _ = dc.deliver_check(bare)
        lv = levels(rows)
        if lv["EX-1"] != "WARN" or "acceptance-report" not in row(rows, "EX-1")["ev"]:
            fail(f"裸夹具 EX-1 应 WARN（M1 时点项）: {lv['EX-1']} {row(rows, 'EX-1')['ev'][:80]}")
        if lv["EX-2"] != "SKIP" or lv["EX-3"] != "SKIP" or lv["EX-4"] != "SKIP":
            fail(f"裸夹具 EX-2/3/4 应 SKIP: {lv['EX-2']}/{lv['EX-3']}/{lv['EX-4']}")
        if lv["EX-5"] != "SKIP" or lv["EX-6"] != "SKIP" or lv["EX-7"] != "SKIP":
            fail(f"裸夹具（无 .verification/）EX-5/6/7 应 SKIP: {lv['EX-5']}/{lv['EX-6']}/{lv['EX-7']}")
        ok("裸夹具：EX-1 WARN（验收报告 M1 时点）+ EX-2/3/4 SKIP + EX-5/6/7 SKIP（留痕域未建）")

        # 1b. .verification/ 在场但无 iteration/无关键词 → EX-5/6/7 WARN
        vempty = make_skill(tmp, "vempty-skill")
        (vempty / "evals").mkdir()
        (vempty / "evals" / "evals.json").write_text('{"cases": []}', encoding="utf-8")
        (vempty / ".verification").mkdir()
        (vempty / ".verification" / "note.md").write_text(
            "# 备忘\n与留痕关键词无关的内容。\n", encoding="utf-8")
        rows, _ = dc.deliver_check(vempty)
        lv = levels(rows)
        if lv["EX-5"] != "WARN" or lv["EX-6"] != "WARN" or lv["EX-7"] != "WARN":
            fail(f"留痕域在场无内容 EX-5/6/7 应 WARN: {lv['EX-5']}/{lv['EX-6']}/{lv['EX-7']}")
        ok("EX-5/6/7：留痕域在场但无关键词/无 iteration → WARN（人工确认留档位置）")

        # 2. EX-1 FAIL：evals.json 缺失（编写期产物 [M]）——仅 SKILL.md
        noev = make_skill(tmp, "no-evals")
        rows, _ = dc.deliver_check(noev)
        r1 = row(rows, "EX-1")
        if r1["level"] != "FAIL" or "evals" not in r1["ev"]:
            fail(f"缺 evals.json 应 FAIL: {r1['level']} {r1['ev'][:80]}")
        ok("EX-1：evals/evals.json 缺失 → FAIL（[M] 编写期产物）；验收报告缺失仅 WARN")

        # 3. feedback.json 三态：口径 A PASS / 空对象 WARN / 结构不匹配 FAIL
        fa = make_skill(tmp, "fb-a")
        (fa / ".verification").mkdir()
        (fa / ".verification" / "feedback.json").write_text(
            json.dumps([{"text": "x", "passed": False, "evidence": "y"}]),
            encoding="utf-8")
        rows, _ = dc.deliver_check(fa)
        r2 = row(rows, "EX-2")
        if r2["level"] != "PASS" or "口径 A" not in r2["ev"]:
            fail(f"口径 A 应 PASS: {r2['level']} {r2['ev'][:80]}")
        fe = make_skill(tmp, "fb-empty")
        (fe / ".verification").mkdir()
        (fe / ".verification" / "feedback.json").write_text("{}", encoding="utf-8")
        rows, _ = dc.deliver_check(fe)
        if row(rows, "EX-2")["level"] != "WARN":
            fail(f"空对象应 WARN: {row(rows, 'EX-2')['ev'][:80]}")
        fb = make_skill(tmp, "fb-bad")
        (fb / ".verification").mkdir()
        (fb / ".verification" / "feedback.json").write_text(
            '{"foo": 123}', encoding="utf-8")
        rows, _ = dc.deliver_check(fb)
        r2 = row(rows, "EX-2")
        if r2["level"] != "FAIL" or "双文档口径" not in r2["ev"]:
            fail(f"结构不匹配应 FAIL: {r2['level']} {r2['ev'][:80]}")
        ok("EX-2：口径 A/B 同认 PASS；空对象 WARN（逐用例留键）；不匹配 FAIL（[M]）")

        # 4. grading.json schema：缺 passed FAIL / summary 键不符 FAIL / 无 summary WARN
        gb = make_skill(tmp, "gr-bad")
        (gb / ".verification").mkdir()
        (gb / ".verification" / "grading.json").write_text(
            json.dumps({"cases": [{"text": "x", "result": True, "evidence": "y"}]}),
            encoding="utf-8")
        rows, _ = dc.deliver_check(gb)
        r3 = row(rows, "EX-3")
        if r3["level"] != "FAIL" or "passed" not in r3["ev"]:
            fail(f"缺 passed 应 FAIL: {r3['level']} {r3['ev'][:80]}")
        gs = make_skill(tmp, "gr-summary")
        (gs / ".verification").mkdir()
        (gs / ".verification" / "grading.json").write_text(
            json.dumps({"summary": {"pass": 1},
                        "cases": [{"text": "x", "passed": True, "evidence": "y"}]}),
            encoding="utf-8")
        rows, _ = dc.deliver_check(gs)
        if row(rows, "EX-3")["level"] != "FAIL":
            fail(f"summary 键不符应 FAIL: {row(rows, 'EX-3')['ev'][:80]}")
        gn = make_skill(tmp, "gr-nosum")
        (gn / ".verification").mkdir()
        (gn / ".verification" / "grading.json").write_text(
            json.dumps({"cases": [{"text": "x", "passed": True, "evidence": "y"}]}),
            encoding="utf-8")
        rows, _ = dc.deliver_check(gn)
        r3 = row(rows, "EX-3")
        if r3["level"] != "WARN" or "summary" not in r3["ev"]:
            fail(f"无 summary 应 WARN: {r3['level']} {r3['ev'][:80]}")
        ok("EX-3：断言缺 passed/summary 键不符 → FAIL；无 summary（门 D 类）→ WARN 人工甄别")

        # 5. license 三态：长字段 WARN / 声明无随包 WARN / 有文件无字段 PASS
        lic = make_skill(tmp, "lic-long")
        (lic / "SKILL.md").write_text(
            "---\nname: lic-long\ndescription: x\nlicense: "
            + "L" * 130 + "\n---\n# t\n", encoding="utf-8")
        rows, _ = dc.deliver_check(lic)
        r4 = row(rows, "EX-4")
        if r4["level"] != "WARN" or "内嵌" not in r4["ev"]:
            fail(f"长 license 应 WARN: {r4['level']} {r4['ev'][:80]}")
        lif = make_skill(tmp, "lic-file")
        (lif / "LICENSE").write_text("MIT License\n", encoding="utf-8")
        rows, _ = dc.deliver_check(lif)
        if row(rows, "EX-4")["level"] != "PASS":
            fail(f"LICENSE 文件在场应 PASS: {row(rows, 'EX-4')['ev'][:80]}")
        ok("EX-4：条款内嵌（130 字符）WARN；随包 LICENSE 在场 PASS；均未声明 SKIP（组 1）")

        # 6. B1 留档关键词命中（EX-5/7 PASS）已在组 0 固化；此处固化 iteration 缺失 WARN 已在组 1。
        #    license_field 直测：块标量多行计数 + 单键（dup=False）
        val, cont, dup = dc.license_field("license: |\n  Full text line 1\n  line 2\nname: x\n")
        if val != "|" or cont != 2 or dup:
            fail(f"license_field 块标量应 (\"|\", 2, False): ({val}, {cont}, {dup})")
        ok("EX-4 license_field：块标量视为已声明+续行计数正确（多行→WARN 依据）")

        # 6b. 评审 v1.0.1 回归：BOM / B 口径弱约束 / summary 类型 / 示例口径 / 多 license 键
        bom = make_skill(tmp, "bom-skill")
        (bom / "SKILL.md").write_bytes(
            "﻿---\nname: bom-skill\ndescription: BOM 夹具\nlicense: MIT\n---\n# t\n".encode("utf-8"))
        (bom / "LICENSE").write_text("MIT License\n", encoding="utf-8")
        (bom / "evals").mkdir()
        (bom / "evals" / "evals.json").write_text('{"cases": []}', encoding="utf-8")
        rows, _ = dc.deliver_check(bom)
        r4 = row(rows, "EX-4")
        if r4["level"] != "PASS" or "MIT" not in r4["ev"]:
            fail(f"BOM 夹具 EX-4 应 PASS（frontmatter 不得因 BOM 判空）: "
                 f"{r4['level']} {r4['ev'][:80]}")
        ok("EX-4：SKILL.md 带 BOM 时 frontmatter 仍可解析（utf-8-sig+lstrip 双保险）")

        bmeta = make_skill(tmp, "fb-meta")
        (bmeta / ".verification").mkdir()
        (bmeta / ".verification" / "feedback.json").write_text(
            json.dumps({"name": "skill-x", "version": "1.0"}), encoding="utf-8")
        rows, _ = dc.deliver_check(bmeta)
        r2 = row(rows, "EX-2")
        if r2["level"] != "PASS" or "人工甄别" not in r2["ev"]:
            fail(f"B 口径无分隔键应 PASS 但证据含人工甄别提示: {r2['level']} {r2['ev'][:80]}")
        ok("EX-2：B 口径键名均无 / 或 - 分隔（疑似元数据文件）→ PASS+证据人工甄别提示")

        gst = make_skill(tmp, "gr-strnum")
        (gst / ".verification").mkdir()
        (gst / ".verification" / "grading.json").write_text(
            json.dumps({"summary": {"passed": "1", "failed": "0", "total": "1",
                                    "pass_rate": "1.0"},
                        "cases": [{"text": "x", "passed": True, "evidence": "y"}]}),
            encoding="utf-8")
        rows, _ = dc.deliver_check(gst)
        r3 = row(rows, "EX-3")
        if r3["level"] != "WARN" or "非数值" not in r3["ev"]:
            fail(f"summary 字符串数值应 WARN: {r3['level']} {r3['ev'][:80]}")
        ok("EX-3：summary 值为字符串数字 → WARN 非数值（类型人工甄别）")

        gsamp = make_skill(tmp, "gr-sample")
        (gsamp / "references").mkdir()
        (gsamp / "references" / "grading.json").write_text(
            json.dumps({"cases": [{"text": "x", "result": True}]}), encoding="utf-8")
        rows, _ = dc.deliver_check(gsamp)
        r3 = row(rows, "EX-3")
        if r3["level"] != "WARN" or "示例口径" not in r3["ev"]:
            fail(f"references/ 示例 grading 应 WARN 不 FAIL: {r3['level']} {r3['ev'][:80]}")
        ok("EX-3：references/ 内示例 grading.json 结构违规 → WARN 示例口径（不判 FAIL）")

        gdup = make_skill(tmp, "lic-dup")
        (gdup / "SKILL.md").write_text(
            "---\nname: lic-dup\ndescription: x\nlicense: MIT\nlicense: Apache-2.0\n---\n# t\n",
            encoding="utf-8")
        (gdup / "LICENSE").write_text("MIT License\n", encoding="utf-8")
        rows, _ = dc.deliver_check(gdup)
        r4 = row(rows, "EX-4")
        if r4["level"] != "WARN" or "多个 license 键" not in r4["ev"]:
            fail(f"重复 license 键应 WARN: {r4['level']} {r4['ev'][:80]}")
        ok("EX-4：frontmatter 重复 license 键 → WARN（YAML 重复顶层键非法，取首个判定）")

        # 6c. 评审 v1.0.2 回归：summary-only 形态 / 截断标注
        gso = make_skill(tmp, "gr-sumonly")
        (gso / ".verification").mkdir()
        (gso / ".verification" / "grading.json").write_text(
            json.dumps({"summary": {"passed": 1, "failed": 0, "total": 1,
                                    "pass_rate": 1.0}}),
            encoding="utf-8")
        rows, _ = dc.deliver_check(gso)
        r3 = row(rows, "EX-3")
        if r3["level"] != "WARN" or "不列明细" not in r3["ev"]:
            fail(f"summary-only 应 WARN: {r3['level']} {r3['ev'][:80]}")
        gtr = make_skill(tmp, "gr-trunc")
        (gtr / ".verification").mkdir()
        (gtr / ".verification" / "grading.json").write_text(
            json.dumps({"cases": [{"text": f"断言 {i}", "passed": True,
                                   "evidence": "y"} for i in range(25)]}),
            encoding="utf-8")
        rows, _ = dc.deliver_check(gtr)
        r3 = row(rows, "EX-3")
        if r3["level"] != "WARN" or "仅检查前 20 条" not in r3["ev"]:
            fail(f">20 条断言应 WARN 截断标注: {r3['level']} {r3['ev'][:80]}")
        ok("EX-3：summary-only（不列明细）WARN；断言 >20 条带截断标注（另 N 条未检查）")

        # 7. 退出码 0/1/2（子进程级）+ 参数错误统一 1 + --out
        if run_exit(str(sk)) != 0:
            fail("合规退出码应为 0")
        if run_exit(str(bare)) != 2:
            fail("裸夹具（仅 WARN/SKIP）退出码应为 2")
        if run_exit(str(noev)) != 1:
            fail("EX-1 FAIL 退出码应为 1")
        if run_exit() != 1:
            fail("缺 skill_dir 应返回 1，不得用 argparse 默认 exit 2")
        if run_exit(str(tmp / "nope")) != 1:
            fail("目录不存在应返回 1")
        if run_exit(str(sk), "--mode", "bogus") != 1:
            fail("未知旗标应经 error() 覆写返回 1")
        out_path = tmp / "report" / "deliver.md"
        if run_exit(str(sk), "--out", str(out_path)) != 0:
            fail("--out 模式退出码应为 0")
        if not out_path.is_file() or "存在性/schema 门报告" not in out_path.read_text(encoding="utf-8"):
            fail("--out 报告未落盘或内容缺失")
        ok("退出码 0/1/2（SKIP 不计警告）+ 参数错误统一 1 + --out 落盘")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nALL PASS ({len(passed)} 组断言)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
