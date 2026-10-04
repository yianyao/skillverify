#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_inject_test.py — inject_test.py（V23 fail-loud 注入测试）固化回归单测。

全部经 --parser-cmd 假解析器驱动（不依赖外部 agentskills CLI 在场）+ 函数级
直调覆盖"解析器缺位 → SKIP"路径。族惯例 fail/ok fail-fast。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
IT = TOOLS / "inject_test.py"

_ok_n = 0


def ok(msg: str) -> None:
    global _ok_n
    _ok_n += 1
    print(f"  PASS {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")
    sys.exit(1)


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(IT), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120, stdin=subprocess.DEVNULL)


def make_skill(root: Path) -> Path:
    d = root / "demo-skill"
    (d / "scripts").mkdir(parents=True)
    (d / ".verification").mkdir()
    (d / ".verification" / "big.md").write_text("留痕夹具——应被 _IGNORE 排除\n",
                                                encoding="utf-8")
    (d / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: A demo skill for V23 tests.\n---\n\n"
        "# Demo\n\n正文。\n", encoding="utf-8")
    (d / "scripts" / "run.py").write_text("print('ok')\n", encoding="utf-8")
    return d


def write_fake(td: Path, name: str, body: str) -> str:
    p = td / name
    p.write_text(body, encoding="utf-8")
    return p.as_posix()


FAIL_ON_MARKER = (
    "import sys\nfrom pathlib import Path\n"
    "t = (Path(sys.argv[1]) / 'SKILL.md').read_text(encoding='utf-8')\n"
    "sys.exit(1 if 'V23INJECT' in t else 0)\n")
ALWAYS_OK = "import sys\nsys.exit(0)\n"
ALWAYS_FAIL = "import sys\nsys.exit(1)\n"


