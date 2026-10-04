#!/usr/bin/env python3
"""test_regression.py — tools 固化回归单测（豁免口径补偿控制）。

汇总六轮评审（2026-10-02）的修复结论为可执行断言；2026-10-03 收官回填批次
起对齐工具族 fail()/ok() 惯例（fail-fast、消息明确、python -O 下不假阳性），
并固化收官回填（VERSION 常量 ×3 / _BlockArgParser 全员覆盖 / --lines 校验）。
只读 + 临时目录夹具，无系统副作用。

用法: python tests/test_regression.py    # 全过打印 ALL PASS，失败非零退出
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parent.parent
passed: list[str] = []


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hc = load("host_compat_under_test", TOOLS / "host_compat.py")
sr = load("smoke_runner_under_test", TOOLS / "smoke_runner.py")


def ok(msg: str) -> None:
    passed.append(msg)
    print(f"  PASS {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")
    sys.exit(1)


# ── host_compat：HOSTS 表驱动（第三/四轮 2.1/2.2）──
def test_host_homes_table_driven():
    for name, homes in [("DeepSeek Harness", [".dsh", ".deepseek"]),
                        ("智谱 ZCode", [".zcode", ".zai", ".zhipu", ".glm"]),
                        ("豆包/TRAE", [".trae", ".doubao"])]:
        if hc.host_homes(name) != homes:
            fail(f"host_homes({name}) 应为 {homes}，实为 {hc.host_homes(name)}")
        guessed = {str(p) for lb, p, _ in hc.skill_dirs_for(name) if "推测" in lb}
        want = {str(Path.home() / d / "skills") for d in homes}
        if guessed != want:
            fail(f"{name} 推测技能库应为 {want}，实为 {guessed}")
    if hc.host_homes("MyCustomHost") != [".mycustomhost"]:
        fail("未知宿主名字应兜底为 ['.<lower>'] 形态")
    ok("host_homes/skill_dirs_for 由 HOSTS 表驱动 + 自定义宿主兜底")


def test_dedupe():
    paths = [os.path.normcase(str(p)) for _, p, _ in hc.skill_dirs_for("WorkBuddy")]
    wb = os.path.normcase(str(Path.home() / ".workbuddy" / "skills"))
    if paths.count(wb) != 1:
        fail(f"WorkBuddy 目录应恰好出现一次（去重），实为 {paths.count(wb)} 次")
    if "os.path.normcase" not in (TOOLS / "host_compat.py").read_text(encoding="utf-8"):
        fail("host_compat 应以 normcase 去重（第五/六轮 2.2/2.5 固化）")
    ok("技能库候选按 normcase 去重（第五/六轮 2.2/2.5）")


def test_cursor():
    if [d for h in hc.HOSTS for d in h["home"]].count(".cursor") != 0:
        fail("~/.cursor 不得入 HOSTS home（会劫持 detect_host）")
    cands = [str(p) for _, p, _ in hc.skill_dirs_for("Cursor")]
    if str(Path.home() / ".cursor" / "skills") not in cands:
        fail("--host Cursor 应报告预期路径 ~/.cursor/skills")
    orig = Path.home
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td)
        fake.joinpath(".cursor", "skills").mkdir(parents=True)
        Path.home = classmethod(lambda cls: fake)  # type: ignore[method-assign]
        try:
            host = hc.detect_host(None)
            if not any(".cursor" in str(p) for _, p, _ in hc.skill_dirs_for(host)):
                fail("env 未识别时目录探测应命中 .cursor")
            if not any(p.is_dir() for _, p, _ in hc.skill_dirs_for(host)):
                fail("目录探测应返回存在的目录")
        finally:
            Path.home = orig  # type: ignore[assignment]
    ok("Cursor：显式 --host 报告路径 + env 未识别时目录探测仍生效（第六轮 2.1）")


def test_agent_cli_symlink_dedupe():
    real = shutil.which
    shutil.which = lambda c: "C:/fake/bin/zcode.exe" if c in ("zcode", "zhipu") else None  # type: ignore[assignment]
    try:
        _, _, found = hc.check_agent_clis()
        if found != ["zcode"]:
            fail(f"agent CLI 软链别名应按 resolve 去重为 ['zcode']，实为 {found}")
    finally:
        shutil.which = real  # type: ignore[assignment]
    ok("agent CLI 软链别名按 resolve 去重（第四轮 2.3）")


# ── host_compat：frontmatter 体检（第五/六轮 2.2/2.6）──
def test_frontmatter_checks():
    with tempfile.TemporaryDirectory() as td:
        cases = {"nofm": ("# 正文", "无 YAML frontmatter"),
                 "empty": ("---\n---\n正文", "frontmatter 块为空"),
                 "misskey": ("---\nname: x\n---\n正文", "缺 name/description")}
        for dname, (content, want) in cases.items():
            d = Path(td) / dname
            d.mkdir()
            (d / "SKILL.md").write_text(content, encoding="utf-8")
            lvl, msg = hc.check_skill_dir_arg(str(d))
            if lvl != "FAIL" or want not in msg:
                fail(f"夹具 {dname} 应 FAIL 且含'{want}'，实为 {lvl}: {msg}")
        bom = Path(td) / "bom"
        bom.mkdir()
        (bom / "SKILL.md").write_bytes(
            "﻿---\nname: x\ndescription: y\n---\n正文".encode("utf-8"))
        if hc.check_skill_dir_arg(str(bom))[0] != "PASS":
            fail("BOM 应被 utf-8-sig 剥除")
        locked = Path(td) / "locked"
        locked.mkdir()
        (locked / "SKILL.md").write_text("---\nname: x\ndescription: y\n---\n", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=OSError("denied")):
            lvl, msg = hc.check_skill_dir_arg(str(locked))
        if lvl != "FAIL" or "读取失败" not in msg:
            fail("OSError 应兜底为 FAIL 而非崩溃")
    ok("frontmatter 三分报错 + BOM 剥除 + OSError 兜底")


# ── host_compat：B 路径待确认（第五轮 2.2）──
def test_b_path_ambiguity():
    orig = Path.home
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td)
        fake.joinpath(".claude", "skills").mkdir(parents=True)
        Path.home = classmethod(lambda cls: fake)  # type: ignore[method-assign]
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                hc.main()
        finally:
            Path.home = orig  # type: ignore[assignment]
        text = buf.getvalue()
        if "待确认" not in text or "改走 C" not in text:
            fail("通用终端 + 残留技能库场景应有'待确认'+'改走 C'提示")
    ok("通用终端 + 残留技能库 → B（待确认）+ 改走 C 条件")


# ── smoke_runner：C4 只认参数定义形态（第三/四轮 2.3/2.4）──
def test_c4():
    import re
    cases = [("import argparse\nap.add_argument('--dry-run', action='store_true')\n", True),
             ("import click\n@click.option('--dry-run', is_flag=True)\ndef g(): pass\n", True),
             ("print('使用 --dry-run')\nx = '--dry-run'\n", False),
             ("import argparse\nap.add_argument('--verbose')\n", False)]
    with tempfile.TemporaryDirectory() as td:
        for i, (code, want) in enumerate(cases):
            p = Path(td) / f"c{i}.py"
            p.write_text(code, encoding="utf-8")
            rows = sr.smoke_one(p, 10)
            c4 = next(r for r in rows if r["cid"].startswith("C4"))
            if ("含 dry-run 标志" in c4["ev"]) != want:
                fail(f"C4 用例 {i} 应{'命中' if want else '不命中'}，实为 {c4['ev']}")
    ok("C4 认 argparse/click 定义形态，不认裸字面量")


# ── smoke_runner：C2 用法提示不含 error 系（第一轮 P-6）──
def test_usage_hints():
    joined = " ".join(sr.USAGE_HINTS).lower()
    if "error" in joined:
        fail("USAGE_HINTS 不得含 error 系（崩溃栈会误判 PASS）")
    if "usage" not in joined or "用法" not in joined:
        fail("USAGE_HINTS 应含 usage/用法关键词")
    ok("USAGE_HINTS 仅含用法/必需类关键词")


# ── 收官回填批次固化（2026-10-03 全量盘点评审处置）──
def test_family_backfill():
    # VERSION 常量：host_compat/smoke_runner/check_skill 三成员补齐（盘点缺口原为 3 个）
    if not hasattr(hc, "VERSION") or not hc.VERSION.startswith("v"):
        fail("host_compat 应有 VERSION 常量（v1.0 收官回填）")
    if not hasattr(sr, "VERSION") or not sr.VERSION.startswith("v"):
        fail("smoke_runner 应有 VERSION 常量（v1.1 收官回填）")
    cs_src = (TOOLS / "check_skill.py").read_text(encoding="utf-8")
    ss_src = (TOOLS / "security_scan.py").read_text(encoding="utf-8")
    if 'VERSION = "v' not in cs_src:
        fail("check_skill 应有 VERSION 常量（v1.1.3 收官回填引入；软断言防版本升位误报）")
    # _BlockArgParser 全员覆盖：最后 2 个成员（host_compat/security_scan）回填
    if "class _BlockArgParser" not in (TOOLS / "host_compat.py").read_text(encoding="utf-8"):
        fail("host_compat 应回填 _BlockArgParser")
    if "class _BlockArgParser" not in ss_src:
        fail("security_scan 应回填 _BlockArgParser")
    # check_skill --lines 正整数校验的行为断言归 test_check_skill（子进程实测），此处不重复
    ok("收官回填固化：VERSION ×3 + _BlockArgParser 全员覆盖")


def main() -> int:
    for fn in [test_host_homes_table_driven, test_dedupe, test_cursor,
               test_agent_cli_symlink_dedupe, test_frontmatter_checks,
               test_b_path_ambiguity, test_c4, test_usage_hints,
               test_family_backfill]:
        print(f"[{fn.__name__}]")
        fn()
    print(f"\nALL PASS（{len(passed)} 组断言）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
