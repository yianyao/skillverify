#!/usr/bin/env python3
"""test_dep_check.py — dep_check.py 固化回归单测（§8.1.2/§8.2 依赖检测五项）。

以临时夹具固化建成实测结论：合规全 PASS/SKIP、DEP-1 运行器钉版三态
（代码 FAIL/SKILL.md 文档 WARN/精确钉 PASS/dist-tag 非钉/取值旗标 -r -p 不误取）、
DEP-2 四语言内联声明（PEP 723/Deno npm:/jsr:/Bun 版本化导入统一 classify_pkg_spec
 ranged→DEP-4 WARN/Ruby bundler/inline + 本地模块豁免）、
DEP-3 manifest 判级（FAIL/WARN/夹具 WARN）、DEP-4 说明符与 requires-python
（TOML 单双引号）、DEP-5 清单双向（缺列 FAIL/陈旧 WARN）、
SKILL.md 缺失 → COV WARN + PASS 降级、退出码 0/1/2 + 参数错误统一 1。
任何 dep_check.py 改动后必须先过本文件。
只读 + 临时目录夹具，无系统副作用。

用法: python tests/test_dep_check.py    # 全过打印 ALL PASS，失败非零退出
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


dc = load("dep_check_under_test", TOOLS / "dep_check.py")


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
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: " + name + "\ndescription: 依赖检测夹具技能描述\n---\n# t\n",
        encoding="utf-8", newline="\n")
    return d


def run_exit(*args: str) -> int:
    return subprocess.run(
        [sys.executable, str(TOOLS / "dep_check.py"), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30, stdin=subprocess.DEVNULL).returncode


PEP723_OK = ("# /// script\n"
             "# requires-python = \">=3.10\"\n"
             "# dependencies = [\n"
             "#   \"requests>=2.31\",\n"
             "# ]\n"
             "# ///\n"
             "import json\n"
             "import requests\n"
             "import helper\n")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="dep-test-"))
    try:
        # 0. 合规夹具：PEP 723 完整（specifier+requires-python）+ 本地模块豁免
        #    + SKILL.md 列全脚本 + 运行器全钉版 → 全 PASS exit 0
        sk = make_skill(tmp, "good-skill")
        (sk / "scripts").mkdir()
        (sk / "scripts" / "run_tool.py").write_text(PEP723_OK, encoding="utf-8")
        (sk / "scripts" / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
        (sk / "SKILL.md").write_text(
            "---\nname: good-skill\ndescription: 依赖检测夹具技能描述\n---\n"
            "# t\n运行: `npx some-tool@1.2.3` 或 `uvx other==1.0.0`。\n"
            "脚本: scripts/run_tool.py（主工具）、scripts/helper.py（辅助）。\n",
            encoding="utf-8", newline="\n")
        rows0, _ = dc.dep_check(sk)
        lv = levels(rows0)
        if lv["DEP-1"] != "PASS" or lv["DEP-2"] != "PASS" or lv["DEP-3"] != "PASS" \
                or lv["DEP-4"] != "PASS" or lv["DEP-5"] != "PASS":
            fail(f"合规夹具应全 PASS: {lv}")
        ok("合规夹具：DEP-1~5 全 PASS（PEP 723 完整 + 本地模块豁免 + 清单齐 + 全钉版）")

        # 1. 无 scripts/：DEP-2/4/5 SKIP，DEP-1 文档口径钉版 PASS
        nos = make_skill(tmp, "no-scripts")
        (nos / "SKILL.md").write_text(
            "# t\n用 `npx tool@1.0.0` 调用。\n", encoding="utf-8")
        rows, _ = dc.dep_check(nos)
        lv = levels(rows)
        if lv["DEP-2"] != "SKIP" or lv["DEP-4"] != "SKIP" or lv["DEP-5"] != "SKIP" \
                or lv["DEP-1"] != "PASS":
            fail(f"无 scripts 应 2/4/5 SKIP + 1 PASS: {lv}")
        ok("无 scripts/：DEP-2/4/5 SKIP + DEP-1 仍核 SKILL.md 调用")

        # 2. DEP-2 FAIL：第三方导入无 PEP 723 块
        n7 = make_skill(tmp, "no-pep723")
        (n7 / "scripts").mkdir()
        (n7 / "scripts" / "a.py").write_text("import requests\n", encoding="utf-8")
        (n7 / "SKILL.md").write_text("# t\nscripts/a.py 主脚本。\n", encoding="utf-8")
        rows, _ = dc.dep_check(n7)
        lv = levels(rows)
        r2 = [r for r in rows if r["vid"] == "DEP-2"][0]
        if lv["DEP-2"] != "FAIL" or "requests" not in r2["ev"]:
            fail(f"无 PEP 723 应 FAIL 且含证据: {lv['DEP-2']} {r2['ev']}")
        if lv["DEP-5"] != "PASS":
            fail(f"已列脚本 DEP-5 应 PASS: {lv['DEP-5']}")
        ok("DEP-2：第三方导入无 PEP 723 声明 → FAIL（§8.2.1 [M]）")

        # 3. DEP-4 WARN：PEP 723 裸依赖 + 缺 requires-python
        bare = make_skill(tmp, "bare-dep")
        (bare / "scripts").mkdir()
        (bare / "scripts" / "b.py").write_text(
            "# /// script\n# dependencies = [\n#   \"requests\",\n# ]\n# ///\n"
            "import requests\n", encoding="utf-8")
        (bare / "SKILL.md").write_text("# t\nscripts/b.py 主脚本。\n", encoding="utf-8")
        rows, _ = dc.dep_check(bare)
        lv = levels(rows)
        r4 = [r for r in rows if r["vid"] == "DEP-4"][0]
        if lv["DEP-4"] != "WARN" or "无版本说明符" not in r4["ev"] \
                or "requires-python" not in r4["ev"]:
            fail(f"裸依赖应 WARN 且含两证据: {lv['DEP-4']} {r4['ev']}")
        if lv["DEP-2"] != "PASS":
            fail(f"已声明 DEP-2 应 PASS: {lv['DEP-2']}")
        ok("DEP-4：裸依赖无说明符 + 缺 requires-python → WARN（§8.2.3 [S]）")

        # 4. DEP-2 JS 两态：Deno npm: 带版本 PASS / 裸导入 FAIL / Bun 版本化 PASS
        deno = make_skill(tmp, "deno-ok")
        (deno / "scripts").mkdir()
        (deno / "scripts" / "m.ts").write_text(
            "import { serve } from \"npm:@std/http@1.0.0\";\n"
            "import dayjs from \"dayjs@1.11.10\";\n"
            "import fs from \"node:fs\";\n"
            "import util from \"./local.js\";\n", encoding="utf-8")
        (deno / "SKILL.md").write_text("# t\nscripts/m.ts 主脚本。\n", encoding="utf-8")
        rows, _ = dc.dep_check(deno)
        if levels(rows)["DEP-2"] != "PASS":
            fail(f"Deno 钉版+Bun 版本化应 PASS: {levels(rows)}")
        barejs = make_skill(tmp, "deno-bare")
        (barejs / "scripts").mkdir()
        (barejs / "scripts" / "m.js").write_text(
            "import express from \"express\";\n"
            "const lodash = require(\"lodash\");\n", encoding="utf-8")
        (barejs / "SKILL.md").write_text("# t\nscripts/m.js 主脚本。\n", encoding="utf-8")
        rows, _ = dc.dep_check(barejs)
        r2 = [r for r in rows if r["vid"] == "DEP-2"][0]
        if r2["level"] != "FAIL" or "express" not in r2["ev"] or "lodash" not in r2["ev"]:
            fail(f"JS 裸导入应 FAIL: {r2['level']} {r2['ev']}")
        ok("DEP-2 JS：npm:@ver/Bun pkg@ver PASS；裸导入（express/lodash）FAIL")

        # 5. DEP-2 Ruby 两态 + DEP-4 gem 钉版
        rby = make_skill(tmp, "ruby-ok")
        (rby / "scripts").mkdir()
        (rby / "scripts" / "t.rb").write_text(
            "require \"bundler/inline\"\n"
            "gemfile(true) do\n  gem \"sinatra\", \"4.0.0\"\nend\n", encoding="utf-8")
        (rby / "SKILL.md").write_text("# t\nscripts/t.rb 主脚本。\n", encoding="utf-8")
        rows, _ = dc.dep_check(rby)
        if levels(rows)["DEP-2"] != "PASS" or levels(rows)["DEP-4"] != "PASS":
            fail(f"Ruby inline+钉版应全 PASS: {levels(rows)}")
        rbad = make_skill(tmp, "ruby-bad")
        (rbad / "scripts").mkdir()
        (rbad / "scripts" / "t.rb").write_text(
            "require \"sinatra\"\ngem \"rake\"\n", encoding="utf-8")
        (rbad / "SKILL.md").write_text("# t\nscripts/t.rb 主脚本。\n", encoding="utf-8")
        rows, _ = dc.dep_check(rbad)
        lv = levels(rows)
        r2 = [r for r in rows if r["vid"] == "DEP-2"][0]
        if lv["DEP-2"] != "FAIL" or "sinatra" not in r2["ev"]:
            fail(f"Ruby 无 inline 应 FAIL: {r2['ev']}")
        if lv["DEP-4"] != "WARN" or "rake" not in [r for r in rows if r["vid"] == "DEP-4"][0]["ev"]:
            fail("gem 未钉版本应 DEP-4 WARN（§8.2.5）")
        ok("DEP-2/4 Ruby：bundler/inline+钉版 PASS；裸 require FAIL + gem 未钉 WARN")

        # 6. DEP-3 manifest 判级：根 package.json FAIL / pyproject WARN / references 夹具 WARN
        man = make_skill(tmp, "manifest-skill")
        (man / "package.json").write_text("{\"name\": \"x\"}", encoding="utf-8")
        (man / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
        (man / "references").mkdir()
        (man / "references" / "sample").mkdir()
        (man / "references" / "sample" / "Gemfile").write_text("gem \"x\"\n", encoding="utf-8")
        rows, _ = dc.dep_check(man)
        r3 = [r for r in rows if r["vid"] == "DEP-3"][0]
        if r3["level"] != "FAIL" or "package.json" not in r3["ev"] \
                or "pyproject" not in r3["ev"] or "Gemfile" not in r3["ev"]:
            fail(f"manifest 判级证据不符: {r3['level']} {r3['ev']}")
        ok("DEP-3：根 package.json FAIL（[M]）+ pyproject/夹具 WARN 同行并列人工甄别")

        # 7. DEP-5 双向：缺列 FAIL + 陈旧 WARN
        stale = make_skill(tmp, "stale-list")
        (stale / "scripts").mkdir()
        (stale / "scripts" / "real.py").write_text("import os\n", encoding="utf-8")
        (stale / "SKILL.md").write_text(
            "# t\n脚本清单: scripts/ghost.py（已删）。\n", encoding="utf-8")
        rows, _ = dc.dep_check(stale)
        d5 = [r for r in rows if r["vid"] == "DEP-5"]
        if d5[0]["level"] != "FAIL" or "real.py" not in d5[0]["ev"]:
            fail(f"缺列应 FAIL: {d5[0]['ev']}")
        if len(d5) < 2 or d5[1]["level"] != "WARN" or "ghost.py" not in d5[1]["ev"]:
            fail(f"陈旧清单应 WARN: {[r['level'] for r in d5]}")
        ok("DEP-5：实际文件未列入 → FAIL；SKILL.md 列出不存在的脚本 → WARN")

        # 8. DEP-1 代码 FAIL + 文档 WARN 并存 + 本地 go run 豁免 + ranged WARN
        inst = make_skill(tmp, "runner-mixed")
        (inst / "scripts").mkdir()
        (inst / "scripts" / "inst.sh").write_text(
            "pip install flask\n"
            "npx some-tool\n"
            "uvx ruff==0.6.0\n"
            "go run .\n"
            "go run example.com/tool@v1.2.3\n"
            "deno run --allow-net npm:express@4.18.2\n", encoding="utf-8")
        (inst / "SKILL.md").write_text(
            "# t\nscripts/inst.sh 脚本。文档示例: `npx doc-tool`（未钉版）。\n"
            "版本化: `npx @scope/tool@2.1.0`。\n", encoding="utf-8")
        rows, _ = dc.dep_check(inst)
        r1 = [r for r in rows if r["vid"] == "DEP-1"][0]
        if r1["level"] != "FAIL" or "flask" not in r1["ev"] or "some-tool" not in r1["ev"] \
                or "doc-tool" not in r1["ev"]:
            fail(f"DEP-1 判级/证据不符: {r1['level']} {r1['ev']}")
        ok("DEP-1：代码 unpinned FAIL + 文档 WARN 并行 + go run ./钉版/ranged 口径全命中")

        # 8b. 评审 v1.0.1①④：dist-tag 非钉版 + 取值旗标（-r/-p）不得取值作包名
        tag = make_skill(tmp, "dist-tag")
        (tag / "scripts").mkdir()
        (tag / "scripts" / "t.sh").write_text(
            "npx some-tool@latest\n"
            "pip install -r requirements.txt\n"
            "npx -p some-pkg some-tool@2.0.0\n", encoding="utf-8")
        (tag / "SKILL.md").write_text("# t\nscripts/t.sh 主脚本。\n", encoding="utf-8")
        rows, _ = dc.dep_check(tag)
        lv = levels(rows)
        r1 = [r for r in rows if r["vid"] == "DEP-1"][0]
        if lv["DEP-1"] != "WARN" or "some-tool@latest" not in r1["ev"] \
                or "requirements.txt" in r1["ev"] or "some-pkg" in r1["ev"] \
                or "some-tool@2.0.0" in r1["ev"]:
            fail(f"DEP-1 dist-tag/取值旗标口径不符: {lv['DEP-1']} {r1['ev']}")
        for sp, want in [("tool@latest", "ranged"), ("pkg@next", "ranged"),
                         ("pkg@beta", "ranged"), ("npm:z@latest", "ranged"),
                         ("pkg@1.2.3", "pinned"), ("pkg@", "unpinned")]:
            got = dc.classify_pkg_spec(sp)[0]
            if got != want:
                fail(f"classify_pkg_spec({sp}) 应 {want} 实 {got}")
        ok("DEP-1 dist-tag（latest/next/beta）→ ranged 非钉版；-r/-p 取值旗标不误取；pkg@ 尾随守卫")

        # 8c. 评审 v1.0.1②：Bun 版本化导入统一 classify_pkg_spec（ranged/dist-tag → DEP-4 WARN）
        bun2 = make_skill(tmp, "bun-range")
        (bun2 / "scripts").mkdir()
        (bun2 / "scripts" / "m.ts").write_text(
            "import a from \"pkg@^1.0.0\";\n"
            "import b from \"lat@latest\";\n"
            "import c from \"@scope/pk@2.0.0\";\n", encoding="utf-8")
        (bun2 / "SKILL.md").write_text("# t\nscripts/m.ts 主脚本。\n", encoding="utf-8")
        rows, _ = dc.dep_check(bun2)
        lv = levels(rows)
        r4 = [r for r in rows if r["vid"] == "DEP-4"][0]
        if lv["DEP-4"] != "WARN" or "pkg@^1.0.0" not in r4["ev"] \
                or "lat@latest" not in r4["ev"]:
            fail(f"Bun ranged/dist-tag 导入应 DEP-4 WARN: {lv['DEP-4']} {r4['ev']}")
        if lv["DEP-2"] != "PASS":
            fail(f"版本化导入（含 ranged）应计 DEP-2 PASS: {lv['DEP-2']}")
        ok("DEP-2/4 Bun：pkg@^1.0.0 与 lat@latest → DEP-4 WARN（不再静默）；钉版计入声明")

        # 8d. 评审 v1.0.1③：SKILL.md 缺失 → n_read_err 计入 → COV WARN + PASS 降级
        nomd = tmp / "no-skillmd"
        nomd.mkdir()
        (nomd / "scripts").mkdir()
        (nomd / "scripts" / "a.py").write_text("import os\n", encoding="utf-8")
        rows, _ = dc.dep_check(nomd)
        cov = [r for r in rows if r["vid"] == "COV"][0]
        d5 = [r for r in rows if r["vid"] == "DEP-5"][0]
        d2 = [r for r in rows if r["vid"] == "DEP-2"][0]
        if cov["level"] != "WARN" or d5["level"] != "FAIL" or d2["level"] != "WARN":
            fail(f"SKILL.md 缺失应 COV WARN+PASS 降级: "
                 f"COV={cov['level']} DEP-5={d5['level']} DEP-2={d2['level']}")
        ok("SKILL.md 缺失：COV WARN（读取失败计数）+ PASS 行同步降 WARN")

        # 8e. 评审 v1.0.1⑤⑥：TOML 单引号（requires-python / dependencies 项）
        sq = make_skill(tmp, "sq-toml")
        (sq / "scripts").mkdir()
        (sq / "scripts" / "c.py").write_text(
            "# /// script\n# requires-python = '>=3.10'\n"
            "# dependencies = ['requests>=2.31']\n# ///\nimport requests\n",
            encoding="utf-8")
        (sq / "SKILL.md").write_text("# t\nscripts/c.py 主脚本。\n", encoding="utf-8")
        rows, _ = dc.dep_check(sq)
        lv = levels(rows)
        if lv["DEP-2"] != "PASS" or lv["DEP-4"] != "PASS":
            fail(f"单引号 TOML 应全 PASS: DEP-2={lv['DEP-2']} DEP-4={lv['DEP-4']}")
        ok("TOML 单引号：requires-python 与 dependencies 项均正确抽取（不再误 WARN）")

        # 9. 退出码 0/1/2（子进程级）+ 参数错误统一 1 + --out
        if run_exit(str(sk)) != 0:
            fail("合规退出码应为 0")
        if run_exit(str(n7)) != 1:
            fail("DEP-2 FAIL 退出码应为 1")
        if run_exit(str(bare)) != 2:
            fail("仅 WARN（DEP-4）退出码应为 2")
        if run_exit() != 1:
            fail("缺 skill_dir 应返回 1，不得用 argparse 默认 exit 2")
        if run_exit(str(tmp / "nope")) != 1:
            fail("目录不存在应返回 1")
        if run_exit(str(sk), "--mode", "bogus") != 1:
            fail("未知旗标应经 error() 覆写返回 1")
        out_path = tmp / "report" / "dep.md"
        if run_exit(str(sk), "--out", str(out_path)) != 0:
            fail("--out 模式退出码应为 0")
        if not out_path.is_file() or "依赖检测五项报告" not in out_path.read_text(encoding="utf-8"):
            fail("--out 报告未落盘或内容缺失")
        ok("退出码 0/1/2（SKIP 不计警告）+ 参数错误统一 1 + --out 落盘")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nALL PASS ({len(passed)} 组断言)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