def main() -> int:
    print("[test_inject_test]")

    # 1. C2 无参契约
    p = run()
    if p.returncode != 1 or "用法" not in (p.stderr or "") and "usage" not in (p.stderr or ""):
        fail(f"无参调用应 exit 1 且 stderr 含用法，实为 exit={p.returncode} stderr={p.stderr[:100]!r}")
    ok("无参调用 exit 1 带用法提示（C2 契约，_BlockArgParser）")

    with tempfile.TemporaryDirectory(prefix="t_it_") as td:
        tdp = Path(td)
        skill = make_skill(tdp)

        # 2. skill_dir 无 SKILL.md
        empty = tdp / "empty"
        empty.mkdir()
        p = run(str(empty))
        if p.returncode != 1 or "SKILL.md" not in p.stderr:
            fail(f"无 SKILL.md 目录应 exit 1，实为 exit={p.returncode} stderr={p.stderr[:100]!r}")
        ok("skill_dir 缺 SKILL.md → exit 1 带指向性提示")

        # 2b. SKILL.md 无合法 frontmatter → 注入用例无目标 exit 1
        bare = tdp / "bare"
        bare.mkdir()
        (bare / "SKILL.md").write_text("# 仅正文，无 frontmatter\n", encoding="utf-8")
        p = run(str(bare))
        if p.returncode != 1 or "frontmatter" not in p.stderr:
            fail(f"无 frontmatter 应 exit 1 带提示，实为 {p.returncode} {p.stderr[:100]!r}")
        ok("SKILL.md 无合法 frontmatter → exit 1（注入用例无目标，防静默变异失效）")

        # 2c. BOM SKILL.md 不误判——utf-8-sig 读码（复检批次：utf-8 下 \ufeff---
        #     首行判空 → 误报"无合法 frontmatter"exit 1）
        bom = tdp / "bom"
        bom.mkdir()
        (bom / "SKILL.md").write_bytes(
            b"\xef\xbb\xbf---\nname: bom-skill\ndescription: BOM fixture.\n---\n\n# B\n")
        pb = run(str(bom))
        if pb.returncode == 1 and "frontmatter" in pb.stderr:
            fail(f"BOM SKILL.md 被误判无 frontmatter：stderr={pb.stderr[:100]!r}")
        # 本工具无 --run 旗标（快速工具）——合法 frontmatter 后直接执行注入；
        # 断言只看"报告行在场"（V23-0..4 齐备=确实跑完注入流程），环境无关：
        # 无官方 CLI → 全 SKIP exit 2；有 CLI → 真注入 exit 0/1 均可，不绑环境
        for vid in ("V23-0", "V23-4"):
            if f"| {vid} |" not in pb.stdout:
                fail(f"BOM 夹具未进入注入流程（缺 {vid} 行）："
                     f"stdout={pb.stdout[-120:]!r}")
        # 直调 _mutate：以生产路径同款 utf-8-sig 读码传入（原 utf-8 读码下
        # 首行 \ufeff--- 判空 → fm=[] → 变异静默 no-op）
        sys.path.insert(0, str(TOOLS))
        import inject_test as it
        mutated = it._mutate(
            (bom / "SKILL.md").read_text(encoding="utf-8-sig"), "V23-1")
        _p2, fm2, _r2 = it._split_frontmatter(mutated)
        if it.MARKER not in mutated or "\tbroken_inject" not in "\n".join(fm2):
            fail(f"BOM 文本 _mutate 变异未生效（MARKER 或注入行缺失）：{mutated[:80]!r}")
        ok("BOM SKILL.md：utf-8-sig 读码不误判 + _mutate 变异生效（复检批次）")

        # 3. 参数校验：--timeout 0 / --out 空串
        p1 = run(str(skill), "--timeout", "0")
        p2 = run(str(skill), "--out", "  ")
        if p1.returncode != 1 or "正整数" not in p1.stderr:
            fail(f"--timeout 0 应 exit 1 带正整数提示，实为 {p1.returncode} {p1.stderr[:80]!r}")
        if p2.returncode != 1 or "--out" not in p2.stderr:
            fail(f"--out 空白应 exit 1，实为 {p2.returncode} {p2.stderr[:80]!r}")
        ok("--timeout<=0 / --out 空白 → exit 1（参数校验惯例）")

        # 4. 假解析器（对照 0/注入 1）→ 全 PASS exit 0
        good = write_fake(tdp, "fake_fail_on_marker.py", FAIL_ON_MARKER)
        p = run(str(skill), "--parser-cmd", f'"{sys.executable}" "{good}"')
        if p.returncode != 0:
            fail(f"marker 假解析器应全 PASS exit 0，实为 {p.returncode}\n{p.stdout[-500:]}")
        for vid in ("V23-0", "V23-1", "V23-2", "V23-3", "V23-4"):
            row = [ln for ln in p.stdout.splitlines() if ln.startswith(f"| {vid} |")]
            if not row or "| PASS |" not in row[0]:
                fail(f"{vid} 应 PASS，实为 {row[:1]}")
        ok("fail-loud 解析器：V23-0~4 全 PASS exit 0（注入副本被拒=宿主报错）")

        # 5. 假解析器恒 0（静默接受）→ 注入用例 FAIL exit 1
        silent = write_fake(tdp, "fake_always_ok.py", ALWAYS_OK)
        p = run(str(skill), "--parser-cmd", f'"{sys.executable}" "{silent}"')
        if p.returncode != 1:
            fail(f"静默解析器应 exit 1，实为 {p.returncode}")
        if not any(ln.startswith("| V23-") and "| FAIL |" in ln
                   and "静默接受" in ln for ln in p.stdout.splitlines()):
            fail("静默接受场景应产出 FAIL 行（非法 frontmatter 零退出）")
        ok("静默解析器：注入用例 FAIL（非 fail-loud）exit 1")

        # 6. 假解析器恒 1（对照失败）→ V23-0 FAIL + 注入转 SKIP exit 1
        broken = write_fake(tdp, "fake_always_fail.py", ALWAYS_FAIL)
        p = run(str(skill), "--parser-cmd", f'"{sys.executable}" "{broken}"')
        if p.returncode != 1:
            fail(f"对照失败场景应 exit 1，实为 {p.returncode}")
        rows = {ln.split("|")[1].strip(): ln for ln in p.stdout.splitlines()
                if ln.startswith("| V23-")}
        if "| FAIL |" not in rows.get("V23-0", ""):
            fail(f"V23-0 应 FAIL，实为 {rows.get('V23-0', '缺失')[:120]}")
        for vid in ("V23-1", "V23-2", "V23-3"):
            if rows.get(vid, "") and "| SKIP |" not in rows[vid]:
                fail(f"对照失败后 {vid} 应 SKIP，实为 {rows[vid][:120]}")
        ok("对照组失败：V23-0 FAIL + 注入用例转 SKIP（结果不可解释不硬判）")

        # 7. V23-4 原目录未触碰：静默场景下原目录哈希仍应一致（行内断言）
        p = run(str(skill), "--parser-cmd", f'"{sys.executable}" "{silent}"')
        row4 = [ln for ln in p.stdout.splitlines() if ln.startswith("| V23-4 |")]
        if not row4 or "| PASS |" not in row4[0] or "哈希一致" not in row4[0]:
            fail(f"V23-4 应 PASS（原目录只读），实为 {row4[:1]}")
        ok("V23-4 原目录 SHA256 全清单前后一致（只读自证）")

        # 8. --out 落盘
        rep = tdp / "rep" / "inject.md"
        p = run(str(skill), "--parser-cmd", f'"{sys.executable}" "{good}"',
                "--out", str(rep))
        if p.returncode != 0 or not rep.is_file() or "V23 fail-loud 注入测试报告" not in rep.read_text(encoding="utf-8"):
            fail("--out 报告未落盘或内容缺失")
        ok("--out 报告落盘")

    # 9. 解析器缺位路径（函数级直调——V23-0..3 SKIP + V23-4 实检）
    sys.path.insert(0, str(TOOLS))
    import inject_test as it  # noqa: PLC0415
    with tempfile.TemporaryDirectory(prefix="t_it2_") as td:
        skill = make_skill(Path(td))
        rows, worst = it.run_injection(skill, None, 60)
        skips = [r for r in rows if r["level"] == "SKIP"]
        r4 = [r for r in rows if r["vid"] == "V23-4"]
        if len(skips) != 4 or worst != 2 or not r4 or r4[0]["level"] != "PASS":
            fail(f"解析器缺位应 4 SKIP + V23-4 PASS worst=2，实为 worst={worst} "
                 f"rows={[(r['vid'], r['level']) for r in rows]}")
        if "COV" not in (skips[0]["ev"] if skips else ""):
            fail("SKIP 行应带 COV 覆盖缺口说明")
        ok("解析器缺位：V23-0..3 SKIP（COV 说明）+ V23-4 恒实检，worst=2")

    # 10. _IGNORE 排除留痕目录（函数级直调 _make_case_copy）
    with tempfile.TemporaryDirectory(prefix="t_it3_") as td:
        skill = make_skill(Path(td))
        outer, case_dir = it._make_case_copy(skill, None)
        try:
            if (case_dir / ".verification").exists():
                fail("_IGNORE 应排除 .verification（留痕不进注入副本——效率+敏感留痕不进临时窗口）")
            if not (case_dir / "SKILL.md").is_file() or not (case_dir / "scripts").is_dir():
                fail("排除留痕后技能本体应完整拷贝")
        finally:
            shutil.rmtree(outer, ignore_errors=True)
        ok("copytree _IGNORE：.verification 不入副本，技能本体完整")

    # 11. V23-2 折叠标量整块剥除（函数级直调 _mutate）
    text = ("---\nname: demo-skill\ndescription: >\n  折叠续行一\n  折叠续行二\n"
            "compatibility: x\n---\n\n正文\n")
    out = it._mutate(text, "V23-2")
    if "description" in out or "折叠续行" in out:
        fail(f"V23-2 应整块剥除折叠标量（键+续行），实为:\n{out}")
    if "compatibility: x" not in out or "name: demo-skill" in out:
        fail(f"V23-2 应保留其他顶层键且删 name 键，实为:\n{out}")
    ok("V23-2 折叠标量：键+续行整块剥除，其余键保留（产物语义恒为缺必填键）")

    # 12. 纪律源码断言：VERSION / _BlockArgParser / 官方 CLI 复用
    src = IT.read_text(encoding="utf-8")
    if 'VERSION = "v' not in src:
        fail("inject_test.py 缺 VERSION 常量（软断言防版本升位误报）")
    if "class _BlockArgParser" not in src:
        fail("inject_test.py 应内嵌 _BlockArgParser（参数错误 exit 1）")
    if "find_official_cli" not in src:
        fail("inject_test.py 应复用 check_skill.find_official_cli（agentskills 优先）")
    ok("纪律固化：VERSION + _BlockArgParser + find_official_cli 复用")

    print(f"\nALL PASS ({_ok_n} 组断言)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
