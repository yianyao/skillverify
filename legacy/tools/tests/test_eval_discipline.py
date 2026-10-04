#!/usr/bin/env python3
"""test_eval_discipline.py — eval_discipline.py 固化回归单测（V21/V28/V29 评测纪律三门）。

以临时夹具固化开发期实测结论：合规全 PASS/SKIP、断言时机 mtime 两向（os.utime 控制）、
assertions_added_at 显式字段优先、非断言形态/未提供依据 SKIP、V28 三态、
V29 record→verify 闭环 + 篡改检测 + 旧格式（下划线键）兼容、
退出码 0/1/2（全部参数错误统一 1 不撞 WARN 码）；
v1.0.1 首轮外部评审回归：snapshot SKIP 相对路径判定、无秒 ISO 补秒（3.10 兼容）、
cases 空断言 WARN、record 缺快照目录 stderr 提示、行内无空格 snapshot JSON、
空 --description-text fail-fast。
任何 eval_discipline.py 改动后必须先过本文件。
只读 + 临时目录夹具，无系统副作用。

用法: python tests/test_eval_discipline.py    # 全过打印 ALL PASS，失败非零退出
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
passed: list[str] = []


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ed = load("eval_discipline_under_test", TOOLS / "eval_discipline.py")


def ok(msg: str) -> None:
    passed.append(msg)
    print(f"  PASS {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")
    sys.exit(1)


def levels(rows: list[dict]) -> dict[str, str]:
    return {r["vid"]: r["level"] for r in rows}


def make_skill(root: Path, name: str) -> Path:
    d = root / name
    (d / "evals").mkdir(parents=True)
    (d / ".verification").mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        "---\nname: " + name + "\ndescription: 评测纪律夹具技能的描述文本\n---\n# t\n",
        encoding="utf-8", newline="\n")
    return d


def make_workspace(root: Path, name: str, output_body: str = "产出\n") -> Path:
    ws = root / (name + "-workspace")
    out = ws / "iteration-1" / "eval-basic" / "with_skill" / "outputs"
    out.mkdir(parents=True)
    (out / "result.md").write_text(output_body, encoding="utf-8")
    old = time.time() - 3600
    os.utime(out / "result.md", (old, old))
    return ws


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ed-test-"))
    try:
        # 0. 合规夹具：record→check 闭环全绿
        sk = make_skill(tmp, "good-skill")
        evals = {"cases": [{"name": "c1", "assertions": [{"text": "a", "passed": True}]},
                           {"name": "c2", "assertions": [{"text": "b", "passed": True}]}]}
        (sk / "evals" / "evals.json").write_text(
            json.dumps(evals, ensure_ascii=False), encoding="utf-8")
        ws = make_workspace(tmp, "good-skill")
        # evals.json 写在产出之后（mtime 晚于产出）——记录时间基线供回拨用例复用
        evals_mtime = (sk / "evals" / "evals.json").stat().st_mtime
        txt, err = ed.record_baseline(sk, "v1.0", "1", "2026-10-03T00:10:00", "report.md", ws)
        if err:
            fail(f"record 不应报错: {err}")
        rows, st = ed.discipline_check(sk, ws, None, None)
        lv = levels(rows)
        if lv["V21-1"] != "INFO":
            fail(f"V21-1 应 INFO（用例数记录），实为 {lv['V21-1']}")
        if lv["V21-2"] != "PASS" or lv["V29-1"] != "PASS" or lv["V29-2"] != "PASS":
            fail(f"合规夹具 V21-2/V29-1/V29-2 应 PASS: {lv}")
        if lv["V28-1"] != "SKIP" or lv["V29-2"] != "PASS":
            fail(f"未提供 V28 依据应 SKIP: {lv['V28-1']}")
        if st["skips"] != 1:
            fail(f"skips 应为 1: {st}")
        ok("合规夹具：record→check 闭环 V21-1 INFO + V21-2/V29-1/V29-2 PASS + V28 SKIP")

        # 1. evals.json 缺失 → V21-1 FAIL、V21-2 SKIP
        noev = make_skill(tmp, "no-evals")
        rows, _ = ed.discipline_check(noev, None, None, None)
        lv = levels(rows)
        if lv["V21-1"] != "FAIL" or lv["V21-2"] != "SKIP":
            fail(f"evals 缺失应 V21-1 FAIL + V21-2 SKIP: {lv}")
        ok("evals.json 缺失 → V21-1 FAIL（§7.1.1）+ V21-2 SKIP")

        # 1b. evals.json 解析失败 → FAIL
        badj = make_skill(tmp, "bad-json")
        (badj / "evals" / "evals.json").write_text("{broken", encoding="utf-8")
        rows, _ = ed.discipline_check(badj, None, None, None)
        if rows[0]["level"] != "FAIL" or "解析失败" not in rows[0]["ev"]:
            fail(f"坏 JSON 应 FAIL: {rows[0]['level']} {rows[0]['ev']}")
        ok("evals.json 解析失败 → V21-1 FAIL")

        # 2. 断言时机 mtime 启发式：evals.json 回拨早于产出 → FAIL
        old_evals = time.time() - 7200
        os.utime(sk / "evals" / "evals.json", (old_evals, old_evals))
        rows, _ = ed.discipline_check(sk, ws, None, None)
        lv = levels(rows)
        if lv["V21-2"] != "FAIL" or "未晚于" not in [r for r in rows if r["vid"] == "V21-2"][0]["ev"]:
            fail(f"evals 早于产出应 FAIL: {lv['V21-2']}")
        # 恢复 mtime（后续用例依赖合规基线）
        os.utime(sk / "evals" / "evals.json", (evals_mtime, evals_mtime))
        ok("V21-2 mtime 启发式：断言早于产出 → FAIL（os.utime 回拨验证）")

        # 2b. assertions_added_at 显式字段优先于 mtime
        (sk / "evals" / "evals.json").write_text(
            json.dumps({**evals, "assertions_added_at": "2026-01-01T00:00:00"},
                       ensure_ascii=False), encoding="utf-8")
        os.utime(sk / "evals" / "evals.json", (old_evals, old_evals))
        rows, _ = ed.discipline_check(sk, ws, None, None)
        v22 = [r for r in rows if r["vid"] == "V21-2"][0]
        # 显式时间戳 2026-01-01 早于产出（昨天）→ FAIL，且证据标明显式字段口径
        if v22["level"] != "FAIL" or "显式字段口径" not in v22["ev"]:
            fail(f"显式字段口径未生效: {v22['level']} {v22['ev']}")
        (sk / "evals" / "evals.json").write_text(
            json.dumps({**evals, "assertions_added_at": "2099-01-01T00:00:00"},
                       ensure_ascii=False), encoding="utf-8")
        rows, _ = ed.discipline_check(sk, ws, None, None)
        if [r for r in rows if r["vid"] == "V21-2"][0]["level"] != "PASS":
            fail("未来显式时间戳应 PASS")
        # 恢复
        (sk / "evals" / "evals.json").write_text(json.dumps(evals, ensure_ascii=False), encoding="utf-8")
        os.utime(sk / "evals" / "evals.json", (evals_mtime, evals_mtime))
        ok("V21-2 显式 assertions_added_at 字段优先于 mtime（早/晚两向验证）")

        # 3. 非断言形态（queries 触发查询集）→ V21-2 SKIP
        qsk = make_skill(tmp, "query-skill")
        (qsk / "evals" / "evals.json").write_text(
            json.dumps({"queries": [{"q": "x", "should_trigger": True}] * 18},
                       ensure_ascii=False), encoding="utf-8")
        rows, _ = ed.discipline_check(qsk, ws, None, None)
        lv = levels(rows)
        if lv["V21-1"] != "INFO" or lv["V21-2"] != "SKIP":
            fail(f"queries 形态应 V21-1 INFO + V21-2 SKIP: {lv}")
        if "18" not in [r for r in rows if r["vid"] == "V21-1"][0]["ev"]:
            fail("V21-1 证据应含用例数")
        ok("V21 queries 形态：V21-1 INFO 记数 + V21-2 SKIP（llm-review 实弹形态）")

        # 4. V28 三态：一致 PASS / 不一致 FAIL / 未提供 SKIP
        dsk = make_skill(tmp, "desc-skill")
        dsk.joinpath(".verification", "desc-final.md").write_text(
            "评测纪律夹具技能的描述文本\n", encoding="utf-8")
        dsk.joinpath(".verification", "desc-bad.md").write_text(
            "另一个描述\n", encoding="utf-8")
        rows, _ = ed.discipline_check(dsk, None, dsk / ".verification" / "desc-final.md", None)
        if levels(rows)["V28-1"] != "PASS" or "逐字符一致" not in [r for r in rows if r["vid"] == "V28-1"][0]["ev"]:
            fail(f"一致应 PASS: {levels(rows)['V28-1']}")
        rows, _ = ed.discipline_check(dsk, None, dsk / ".verification" / "desc-bad.md", None)
        if levels(rows)["V28-1"] != "FAIL":
            fail("不一致应 FAIL")
        rows, _ = ed.discipline_check(dsk, None, None, "评测纪律夹具技能的描述文本")
        if levels(rows)["V28-1"] != "PASS":
            fail("--description-text 一致应 PASS")
        rows, _ = ed.discipline_check(dsk, None, None, None)
        if levels(rows)["V28-1"] != "SKIP":
            fail("未提供应 SKIP")
        ok("V28 三态：一致 PASS（文件/文本两入口）/ 不一致 FAIL / 未提供 SKIP")

        # 5. V29 旧格式（llm-review 形态，下划线键）→ V29-1 PASS + V29-2 SKIP
        lsk = make_skill(tmp, "legacy-baseline")
        (lsk / ".verification" / ".iteration-baseline").write_text(
            "iteration: 1\naccepted_at: 2026-10-02\nversion: v1.3\n"
            "acceptance_report: gate-m/acceptance-report.md\n"
            "snapshot_sha256_skill_md: 见 D 盘 audit-sheet\n"
            "note: V29 iteration 基线——验收通过时点快照\n", encoding="utf-8")
        rows, _ = ed.discipline_check(lsk, None, None, None)
        lv = levels(rows)
        if lv["V29-1"] != "PASS" or "v1.3" not in [r for r in rows if r["vid"] == "V29-1"][0]["ev"]:
            fail(f"旧格式应 PASS 且含版本: {lv['V29-1']}")
        if lv["V29-2"] != "SKIP" or "record" not in [r for r in rows if r["vid"] == "V29-2"][0]["ev"]:
            fail(f"旧格式 V29-2 应 SKIP 并提示升级: {lv['V29-2']}")
        ok("V29 旧格式兼容：下划线键解析 + V29-1 PASS + V29-2 SKIP 提示 record 升级")

        # 5b. 基线缺失 → V29-1 WARN + V29-2 SKIP（不假 PASS 不误阻断）
        rows, _ = ed.discipline_check(make_skill(tmp, "no-baseline"), None, None, None)
        lv = levels(rows)
        if lv["V29-1"] != "WARN" or lv["V29-2"] != "SKIP":
            fail(f"基线缺失应 V29-1 WARN + V29-2 SKIP: {lv}")
        ok("V29 基线缺失 → V29-1 WARN（阶段判断归人工）+ V29-2 SKIP")

        # 5c. 篡改检测：record 后改快照内容 → V29-2 FAIL；新增文件 → 基线外新增
        (ws / "iteration-1" / "eval-basic" / "with_skill" / "outputs" / "result.md").write_text(
            "被篡改\n", encoding="utf-8")
        rows, _ = ed.discipline_check(sk, ws, None, None)
        v92 = [r for r in rows if r["vid"] == "V29-2"][0]
        if v92["level"] != "FAIL" or "内容已变" not in v92["ev"]:
            fail(f"篡改应 FAIL: {v92['level']} {v92['ev']}")
        (ws / "iteration-1" / "eval-basic" / "with_skill" / "outputs" / "extra.md").write_text(
            "新增\n", encoding="utf-8")
        rows, _ = ed.discipline_check(sk, ws, None, None)
        v92 = [r for r in rows if r["vid"] == "V29-2"][0]
        if v92["level"] != "FAIL" or "基线外新增" not in v92["ev"]:
            fail(f"基线外新增应 FAIL: {v92['ev']}")
        # 恢复快照现状（后续退出码用例依赖合规基线）——内容与 mtime 双恢复，
        # 重写会把 mtime 重置为当下、污染 V21-2 时序前提（开发期自测暴露）
        (ws / "iteration-1" / "eval-basic" / "with_skill" / "outputs" / "result.md").write_text(
            "产出\n", encoding="utf-8")
        stale = time.time() - 3600
        os.utime(ws / "iteration-1" / "eval-basic" / "with_skill" / "outputs" / "result.md",
                 (stale, stale))
        (ws / "iteration-1" / "eval-basic" / "with_skill" / "outputs" / "extra.md").unlink()
        ok("V29-2 防覆盖：篡改/基线外新增均 FAIL（§15.4 迭代留痕）")

        # 6. 退出码 0/1/2 与 --out（子进程级）
        def run_exit(*args: str) -> int:
            return subprocess.run(
                [sys.executable, str(TOOLS / "eval_discipline.py"), *args],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30, stdin=subprocess.DEVNULL).returncode

        if run_exit(str(sk), "--workspace", str(ws)) != 0:
            fail("合规退出码应为 0")
        if run_exit(str(noev)) != 1:
            fail("evals 缺失 FAIL 退出码应为 1")
        warn_only = make_skill(tmp, "warn-only")
        # 查询集形态（V21-1 INFO/V21-2 SKIP）+ 无基线（V29-1 WARN）→ 纯 WARN exit 2
        (warn_only / "evals" / "evals.json").write_text(
            json.dumps({"queries": [{"q": "x", "should_trigger": True}]},
                       ensure_ascii=False), encoding="utf-8")
        if run_exit(str(warn_only)) != 2:
            fail("仅 WARN（基线缺失）退出码应为 2")
        out_path = tmp / "report" / "ed.md"
        if run_exit(str(sk), "--workspace", str(ws), "--out", str(out_path)) != 0:
            fail("--out 模式退出码应为 0")
        if not out_path.is_file() or "评测纪律三门报告" not in out_path.read_text(encoding="utf-8"):
            fail("--out 报告未落盘或内容缺失")
        ok("退出码 0/1/2 约定（SKIP 不计警告）+ --out 落盘")

        # 6b. record 模式 CLI + 全部参数错误统一 1（撞码纪律）
        rsk = make_skill(tmp, "record-cli")
        if run_exit(str(rsk), "--mode", "record", "--version", "v1.0",
                    "--iteration", "1", "--accepted-at", "2026-10-03T01:00:00") != 0:
            fail("record CLI 应成功")
        if not (rsk / ".verification" / ".iteration-baseline").is_file():
            fail("record 基线未落盘")
        if run_exit(str(rsk), "--mode", "record") != 1:
            fail("record 缺 --version/--iteration 应返回 1")
        if run_exit() != 1:
            fail("缺 skill_dir 应返回 1，不得用 argparse 默认 exit 2")
        if run_exit(str(sk), "--mode", "bogus") != 1:
            fail("--mode bogus 应经 error() 覆写返回 1")
        if run_exit(str(sk), "--mode", "record", "--version", "v1", "--iteration", "1",
                    "--snapshot-dir", str(tmp / "nope")) != 1:
            fail("快照目录不存在 record 应返回 1")
        if run_exit(str(sk), "--description-final", str(tmp / "a.md"),
                    "--description-text", "x") != 1:
            fail("V28 双依据互斥应返回 1")
        if run_exit(str(sk), "--workspace", str(tmp / "no-ws")) != 1:
            fail("workspace 不存在应返回 1")
        ok("record CLI 闭环 + 全部参数错误（缺参/非法值/互斥/路径不存在）统一 1 不撞 WARN 码")

        # 7. 评审 1 回归：snapshot_dir_files SKIP 判定只看快照根相对路径
        #    （v1.0 用绝对路径 p.parts——祖先目录名 venv 会清空整个快照）
        venv_root = tmp / "venv" / "snap-under-venv"
        venv_root.mkdir(parents=True)
        (venv_root / "a.txt").write_text("快照内容\n", encoding="utf-8")
        (venv_root / "venv").mkdir()  # 快照内部 venv 目录仍应跳过
        (venv_root / "venv" / "ignored.txt").write_text("x\n", encoding="utf-8")
        files, errs = ed.snapshot_dir_files(venv_root)
        if errs or list(files) != ["a.txt"]:
            fail(f"祖先/内部 venv 目录处理不符: files={files} errs={errs}")
        ok("snapshot_dir_files：SKIP_DIRS 按快照根相对路径判定（祖先目录名 venv 不清空快照）")

        # 8. 评审 2 回归：无秒 ISO 时间戳补秒解析（Python 3.10 fromisoformat 兼容）
        if ed.parse_iso_ts("2099-01-01T00:00") is None:
            fail("无秒 ISO（未来时点）应补秒后解析成功")
        if ed.parse_iso_ts("2026-01-01T00:00") is None:
            fail("无秒 ISO（过去时点）应解析成功")
        if ed.parse_iso_ts("2026-01-01T00:00:00") is None:
            fail("带秒 ISO 应原样解析")
        if ed.parse_iso_ts("not-a-time") is not None:
            fail("非法时间戳应返回 None")
        # 端到端：无秒未来时间戳 → 显式字段口径 PASS（而非 3.10 上的"格式非法"FAIL）
        (sk / "evals" / "evals.json").write_text(
            json.dumps({**evals, "assertions_added_at": "2099-01-01T00:00"},
                       ensure_ascii=False), encoding="utf-8")
        rows, _ = ed.discipline_check(sk, ws, None, None)
        v22 = [r for r in rows if r["vid"] == "V21-2"][0]
        if v22["level"] != "PASS" or "显式字段口径" not in v22["ev"]:
            fail(f"无秒显式时间戳应 PASS: {v22['level']} {v22['ev']}")
        # 恢复（后续用例依赖合规基线）
        (sk / "evals" / "evals.json").write_text(json.dumps(evals, ensure_ascii=False),
                                                 encoding="utf-8")
        os.utime(sk / "evals" / "evals.json", (evals_mtime, evals_mtime))
        ok("无秒 ISO：parse_iso_ts 补秒（3.10 兼容）+ 端到端 PASS 不误判格式非法")

        # 9. 评审 3 回归：cases 形态断言全空 → V21-2 WARN（不再误 SKIP"非断言形态"）
        esk = make_skill(tmp, "empty-asserts")
        (esk / "evals" / "evals.json").write_text(
            json.dumps({"cases": [{"name": "c1", "assertions": []}, {"name": "c2"}]},
                       ensure_ascii=False), encoding="utf-8")
        rows, _ = ed.discipline_check(esk, ws, None, None)
        lv = levels(rows)
        if lv["V21-1"] != "INFO":
            fail(f"空断言 cases 形态 V21-1 应 INFO: {lv['V21-1']}")
        v22 = [r for r in rows if r["vid"] == "V21-2"][0]
        if v22["level"] != "WARN" or "断言数组全为空" not in v22["ev"]:
            fail(f"cases 空断言应 V21-2 WARN: {v22['level']} {v22['ev']}")
        ok("cases 形态断言全空 → V21-2 WARN 提示补断言（与'非断言形态'SKIP 区分）")

        # 10. 评审 4 回归：record 缺 --snapshot-dir → 成功落键值基线 + stderr 明示 V29-2 SKIP
        rsk2 = make_skill(tmp, "record-no-snap")
        pr = subprocess.run(
            [sys.executable, str(TOOLS / "eval_discipline.py"), str(rsk2),
             "--mode", "record", "--version", "v1.0", "--iteration", "1"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, stdin=subprocess.DEVNULL)
        if pr.returncode != 0:
            fail(f"record（无快照目录）应成功: rc={pr.returncode} {pr.stderr}")
        if "--snapshot-dir" not in pr.stderr or "SKIP" not in pr.stderr:
            fail(f"record 缺快照目录应 stderr 提示: {pr.stderr!r}")
        bl = (rsk2 / ".verification" / ".iteration-baseline").read_text(encoding="utf-8")
        if "snapshot:" in bl:
            fail("无快照目录 record 的基线不应含 snapshot 块")
        ok("record 缺 --snapshot-dir：键值基线照常落盘 + stderr 明示 V29-2 将 SKIP")

        # 11. 评审 5 回归：parse_baseline 行内无空格 "snapshot:{…}" JSON 兼容
        isk = make_skill(tmp, "inline-snap")
        snap_obj = {"dirs": {"snap": {"root": str(tmp / "whatever"),
                                      "files": {"a.txt": "h"}}}}
        (isk / ".verification" / ".iteration-baseline").write_text(
            "iteration: 1\naccepted_at: 2026-10-03T00:00:00\nversion: v1.0\n"
            "snapshot:" + json.dumps(snap_obj, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8")
        kv, snap, perr = ed.parse_baseline(isk / ".verification" / ".iteration-baseline")
        if perr or snap != snap_obj or kv.get("iteration") != "1":
            fail(f"无空格行内 snapshot JSON 应解析: err={perr} snap={snap}")
        ok("parse_baseline：行内无空格 snapshot:{…} 兼容（非 JSON 值仍落普通键值）")

        # 12. 评审 6 回归：空 --description-text fail-fast 统一 exit 1
        if run_exit(str(sk), "--description-text", "") != 1:
            fail("空 --description-text 应 fail-fast 返回 1")
        ok("空 --description-text fail-fast 统一 exit 1（不产生误导性 V28-1 FAIL）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nALL PASS ({len(passed)} 组断言)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
