#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_kw_locator.py — kw_locator.py（B3-1 关键词定位器）固化回归单测。

族惯例 fail/ok fail-fast；夹具技能临时构造，不依赖真实技能。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
KL = TOOLS / "kw_locator.py"

_ok_n = 0


def ok(msg: str) -> None:
    global _ok_n
    _ok_n += 1
    print(f"  PASS {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")
    sys.exit(1)


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(KL), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=60, stdin=subprocess.DEVNULL)


def make_skill(root: Path, with_hit: bool = True,
               with_flag: bool = False) -> Path:
    d = root / "demo-skill"
    (d / "scripts").mkdir(parents=True)
    prose = ("正文提及 delete 数据前须三思。\n" if with_hit
             else "正文仅作占位，无破坏性关键词。\n")
    (d / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: A demo skill for locator tests.\n---\n\n"
        f"# Demo\n\n{prose}", encoding="utf-8")
    if with_hit:
        flag = " # --confirm" if with_flag else ""
        (d / "scripts" / "clean.py").write_text(
            f"import shutil\nshutil.rmtree(p){flag}\n", encoding="utf-8")
    return d


def main() -> int:
    print("[test_kw_locator]")

    # 1. C2 无参契约
    p = run()
    if p.returncode != 1 or "用法" not in (p.stderr or "") and "usage" not in (p.stderr or ""):
        fail(f"无参调用应 exit 1 且 stderr 含用法，实为 exit={p.returncode} stderr={p.stderr[:100]!r}")
    ok("无参调用 exit 1 带用法提示（C2 契约，_BlockArgParser）")

    with tempfile.TemporaryDirectory(prefix="t_kl_") as td:
        tdp = Path(td)

        # 2. skill_dir 无 SKILL.md / --out 空串
        empty = tdp / "empty"
        empty.mkdir()
        p1 = run(str(empty))
        p2 = run(str(tdp), "--out", "")
        if p1.returncode != 1 or "SKILL.md" not in p1.stderr:
            fail(f"无 SKILL.md 应 exit 1，实为 {p1.returncode} {p1.stderr[:80]!r}")
        if p2.returncode != 1 or "--out" not in p2.stderr:
            fail(f"--out 空串应 exit 1，实为 {p2.returncode} {p2.stderr[:80]!r}")
        ok("skill_dir 缺 SKILL.md / --out 空串 → exit 1（参数校验惯例）")

        # 3. 有命中（代码无防护）→ exit 0，报告含 文件:行/关键词/防护标注/上下文
        skill = make_skill(tdp / "a")
        p = run(str(skill))
        if p.returncode != 0:
            fail(f"信息供给工具命中场景应 exit 0，实为 {p.returncode}")
        out = p.stdout
        for needle in ("命中", "定位方式: S 定位器", "SKILL.md:", "正文"):
            if needle not in out:
                fail(f"报告缺要素 {needle!r}")
        # 词表词整词匹配（有意让 delete 出现在注释中——词表匹配是文本级，注释也算）
        (skill / "scripts" / "clean.py").write_text(
            "import os\nos.remove(p)  # delete 临时目录\n", encoding="utf-8")
        p = run(str(skill))
        out = p.stdout
        if p.returncode != 0 or "scripts/clean.py:2" not in out or "关键词 delete" not in out:
            fail(f"应定位 scripts/clean.py:2 关键词 delete，实为:\n{out[-600:]}")
        if "无 --confirm/--force/--dry-run" not in out:
            fail("代码命中无防护应标注'无 --confirm/--force/--dry-run'")
        if "> os.remove(p)" not in out:
            fail("定位段落应含 ±2 行上下文引用")
        ok("L-1 定位：文件:行 + 关键词 + 上下文段落齐备，exit 0（信息供给）")

        # 4. 代码文件有防护 → 标注"已有防护 --confirm"
        skill_f = make_skill(tdp / "b", with_hit=False)
        (skill_f / "scripts" / "wipe.py").write_text(
            "# wipe 临时缓存（--dry-run 默认）\nos.system(f'rm -rf {p} --dry-run')\n",
            encoding="utf-8")
        p = run(str(skill_f))
        if p.returncode != 0 or "已有防护 --dry-run" not in p.stdout:
            fail(f"防护旗标在场应标注'已有防护'，实为:\n{p.stdout[-500:]}")
        ok("L-2 防护标注：--dry-run 在场 → '已有防护'（仅标注不判定）")

        # 5. 零命中 → "定位段落为空"声明
        skill_z = make_skill(tdp / "c", with_hit=False)
        p = run(str(skill_z))
        if p.returncode != 0 or "定位段落为空" not in p.stdout:
            fail(f"零命中应输出'定位段落为空'声明，实为:\n{p.stdout[-400:]}")
        ok("L-3 零命中声明（W-08 降级句触发口径）")

        # 6. --out 落盘
        rep = tdp / "rep" / "kw.md"
        p = run(str(skill), "--out", str(rep))
        if p.returncode != 0 or not rep.is_file() \
                or "B3-1 关键词定位报告" not in rep.read_text(encoding="utf-8"):
            fail("--out 报告未落盘或内容缺失")
        ok("--out 报告落盘")

    # 7. 纪律源码断言：VERSION/_BlockArgParser/词表复用/二进制跳过
    src = KL.read_text(encoding="utf-8")
    if 'VERSION = "v' not in src:
        fail("kw_locator.py 缺 VERSION 常量（软断言防版本升位误报）")
    if "class _BlockArgParser" not in src:
        fail("kw_locator.py 应内嵌 _BlockArgParser")
    if "from security_scan import DESTRUCTIVE_WORD_RE, PROTECTION_FLAGS" not in src:
        fail("kw_locator.py 应复用 security_scan V8-5 词表（单一来源，禁复制）")
    if "UnicodeDecodeError" not in src:
        fail("kw_locator.py 应跳过不可解码文件（二进制防护）")
    ok("纪律固化：VERSION + _BlockArgParser + 词表单一来源 + 二进制跳过")

    print(f"\nALL PASS ({_ok_n} 组断言)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
