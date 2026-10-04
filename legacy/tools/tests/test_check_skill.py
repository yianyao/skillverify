#!/usr/bin/env python3
"""test_check_skill.py — check_skill.py 固化回归单测。

以临时夹具固化实弹验证结论：真实技能全绿 + 六类缺陷全部响亮 FAIL，
外加 v1.1 外部评审修订的六个回归点（S-1/S-4/P-1/P-2/P-3/退出码语义）。
任何 check_skill.py 改动后必须先过本文件。
只读 + 临时目录夹具，无系统副作用。

用法: python tests/test_check_skill.py    # 全过打印 ALL PASS，失败非零退出
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


cs = load("check_skill_under_test", TOOLS / "check_skill.py")


def ok(msg: str) -> None:
    passed.append(msg)
    print(f"  PASS {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")
    sys.exit(1)


def make_skill(root: Path, name: str, fm: str, body: str = "\n# t\n",
               scripts: dict[str, str] | None = None,
               raw: bytes | None = None) -> Path:
    d = root / name
    d.mkdir(parents=True)
    if raw is not None:
        (d / "SKILL.md").write_bytes(raw)
    else:
        (d / "SKILL.md").write_text(f"---\n{fm}---\n{body}", encoding="utf-8", newline="\n")
    for fn, src in (scripts or {}).items():
        sd = d / "scripts"
        sd.mkdir(exist_ok=True)
        (sd / fn).write_text(src, encoding="utf-8", newline="\n")
    return d


def levels(rows: list[dict]) -> dict[str, str]:
    return {r["aid"]: r["level"] for r in rows}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ck-test-"))
    try:
        good = make_skill(tmp, "good-skill",
                          "name: good-skill\ndescription: 一个合规技能\ncompatibility: 需要 Python 3.10+\n",
                          body="\n见 references/g.md 与 scripts/a.py\n",
                          scripts={"a.py": "print('x')\n"})
        (good / "references").mkdir()
        (good / "references" / "g.md").write_text("doc\n", encoding="utf-8")

        rows = {r["aid"]: r for r in cs.check(good, 300)}
        for aid in ("A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11"):
            if rows[aid]["level"] != "PASS":
                fail(f"合规夹具 {aid} 应 PASS，实为 {rows[aid]['level']}: {rows[aid]['ev']}")
        ok("合规夹具 A2–A11 全 PASS")

        # A3 name 不合规
        lv = levels(cs.check(make_skill(tmp, "bad-name",
                       "name: Bad_Name\ndescription: x\n"), 300))
        (ok if lv["A3"] == "FAIL" else fail)(f"A3 name 不合规 → FAIL（实为 {lv['A3']}）")

        # A7 CRLF
        d = tmp / "crlf-skill"
        d.mkdir()
        (d / "SKILL.md").write_bytes(b"---\nname: crlf-skill\ndescription: x\r\n---\r\n\r\n# t\r\n")
        lv = levels(cs.check(d, 300))
        (ok if lv["A7"] == "FAIL" else fail)(f"A7 CRLF → FAIL（实为 {lv['A7']}）")

        # A7 孤立 \r（v1.1 P-1 回归：旧实现只检 b"\r\n" 会漏报）
        d = tmp / "cr-only-skill"
        d.mkdir()
        (d / "SKILL.md").write_bytes(b"---\nname: cr-only-skill\ndescription: x\n---\n# t\rok\n")
        lv = levels(cs.check(d, 300))
        (ok if lv["A7"] == "FAIL" else fail)(f"A7 孤立 \\r → FAIL（实为 {lv['A7']}）")

        # A8 绝对路径引用
        lv = levels(cs.check(make_skill(tmp, "absref-skill",
                       "name: absref-skill\ndescription: x\n",
                       body="\n见 C:/tools/x.py\n"), 300))
        (ok if lv["A8"] == "FAIL" else fail)(f"A8 绝对路径 → FAIL（实为 {lv['A8']}）")

        # A8 URL 片段不误报（v1.1 P-2 回归：https://.../scripts/foo 不算相对引用）
        lv = levels(cs.check(make_skill(tmp, "url-skill",
                       "name: url-skill\ndescription: x\n",
                       body="\n参见 https://example.com/docs/scripts/foo\n"), 300))
        (ok if lv["A8"] == "PASS" else fail)(f"A8 URL 片段 → PASS 不误报（实为 {lv['A8']}: "
                                             f"{dict((r['aid'], r['ev']) for r in cs.check(tmp / 'url-skill', 300))['A8']}）")

        # A9 交互式输入（连带 A10 退出码非零）
        lv = levels(cs.check(make_skill(tmp, "interactive-skill",
                       "name: interactive-skill\ndescription: x\n",
                       scripts={"i.py": "n = input('n=')\n"}), 300))
        (ok if lv["A9"] == "FAIL" else fail)(f"A9 交互输入 → FAIL（实为 {lv['A9']}）")
        (ok if lv["A10"] == "FAIL" else fail)(f"A10 坏脚本 --help → FAIL（实为 {lv['A10']}）")

        # A11 坏 frontmatter（连带 A3/A4）
        d = tmp / "badfm-skill"
        d.mkdir()
        (d / "SKILL.md").write_text("name: [broken\n bad ::: \n---\n\n# t\n", encoding="utf-8")
        lv = levels(cs.check(d, 300))
        (ok if lv["A11"] == "FAIL" else fail)(f"A11 坏 frontmatter → FAIL（实为 {lv['A11']}）")
        (ok if lv["A3"] == "FAIL" and lv["A4"] == "FAIL" else fail)("A11 失败时 A3/A4 连带 FAIL")

        # A11 多行 YAML 值不误报（v1.1 P-3 回归：缩进续行不再记"无冒号"）
        lv = levels(cs.check(make_skill(tmp, "ml-skill",
                       "name: ml-skill\ndescription: |\n  第一行\n  第二行\n"), 300))
        (ok if lv["A11"] == "PASS" else fail)(f"A11 多行 YAML 值 → PASS（实为 {lv['A11']}）")

        # A6 超 --lines 上限
        lv = levels(cs.check(make_skill(tmp, "overlines-skill",
                       "name: overlines-skill\ndescription: x\n",
                       body="\n" + "\n".join(f"line {i}" for i in range(90)) + "\n"), 50))
        (ok if lv["A6"] == "FAIL" else fail)(f"A6 超 --lines 上限 → FAIL（实为 {lv['A6']}）")

        # A6 行数口径（v1.1 S-1 回归）：总计 49 个显示行 + 末尾换行，limit=50（预警线=40）。
        # 旧实现 split("\n") 多计末尾空行 → 50 行 → 判 FAIL；新实现 splitlines → 49 → WARN，
        # 且证据串必须是"49 行"。level 与证据双重断言，严格区分新旧口径。
        d = make_skill(tmp, "boundary-skill",
                       "name: boundary-skill\ndescription: x\n",
                       body="\n" + "\n".join(f"line {i}" for i in range(44)) + "\n")
        r6 = {r["aid"]: r for r in cs.check(d, 50)}["A6"]
        (ok if r6["level"] == "WARN" and "49 行" in r6["ev"] else fail)(
            f"A6 末尾换行不多计（49 行/limit 50）→ WARN 且证据 49 行（实为 {r6['level']}: {r6['ev']}）")

        # A6 预警线（v1.1 S-4 回归）：limit=50 → 80% 预警线=40，45 行应 WARN 而非静默 PASS
        lv = levels(cs.check(make_skill(tmp, "warnline-skill",
                       "name: warnline-skill\ndescription: x\n",
                       body="\n" + "\n".join(f"line {i}" for i in range(41)) + "\n"), 50))
        (ok if lv["A6"] == "WARN" else fail)(f"A6 达 80% 预警线（41 行/limit 50）→ WARN（实为 {lv['A6']}）")

        # 退出码语义（v1.1 S-2 回归）：合规技能无 FAIL/WARN 时应 exit 0（A1 SKIP 不计警告）
        p = subprocess.run([sys.executable, str(TOOLS / "check_skill.py"), str(good)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60, stdin=subprocess.DEVNULL)
        (ok if p.returncode == 0 else fail)(
            f"合规技能整体退出码 → 0（实为 {p.returncode}；A1 SKIP 不计警告）")

        # X2 合法 JSON 但根非对象（v1.1b 2.2 回归：旧实现 data.get 会抛 AttributeError）
        d = make_skill(tmp, "x2root-skill", "name: x2root-skill\ndescription: x\n")
        (d / "evals").mkdir()
        (d / "evals" / "evals.json").write_text("[1, 2, 3]", encoding="utf-8")
        rows = {r["aid"]: r for r in cs.check(d, 300)}
        x2 = rows["X2"]
        (ok if x2["level"] == "WARN" and "根类型" in x2["ev"] else fail)(
            f"X2 根非对象 → WARN 不崩溃（实为 {x2['level']}: {x2['ev']}）")

        # A9 读取失败 → WARN 不假 PASS（v1.1c 2.1 回归：目录形 .py 夹具跨平台稳定触发 OSError）
        d = tmp / "a9readerr-skill"
        (d / "scripts").mkdir(parents=True)
        (d / "scripts" / "locked.py").mkdir()  # 目录伪装脚本 → read_text 必抛 OSError
        (d / "SKILL.md").write_bytes(b"---\nname: a9readerr-skill\ndescription: x\n---\n# t\n")
        r9 = {r["aid"]: r for r in cs.check(d, 300)}["A9"]
        (ok if r9["level"] == "WARN" and "未检查到" in r9["ev"] else fail)(
            f"A9 读取失败 → WARN 不假 PASS（实为 {r9['level']}: {r9['ev']}）")

        # BOM 开头 → A11 仍 PASS、X1 单独 WARN（v1.1d 2.1 回归：旧实现 A11 误报"区块缺失"）
        d = tmp / "bom-skill"
        d.mkdir()
        (d / "SKILL.md").write_bytes(b"\xef\xbb\xbf---\nname: bom-skill\ndescription: x\n---\n# t\n")
        rows = {r["aid"]: r for r in cs.check(d, 300)}
        (ok if rows["A11"]["level"] == "PASS" else fail)(
            f"BOM 开头 A11 → PASS 不误判（实为 {rows['A11']['level']}: {rows['A11']['ev']}）")
        (ok if rows["X1"]["level"] == "WARN" else fail)(
            f"BOM 开头 X1 → WARN 专职报警（实为 {rows['X1']['level']}）")

        # A8 file:// 片段不误报（v1.1d 2.2 回归：file:///.../references/g.md 不算相对引用）
        lv = levels(cs.check(make_skill(tmp, "fileurl-skill",
                       "name: fileurl-skill\ndescription: x\n",
                       body="\n参见 file:///home/x/references/g.md\n"), 300))
        r8 = {r["aid"]: r for r in cs.check(tmp / "fileurl-skill", 300)}["A8"]
        (ok if lv["A8"] == "PASS" and "无引用" in r8["ev"] else fail)(
            f"A8 file:// 片段 → PASS 且无引用（实为 {lv['A8']}: {r8['ev']}）")

        # A1 探测优先序（v1.1.2 评审 1 回归）：官方入口名 agentskills 优先——
        # npm 第三方占用包 bin 名恰为 skills-ref，两 CLI 并存时不得命中第三方
        fake = lambda name: f"C:\\fake\\{name}.exe"  # noqa: E731  两名均"在场"
        got = cs.find_official_cli(fake)
        (ok if got == "C:\\fake\\agentskills.exe" else fail)(
            f"find_official_cli 并存环境取 agentskills（实为 {got}）")
        only_alias = lambda name: f"C:\\fake\\{name}.exe" if name == "skills-ref" else None  # noqa: E731
        got2 = cs.find_official_cli(only_alias)
        (ok if got2 == "C:\\fake\\skills-ref.exe" else fail)(
            f"find_official_cli 仅别名在场时兜底 skills-ref（实为 {got2}）")
        (ok if cs.find_official_cli(lambda name: None) is None else fail)(
            "find_official_cli 双缺 → None（SKIP 路径不变）")

        # 参数错误统一 exit 1（v1.1.2 评审 2 回填）：--lines abc 不再撞 argparse 默认 exit 2
        p2 = subprocess.run([sys.executable, str(TOOLS / "check_skill.py"),
                             str(good), "--lines", "abc"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=60, stdin=subprocess.DEVNULL)
        (ok if p2.returncode == 1 and "用法" in (p2.stderr or "") else fail)(
            f"--lines abc → exit 1 带用法提示（实为 {p2.returncode}；C2 契约）")

        # --lines 正整数校验（v1.1.3 收官回填）：--lines 0 原使 A6 无条件 FAIL，现 fail-fast
        p3 = subprocess.run([sys.executable, str(TOOLS / "check_skill.py"),
                             str(good), "--lines", "0"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=60, stdin=subprocess.DEVNULL)
        (ok if p3.returncode == 1 and "正整数" in (p3.stderr or "") else fail)(
            f"--lines 0 → exit 1 带正整数提示（实为 {p3.returncode}）")
        (ok if 'VERSION = "v' in (TOOLS / "check_skill.py").read_text(encoding="utf-8")
         else fail)("VERSION 常量在场（v1.1.3 收官回填引入，此前仅记 docstring 曾被盘点漏计；软断言防版本升位误报）")

        print(f"\nALL PASS（{len(passed)} 组断言）")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
