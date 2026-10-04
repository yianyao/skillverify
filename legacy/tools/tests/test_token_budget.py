#!/usr/bin/env python3
"""test_token_budget.py — token_budget.py 固化回归单测（V11 token 口径 + V17 预算门）。

以临时夹具固化开发期实测结论：合规全 PASS、正文/元数据/扩展层三类超限响亮 FAIL、
阈值可调、frontmatter 剥离口径（正文不含元数据）、CJK 占比提示、覆盖缺口降 WARN
不假 PASS、退出码 0/1/2 工具族约定（缺参返回 1 不撞 WARN 码 2）。
任何 token_budget.py 改动后必须先过本文件。
只读 + 临时目录夹具，无系统副作用。

用法: python tests/test_token_budget.py    # 全过打印 ALL PASS，失败非零退出
"""
from __future__ import annotations

import importlib.util
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


tb = load("token_budget_under_test", TOOLS / "token_budget.py")


def ok(msg: str) -> None:
    passed.append(msg)
    print(f"  PASS {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")
    sys.exit(1)


def make_skill(root: Path, name: str, desc: str, body: str) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n{body}",
        encoding="utf-8", newline="\n")
    return d


def levels(rows: list[dict]) -> dict[str, str]:
    return {r["vid"]: r["level"] for r in rows}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="tb-test-"))
    try:
        GOOD_DESC = "批量重命名图片文件的工具"
        GOOD_BODY = "# t\n\n每次运行都需要的核心指令。\n" * 5

        # 0. token 估算口径单测（V11 固定口径）
        if tb.estimate_tokens("", 4) != 0:
            fail("空文本应为 0 tokens")
        if tb.estimate_tokens("a" * 17, 4) != 5:  # ceil(17/4)
            fail(f"ceil 口径不符: {tb.estimate_tokens('a' * 17, 4)}")
        if tb.estimate_tokens("a" * 16, 4) != 4:
            fail(f"整除口径不符: {tb.estimate_tokens('a' * 16, 4)}")
        ok("V11 口径：ceil(字符数/4) 固定实现")

        # 1. 合规夹具：全 PASS + COV INFO
        good = make_skill(tmp, "good-skill", GOOD_DESC, GOOD_BODY)
        (good / "references").mkdir()
        (good / "references" / "g.md").write_text("\n".join(f"l{i}" for i in range(100)) + "\n",
                                                  encoding="utf-8")
        rows, st = tb.budget_check(good, 5000, 100, 500, 4)
        lv = levels(rows)
        for vid in ("V11-1", "V17-1", "V17-2"):
            if lv[vid] != "PASS":
                fail(f"合规夹具 {vid} 应 PASS，实为 {lv[vid]}: {[r for r in rows if r['vid']==vid][0]['ev']}")
        if lv["V17-3"] != "INFO" or lv["COV"] != "INFO" or st["ext_files"] != 1:
            fail(f"V17-3 应 INFO、COV 应 INFO、ext_files=1，实为 {lv} {st}")
        ok("合规夹具 V11-1/V17-1/V17-2 全 PASS + V17-3 INFO + COV INFO")

        # 2. frontmatter 剥离口径：正文 token 不含元数据
        fm_long = "x" * 800  # frontmatter 长、正文短
        fm_skill = make_skill(tmp, "fm-skill", fm_long, "# t\n")
        rows, st = tb.budget_check(fm_skill, 5000, 1000, 500, 4)
        # 正文只有 4 字符级 → 远小于预算；若口径错把 frontmatter 算进正文会 FAIL
        if rows[0]["level"] != "PASS" or st["body_tokens"] > 10:
            fail(f"正文应剥离 frontmatter: tokens={st['body_tokens']} {rows[0]['ev']}")
        ok("V11-1 frontmatter 剥离：正文 token 只计正文（元数据归 V17-1）")

        # 3. 正文超 5000 tokens → FAIL
        fat_body = "word " * 5000  # 25000 chars → 6250 tokens
        fat = make_skill(tmp, "fat-body", GOOD_DESC, fat_body)
        rows, st = tb.budget_check(fat, 5000, 100, 500, 4)
        if rows[0]["level"] != "FAIL" or st["body_tokens"] < 5000:
            fail(f"正文超限应 FAIL: {rows[0]['level']} tokens={st['body_tokens']}")
        ok("V11-1 正文 ≥5000 tokens → FAIL（<5000 为官方 [M] 口径）")

        # 4. 元数据超 100 tokens → FAIL（项目收紧）
        meta_fat = make_skill(tmp, "fat-meta", "x" * 500, GOOD_BODY)
        rows, _ = tb.budget_check(meta_fat, 5000, 100, 500, 4)
        if rows[1]["level"] != "FAIL":
            fail(f"元数据超限应 FAIL: {rows[1]['level']} {rows[1]['ev']}")
        ok("V17-1 元数据 >100 tokens → FAIL（项目级收紧）")

        # 5. 扩展层单文件 >500 行 → FAIL 并列出文件
        ext = make_skill(tmp, "ext-fat", GOOD_DESC, GOOD_BODY)
        (ext / "references").mkdir()
        (ext / "assets").mkdir()
        (ext / "references" / "huge.md").write_text("\n".join(f"l{i}" for i in range(520)) + "\n",
                                                    encoding="utf-8")
        (ext / "assets" / "ok.css").write_text("\n".join(f"l{i}" for i in range(200)) + "\n",
                                               encoding="utf-8")
        rows, st = tb.budget_check(ext, 5000, 100, 500, 4)
        v2 = [r for r in rows if r["vid"] == "V17-2"][0]
        if v2["level"] != "FAIL" or "huge.md" not in v2["ev"] or "520" not in v2["ev"]:
            fail(f"扩展层超行应 FAIL 且指向 huge.md:520: {v2['level']} {v2['ev']}")
        if st["ext_files"] != 2:
            fail(f"应扫 references+assets 共 2 文件，实为 {st['ext_files']}")
        ok("V17-2 扩展层单文件 >500 行 → FAIL（references/+assets/ 全扫）")

        # 5b. scripts/ 不属扩展层（W-S §3 行明确 references/、assets/）
        sc = make_skill(tmp, "scripts-exempt", GOOD_DESC, GOOD_BODY)
        (sc / "scripts").mkdir()
        (sc / "scripts" / "long.py").write_text("\n".join(f"l{i}" for i in range(900)) + "\n",
                                                encoding="utf-8")
        rows, st = tb.budget_check(sc, 5000, 100, 500, 4)
        v2 = [r for r in rows if r["vid"] == "V17-2"][0]
        if v2["level"] != "PASS" or "900" in v2["ev"]:
            fail(f"scripts/ 不应计入扩展层: {v2['level']} {v2['ev']}")
        ok("V17-2 scripts/ 不属扩展层（900 行脚本不计）")

        # 6. 阈值可调：正文预算调低到当前值以下即触发
        rows, _ = tb.budget_check(good, 10, 100, 500, 4)
        if rows[0]["level"] != "FAIL":
            fail(f"--body-budget 10 应触发 FAIL: {rows[0]['level']}")
        ok("阈值可调：--body-budget 调低即触发")

        # 7. CJK 占比提示：>30% 时证据含提示（不改变判定）
        cjk_rows, _ = tb.budget_check(good, 5000, 100, 500, 4)
        v1 = [r for r in cjk_rows if r["vid"] == "V11-1"][0]
        if "CJK 占比" not in v1["ev"]:
            fail(f"CJK 夹具证据应含占比提示: {v1['ev']}")
        ok("V11-1 CJK 占比 >30% 提示入证据（口径不变，提示人工关注）")

        # 8. 无 description → V17-1 WARN 不假 PASS
        nd = tmp / "no-desc"
        nd.mkdir()
        (nd / "SKILL.md").write_text("---\nname: no-desc\n---\n# t\n", encoding="utf-8")
        rows, _ = tb.budget_check(nd, 5000, 100, 500, 4)
        if rows[1]["level"] != "WARN" or "description" not in rows[1]["ev"]:
            fail(f"无 description 应 WARN: {rows[1]['level']} {rows[1]['ev']}")
        ok("覆盖纪律：无 description → V17-1 WARN 不假 PASS")

        # 9. 读取失败 → COV WARN + PASS 行降 WARN（覆盖不全不假 PASS）
        import unittest.mock as mock
        with mock.patch.object(tb, "count_lines",
                               side_effect=OSError(13, "Permission denied")):
            rows, st = tb.budget_check(good, 5000, 100, 500, 4)
        # count_lines 打在 SKILL.md 行数（V17-3 → WARN 不缺席，v1.0.1 评审 2）
        # 与扩展层 g.md——V11-1 估算不受影响，但 V17-2 计缺口后整体降级
        lv = levels(rows)
        if lv["COV"] != "WARN":
            fail(f"读取失败时 COV 应 WARN，实为 {lv['COV']}: {[r for r in rows if r['vid']=='COV'][0]['ev']}")
        for vid in ("V11-1", "V17-2"):
            if lv[vid] == "PASS":
                fail(f"读取失败时 {vid} 不得假 PASS")
        v3 = [r for r in rows if r["vid"] == "V17-3"]
        if not v3 or v3[0]["level"] != "WARN" or "行数不可验" not in v3[0]["ev"]:
            fail(f"读取失败时 V17-3 应在场且 WARN（行数不可验）: {v3}")
        ok("覆盖纪律：读取失败 → COV WARN + 零命中行降 WARN + V17-3 WARN 不缺席")

        # 9b. 无 SKILL.md → V11-1 FAIL + stats 键结构完整（v1.0.1 评审 1）
        empty = tmp / "no-skillmd"
        empty.mkdir()
        rows, st = tb.budget_check(empty, 5000, 100, 500, 4)
        if rows[0]["level"] != "FAIL":
            fail(f"无 SKILL.md 应 FAIL: {rows[0]['level']}")
        for k in ("read_err", "ext_files", "body_tokens", "meta_tokens"):
            if k not in st:
                fail(f"无 SKILL.md 早退 stats 缺键 {k}（下游调用方 KeyError 风险）: {st}")
        ok("无 SKILL.md → V11-1 FAIL + stats 四键齐全（fail-loud 且结构一致）")

        # 10. 退出码 0/1/2 与 --out 落盘（子进程级验证）
        def run_exit(*args: str) -> int:
            return subprocess.run(
                [sys.executable, str(TOOLS / "token_budget.py"), *args],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30, stdin=subprocess.DEVNULL).returncode

        if run_exit(str(good)) != 0:
            fail("合规退出码应为 0")
        if run_exit(str(ext)) != 1:
            fail("扩展层超限 FAIL 退出码应为 1")
        out_path = tmp / "report" / "tb.md"
        if run_exit(str(tmp / "fat-meta"), "--out", str(out_path)) != 1:
            fail("元数据超限退出码应为 1")
        if not out_path.is_file() or "上下文预算报告" not in out_path.read_text(encoding="utf-8"):
            fail("--out 报告未落盘或内容缺失")
        # 无 SKILL.md 目录 → FAIL 码 1
        if run_exit(str(empty)) != 1:
            fail("无 SKILL.md 退出码应为 1")
        # 非法参数 → 统一 1，不得撞 WARN 码 2（naming_precheck v1.0.1 教训）
        if run_exit() != 1:
            fail("缺 skill_dir 应返回 1 阻断码，不得用 argparse 默认 exit 2")
        if run_exit(str(good), "--chars-per-token", "0") != 1:
            fail("chars-per-token=0 应返回 1 阻断码")
        if run_exit(str(good), "--body-budget", "-5") != 1:
            fail("负预算应返回 1 阻断码")
        # argparse 类型转换错误（v1.0.1 评审 5）：error() 覆写后也统一 1
        if run_exit(str(good), "--chars-per-token", "abc") != 1:
            fail("--chars-per-token abc 应经 error() 覆写返回 1，不得 argparse 默认 exit 2")
        if run_exit(str(good), "--body-budget", "abc") != 1:
            fail("--body-budget abc 应返回 1 阻断码")
        ok("退出码 0/1/2 约定 + --out 落盘 + 全部参数错误（缺参/非法值/类型错误）统一 1 不撞 WARN 码")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nALL PASS ({len(passed)} 组断言)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
