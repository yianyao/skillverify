#!/usr/bin/env python3
"""test_naming_precheck.py — naming_precheck.py 固化回归单测（V2 命名冲突预检器）。

以临时夹具固化开发期实测结论：合规全 PASS、同名三类响亮 FAIL（frontmatter 名/
目录名/大小写变体）、余弦与 Jaccard 告警、阈值可调、覆盖不全不假 PASS、
设计期 --name/--description 模式、退出码 0/1/2 工具族约定。
任何 naming_precheck.py 改动后必须先过本文件。
只读 + 临时目录夹具，无系统副作用。

用法: python tests/test_naming_precheck.py    # 全过打印 ALL PASS，失败非零退出
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


np = load("naming_precheck_under_test", TOOLS / "naming_precheck.py")


def ok(msg: str) -> None:
    passed.append(msg)
    print(f"  PASS {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")
    sys.exit(1)


def make_skill(root: Path, name: str, fm: str = "", body: str = "\n# t\n") -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {fm}---\n{body}"
                                if fm else f"---\nname: {name}\ndescription: t\n---\n{body}",
                                encoding="utf-8", newline="\n")
    return d


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="np-test-"))
    try:
        # 0. 分词口径单测（docstring 声明的启发式口径固化）
        toks = np.tokenize("使用 OAuth2 API，并处理用户 user_data")
        if "oauth2" not in toks or "user" not in toks or "data" not in toks:
            fail(f"ASCII 词元缺失: {toks}")
        if "使用" not in toks or "用户" not in toks:
            fail(f"CJK 二字元缺失: {toks}")
        if np.tokenize("字") != ["字"]:
            fail(f"孤立单字应保留: {np.tokenize('字')}")
        # 跨段 bigram 口径（v1.0.1 评审 2）：CJK 抽取序列相邻——中间非 CJK 字符被
        # 丢弃，跨段伪 bigram（"审的"）系有意行为，此处固化防无声变更
        cross = np.tokenize("评审 Agent Skill 的")
        if "审的" not in cross or "评审" not in cross:
            fail(f"跨段 bigram 口径与 docstring 不符: {cross}")
        ok("分词口径：ASCII 词元 + CJK 二字元 + 孤立单字 + 跨段抽取口径固化")

        lib = tmp / "lib"
        lib.mkdir()
        make_skill(lib, "alpha-review",
                   "评审 Agent Skill 的 LLM 语义评审流程，双评留痕与人工裁决\n")
        make_skill(lib, "beta-report",
                   "生成周报归档索引，整理团队周报摘要\n")
        # 不可解析条目（覆盖缺口夹具，测试 8 用）
        broken = lib / "broken-skill"
        broken.mkdir()
        (broken / "SKILL.md").write_text("---\nno-name-here: x\n---\n", encoding="utf-8")
        clean_lib = tmp / "clean-lib"
        clean_lib.mkdir()
        make_skill(clean_lib, "alpha-review",
                   "评审 Agent Skill 的 LLM 语义评审流程，双评留痕与人工裁决\n")
        make_skill(clean_lib, "beta-report",
                   "生成周报归档索引，整理团队周报摘要\n")

        # 1. 合规（干净库）：不同名、低相似 → 全 PASS exit 0
        rows, st = np.precheck("gamma-tools", "批量重命名图片文件的工具", [clean_lib], None, 0.85, 0.6)
        lv = {r["vid"]: r["level"] for r in rows}
        for vid in ("V2-1", "V2-2", "V2-3"):
            if lv[vid] != "PASS":
                fail(f"合规夹具 {vid} 应 PASS，实为 {lv[vid]}: {[r for r in rows if r['vid']==vid][0]['ev']}")
        if lv["COV"] != "INFO" or st["comparable"] != 2 or st["unparsed"] != 0:
            fail(f"COV 应 INFO 且 comparable=2/unparsed=0，实为 {lv['COV']} {st}")
        ok("合规夹具 V2-1~V2-3 全 PASS + 覆盖行 INFO")

        # 2. 同名 name（frontmatter）→ FAIL（同名+同目录时证据路径去重——v1.0.1 评审 6）
        rows, _ = np.precheck("alpha-review", "另一个评审工具", [lib], None, 0.85, 0.6)
        if rows[0]["level"] != "FAIL" or "alpha-review" not in rows[0]["ev"]:
            fail(f"同名应 FAIL 且证据含技能名: {rows[0]['level']} {rows[0]['ev']}")
        dup_path = str(lib / "alpha-review")
        if rows[0]["ev"].count(dup_path) != 1:
            fail(f"同名+同目录时证据路径应去重（出现 1 次），实为 {rows[0]['ev'].count(dup_path)}: {rows[0]['ev']}")
        ok("V2-1 同名 name（frontmatter）→ FAIL + 同名/同目录证据去重")

        # 3. 目录名冲突（库内有同名目录但 name 不可解析）→ FAIL
        rows, _ = np.precheck("broken-skill", "无关描述", [lib], None, 0.85, 0.6)
        if rows[0]["level"] != "FAIL" or "broken-skill" not in rows[0]["ev"]:
            fail(f"目录撞名应 FAIL: {rows[0]['level']} {rows[0]['ev']}")
        ok("V2-1 目录名冲突（占位路径已被占）→ FAIL")

        # 4. 大小写变体同名 → FAIL（name 规范为小写，比对大小写不敏感）
        rows, _ = np.precheck("Alpha-Review", "无关描述", [lib], None, 0.85, 0.6)
        if rows[0]["level"] != "FAIL":
            fail(f"大小写变体应 FAIL，实为 {rows[0]['level']}")
        ok("V2-1 大小写变体同名 → FAIL")

        # 5. 高余弦告警 → WARN（目标与 alpha-review 描述高度相似）
        rows, _ = np.precheck("gamma-review",
                              "评审 Agent Skill 的 LLM 语义评审流程，双评留痕与人工裁决",
                              [clean_lib], None, 0.85, 0.6)
        v2 = rows[1]
        if v2["level"] != "WARN" or "alpha-review" not in v2["ev"]:
            fail(f"高余弦应 WARN 且指向 alpha-review: {v2['level']} {v2['ev']}")
        # 5b. 阈值可调：阈值调到 1.0 后同一对不再告警
        rows2, _ = np.precheck("gamma-review",
                               "评审 Agent Skill 的 LLM 语义评审流程，双评留痕与人工裁决",
                               [clean_lib], None, 1.0, 0.6)
        if rows2[1]["level"] != "PASS":
            fail(f"cos-threshold=1.0 时应 PASS，实为 {rows2[1]['level']}")
        ok("V2-2 余弦告警 WARN + 阈值可调回落 PASS")

        # 6. 高 Jaccard → V2-3 WARN（目标 = beta 描述 + 尾部扩写，近超集构造）
        rows, _ = np.precheck("delta-report",
                              "生成周报归档索引，整理团队周报摘要工具集",
                              [clean_lib], None, 0.99, 0.6)
        v3 = rows[2]
        if v3["level"] != "WARN" or "beta-report" not in v3["ev"]:
            fail(f"高 Jaccard 应 WARN 且指向 beta-report: {v3['level']} {v3['ev']}")
        ok("V2-3 关键词重叠(Jaccard) 告警 WARN")

        # 7. 目标无 description → 相似度行 WARN 不假 PASS
        rows, _ = np.precheck("no-desc-skill", "", [lib], None, 0.85, 0.6)
        for vid in ("V2-2", "V2-3"):
            if {r["vid"]: r for r in rows}[vid]["level"] != "WARN":
                fail(f"无 description 时 {vid} 应 WARN 不假 PASS")
        ok("覆盖不全纪律：无 description → V2-2/V2-3 WARN")

        # 8. 库含不可解析条目 → 相似度行降 WARN + COV WARN；
        #    V2-1 保持 PASS（目录名检索不依赖解析——name 必须与目录名一致）
        rows, _ = np.precheck("gamma-tools", "批量重命名图片文件的工具", [lib], None, 0.85, 0.6)
        lv = {r["vid"]: r["level"] for r in rows}
        if lv["COV"] != "WARN":
            fail(f"覆盖缺口时 COV 应 WARN，实为 {lv['COV']}")
        for vid in ("V2-2", "V2-3"):
            if lv[vid] != "WARN":
                fail(f"覆盖缺口时 {vid} 应 WARN 不假 PASS，实为 {lv[vid]}")
        if lv["V2-1"] != "PASS":
            fail(f"目录名检索不受解析缺口影响，V2-1 应 PASS，实为 {lv['V2-1']}: "
                 f"{[r for r in rows if r['vid']=='V2-1'][0]['ev']}")
        ok("覆盖不全纪律：解析缺口 → 相似度行 WARN、V2-1 目录检索保持 PASS")

        # 9. 目标在库内：自排除（自比相似度恒 1.0 不得自命中；同名/自比均不得误报）
        own = make_skill(tmp, "self-skill", "批量压缩图片并转换格式的独立工具\n")
        rows, _ = np.precheck("self-skill",
                              "批量压缩图片并转换格式的独立工具",
                              [clean_lib, tmp], own, 0.85, 0.6)
        lv = {r["vid"]: r["level"] for r in rows}
        if lv["V2-1"] != "PASS":
            fail(f"自排除失效：自身目录被当冲突 {lv['V2-1']}: {[r for r in rows if r['vid']=='V2-1'][0]['ev']}")
        if lv["V2-2"] != "PASS":
            fail(f"自排除失效：自比相似度命中 {lv['V2-2']}: {[r for r in rows if r['vid']=='V2-2'][0]['ev']}")
        ok("自排除：库内目标目录不与自身比较")

        # 10. 目录模式（SKILL.md 取 name/description）+ 库不存在计缺口
        rows, st = np.precheck("self-skill",
                               "评审 Agent Skill 的 LLM 语义评审流程，双评留痕与人工裁决",
                               [lib, tmp / "nope"], own, 0.85, 0.6)
        lv = {r["vid"]: r["level"] for r in rows}
        if lv["COV"] != "WARN" or st["lib_missing"] != 1:
            fail(f"不可达库应计缺口: COV={lv['COV']} lib_missing={st['lib_missing']}")
        ok("目录模式取值 + 不可达库计覆盖缺口 WARN")

        # 11. 退出码 0/1/2 与 --out 落盘（子进程级验证）
        def run_exit(*args: str) -> int:
            return subprocess.run(
                [sys.executable, str(TOOLS / "naming_precheck.py"), *args],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30, stdin=subprocess.DEVNULL).returncode

        lib_arg = ["--library", str(clean_lib)]
        if run_exit("--name", "gamma-tools", "--description", "批量重命名图片文件", *lib_arg) != 0:
            fail("合规退出码应为 0")
        if run_exit("--name", "alpha-review", "--description", "x", *lib_arg) != 1:
            fail("同名 FAIL 退出码应为 1")
        out_path = tmp / "report" / "naming.md"
        if run_exit("--name", "gamma-review", "--description",
                    "评审 Agent Skill 的 LLM 语义评审流程，双评留痕与人工裁决", *lib_arg,
                    "--out", str(out_path)) != 2:
            fail("仅 WARN 退出码应为 2")
        if not out_path.is_file() or "V2 命名冲突预检报告" not in out_path.read_text(encoding="utf-8"):
            fail("--out 报告未落盘或内容缺失")
        # 缺 --library：自查返回 1（FAIL 阻断码），不得用 argparse 的 SystemExit(2)
        # 撞 WARN 码——v1.0.1 评审 5
        if run_exit("--name", "x") != 1:
            fail("缺 --library 应返回 1（阻断码），不得撞 WARN 码 2")
        # name 格式预检（v1.0.1 评审 3）：越界路径形态 → 1，不得构造越界路径
        if run_exit("--name", "../etc", "--library", str(clean_lib)) != 1:
            fail("name 含路径穿越形态应返回 1")
        if run_exit("--name", "a/b", "--library", str(clean_lib)) != 1:
            fail("name 含路径分隔符应返回 1")
        # argparse 类型转换错误（v1.0.3 随 token_budget 评审扩撞码覆盖）：error() 覆写统一 1
        if run_exit("--name", "x", "--library", str(clean_lib), "--cos-threshold", "abc") != 1:
            fail("--cos-threshold abc 应经 error() 覆写返回 1，不得 argparse 默认 exit 2")
        ok("退出码 0/1/2 约定 + --out 报告落盘 + 全部参数错误（缺参/name 非法/类型错误）返回 1 阻断码")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nALL PASS ({len(passed)} 组断言)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
