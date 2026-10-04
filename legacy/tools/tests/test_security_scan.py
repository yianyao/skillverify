#!/usr/bin/env python3
"""test_security_scan.py — security_scan.py 固化回归单测（V8 安全扫描器）。

以临时夹具固化开发期实测结论：合规夹具全 PASS、六类安全缺陷各自响亮命中、
两级语义（代码 FAIL / 文档 WARN）、占位符降噪、端点声明与白名单豁免、
扫描面跳过纪律、覆盖不全不假 PASS、退出码 0/1/2 工具族约定。
任何 security_scan.py 改动后必须先过本文件。
只读 + 临时目录夹具（mock 仅限进程内），无系统副作用。

用法: python tests/test_security_scan.py    # 全过打印 ALL PASS，失败非零退出
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

HIGH_ENTROPY = "aB3dE6fH9iK2lM5nP8qR1sT4uV7wX0yZ"  # 实测香农熵 5.0 ≥ 4.5


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ss = load("security_scan_under_test", TOOLS / "security_scan.py")


def ok(msg: str) -> None:
    passed.append(msg)
    print(f"  PASS {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")
    sys.exit(1)


def make_skill(root: Path, name: str, fm: str, body: str = "\n# t\n",
               scripts: dict[str, str] | None = None,
               extra: dict[str, str] | None = None,
               skipdirs: dict[str, str] | None = None) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\n{fm}---\n{body}", encoding="utf-8", newline="\n")
    for fn, src in (scripts or {}).items():
        sd = d / "scripts"
        sd.mkdir(exist_ok=True)
        (sd / fn).write_text(src, encoding="utf-8", newline="\n")
    for fn, src in (extra or {}).items():
        fp = d / fn
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(src, encoding="utf-8", newline="\n")
    for fn, src in (skipdirs or {}).items():
        fp = d / ".verification" / fn
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(src, encoding="utf-8", newline="\n")
    return d


def levels(rows: list[dict]) -> dict[str, str]:
    return {r["vid"]: r["level"] for r in rows}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ss-test-"))
    try:
        GOOD_FM = "name: good-skill\ndescription: 一个合规技能\ncompatibility: 需要 Python 3.10+\n"

        # 1. 合规夹具：V8-1..V8-6 全 PASS，INFO 覆盖行
        good = make_skill(tmp, "good-skill", GOOD_FM,
                          scripts={"a.py": "print('x')\n"},
                          extra={"references/g.md": "纯文档，无外链。\n"})
        rows = {r["vid"]: r for r in ss.scan(good, [])[0]}
        for vid in ("V8-1", "V8-2", "V8-3", "V8-4", "V8-5", "V8-6"):
            if rows[vid]["level"] != "PASS":
                fail(f"合规夹具 {vid} 应 PASS，实为 {rows[vid]['level']}: {rows[vid]['ev']}")
        if rows["COV"]["level"] != "INFO":
            fail(f"合规夹具覆盖行应 INFO，实为 {rows['COV']['level']}")
        ok("合规夹具 V8-1~V8-6 全 PASS + 覆盖行 INFO")

        # 1b. 证据脱敏：secret 命中证据不含完整密钥（v1.0.1 评审 1；自持夹具）
        mask_skill = make_skill(tmp, "mask-skill", GOOD_FM,
                                scripts={"a.py": "k = 'AKIAIOSFODNN7EXAMPLE'\n"})
        rows = {r["vid"]: r for r in ss.scan(mask_skill, [])[0]}
        ev = rows["V8-1"]["ev"]
        if "AKIAIOSFODNN7EXAMPLE" in ev:
            fail(f"V8-1 证据明文泄露完整密钥: {ev}")
        if "AKIA" not in ev:
            fail(f"V8-1 证据应保留首段特征便于定位: {ev}")
        if "MPLE" in ev or "NN7EX" in ev:
            fail(f"V8-1 尾段泄露超过 tail=2 口径（v1.0.2 评审 3）: {ev}")
        ok("V8-1 证据脱敏：含 AKIA 特征、不含完整密钥、尾段 ≤2 字符")

        # 2. secret 正则命中（scripts 内 AKIA）→ V8-1 FAIL
        leak = make_skill(tmp, "leak-skill", GOOD_FM,
                          scripts={"bad.py": "k = 'AKIAIOSFODNN7EXAMPLE'\n"})
        rows = levels(ss.scan(leak, [])[0])
        if rows["V8-1"] != "FAIL":
            fail(f"AKIA 命中应 V8-1 FAIL，实为 {rows['V8-1']}")
        ok("V8-1 secret 正则：scripts 内 AKIA → FAIL")

        # 3. 占位符降噪：通用赋值型占位符不命中
        ph = make_skill(tmp, "placeholder-skill", GOOD_FM,
                        scripts={"a.py": "password = 'your-password-here'\n"})
        scan_rows, st = ss.scan(ph, [])
        if scan_rows[0]["level"] != "PASS":
            fail(f"占位符不应命中，实为 {scan_rows[0]['level']}: {scan_rows[0]['ev']}")
        if st["placeholder_filtered"] != 1:
            fail(f"占位符过滤计数应为 1，实为 {st['placeholder_filtered']}")
        ok("V8-1 占位符降噪：your-password-here 不命中且计数=1")

        # 4. 熵检测：高熵串 FAIL；64 位 hex 哈希（低熵）不误报
        ent = make_skill(tmp, "entropy-skill", GOOD_FM,
                         scripts={"a.py": f"raw = '{HIGH_ENTROPY}'\n"},
                         extra={"references/h.md": "sha256 = " + "3a42f85c9c1c30f2a5e77d1b64cf09a2e11f8d07c3d5b21a9e046cf80b1d5e77\n"})
        rows = levels(ss.scan(ent, [])[0])
        if rows["V8-2"] != "FAIL":
            fail(f"高熵串应 V8-2 FAIL，实为 {rows['V8-2']}")
        hex_only = make_skill(tmp, "hex-skill", GOOD_FM,
                              extra={"references/h.md": "sha256 = " + "3a42f85c9c1c30f2a5e77d1b64cf09a2e11f8d07c3d5b21a9e046cf80b1d5e77\n"})
        rows = levels(ss.scan(hex_only, [])[0])
        if rows["V8-2"] != "PASS":
            fail(f"hex 哈希不应触熵，实为 {rows['V8-2']}: {[r for r in ss.scan(hex_only, [])[0] if r['vid']=='V8-2'][0]['ev']}")
        ok("V8-2 熵检测：高熵串 FAIL，hex 哈希不误报")

        # 5. 端点比对：声明放行 / 文档链接未声明 FAIL / --allow-url 豁免
        ep = make_skill(tmp, "endpoint-skill",
                        "name: endpoint-skill\ndescription: t\n"
                        "compatibility: 需访问 https://api.example.com/v1\n",
                        body="\n文档: https://docs.python.org/3/ 与 https://evil.example.com/x\n")
        rows = {r["vid"]: r for r in ss.scan(ep, [])[0]}
        if rows["V8-3"]["level"] != "FAIL":
            fail(f"未声明端点应 FAIL，实为 {rows['V8-3']['level']}")
        if "docs.python.org" not in rows["V8-3"]["ev"] or "evil.example.com" not in rows["V8-3"]["ev"]:
            fail(f"未声明端点证据应含两个 URL: {rows['V8-3']['ev']}")
        rows = {r["vid"]: r for r in ss.scan(ep, ["docs.python.org"])[0]}
        if rows["V8-3"]["level"] != "FAIL" or "evil.example.com" not in rows["V8-3"]["ev"] \
                or "docs.python.org" in rows["V8-3"]["ev"].split("。下一步")[0]:
            fail(f"--allow-url 豁免 docs.python.org 后应仅余 evil.example.com: {rows['V8-3']['ev']}")
        # 5b. 主机边界（v1.0.1 评审 2）：URL 前缀/声明条目不得放行攻性子域
        for url, declared, allow in [
            ("https://example.com.evil.io/x", [], ["https://example.com"]),
            ("https://api.example.com.evil.io/v1/x", ["https://api.example.com/v1"], []),
            ("https://api.example.com.evil.io/x", [], ["api.example.com"]),
        ]:
            okf, basis = ss.url_allowed(url, declared, allow)
            if okf:
                fail(f"主机边界失效: {url} 被 {declared or allow} 放行（依据: {basis}）")
        # 5c. 正向：子域与路径边界内放行（declared 来源恒为 URL 正则，必带 scheme）
        for url, declared in [("https://api.example.com/v1/x", ["https://api.example.com/v1"]),
                              ("https://www.api.example.com/x", ["https://api.example.com"])]:
            okf, basis = ss.url_allowed(url, declared, [])
            if not okf:
                fail(f"应放行却拒绝: {url} by {declared}")
        # 5d. 路径边界：/v1 不放行 /v1evil
        okf, _ = ss.url_allowed("https://api.example.com/v1evil", ["https://api.example.com/v1"], [])
        if okf:
            fail("路径边界失效: /v1evil 被 /v1 声明放行")
        ok("V8-3 端点比对：声明放行/未声明 FAIL/白名单豁免/主机与路径边界")

        # 6. 交互两级：代码 input( → FAIL；仅文档提及 → WARN
        itx = make_skill(tmp, "interactive-skill", GOOD_FM,
                         scripts={"a.py": "name = input('> ')\n"})
        rows = levels(ss.scan(itx, [])[0])
        if rows["V8-4"] != "FAIL":
            fail(f"代码 input( 应 V8-4 FAIL，实为 {rows['V8-4']}")
        itx_doc = make_skill(tmp, "interactive-doc-skill", GOOD_FM,
                             extra={"references/g.md": "示例: input( 用法说明。\n"})
        rows = levels(ss.scan(itx_doc, [])[0])
        if rows["V8-4"] != "WARN":
            fail(f"文档提及 input( 应 V8-4 WARN，实为 {rows['V8-4']}")
        ok("V8-4 交互检测：代码 FAIL / 文档 WARN 两级语义")

        # 6b. 前置断言（v1.0.1 评审 9 / v1.0.2 评审 1-2）：近似词形不命中；真实形态命中
        near = make_skill(tmp, "nearmiss-skill", GOOD_FM,
                          scripts={"a.py": "x = reinput('> ')\ny = my_input(z)\n"
                                           "import mygetpass\nz = disinquirer(q)\n"
                                           "from x import prompt_toolkits\nw = read -3p\n"})
        rows = levels(ss.scan(near, [])[0])
        if rows["V8-4"] != "PASS":
            fail(f"reinput(/my_input(/mygetpass/disinquirer/prompt_toolkits/read -3p "
                 f"不应命中 V8-4，实为 {rows['V8-4']}: "
                 f"{[r for r in ss.scan(near, [])[0] if r['vid']=='V8-4'][0]['ev']}")
        rp = make_skill(tmp, "readrp-skill", GOOD_FM,
                        scripts={"a.sh": "read -rp 'name: ' name\n"})
        rows = levels(ss.scan(rp, [])[0])
        if rows["V8-4"] != "FAIL":
            fail(f"read -rp 应命中 V8-4，实为 {rows['V8-4']}")
        gp = make_skill(tmp, "getpass-skill", GOOD_FM,
                        scripts={"a.py": "import getpass\npwd = getpass.getpass('pw: ')\n"})
        rows = levels(ss.scan(gp, [])[0])
        if rows["V8-4"] != "FAIL":
            fail(f"getpass 真实调用应命中 V8-4，实为 {rows['V8-4']}")
        ok("V8-4 边界断言：reinput(/mygetpass/disinquirer/prompt_toolkits/read -3p 零误报；"
           "read -rp 与 getpass 真实形态命中")

        # 7. 破坏性关键词：无防护 FAIL；--dry-run 防护 PASS
        dest = make_skill(tmp, "destructive-skill", GOOD_FM,
                          scripts={"a.py": "os.system('rm -rf tmp')\n"})
        rows = levels(ss.scan(dest, [])[0])
        if rows["V8-5"] != "FAIL":
            fail(f"rm 无防护应 V8-5 FAIL，实为 {rows['V8-5']}")
        prot = make_skill(tmp, "protected-skill", GOOD_FM,
                          scripts={"a.py": "# delete temp files\nimport sys\nassert '--dry-run' or True\n"})
        rows = levels(ss.scan(prot, [])[0])
        if rows["V8-5"] != "PASS":
            fail(f"含 --dry-run 防护应 V8-5 PASS，实为 {rows['V8-5']}: "
                 f"{[r for r in ss.scan(prot, [])[0] if r['vid']=='V8-5'][0]['ev']}")
        ok("V8-5 破坏性关键词：无防护 FAIL / 有 --dry-run PASS")

        # 8. 危险指令关键词：代码命中 FAIL；文档合规表述（"不得绕过确认"）WARN
        dang = make_skill(tmp, "dangerous-skill", GOOD_FM,
                          scripts={"a.py": "# bypass confirmation\nprint(1)\n"})
        rows = levels(ss.scan(dang, [])[0])
        if rows["V8-6"] != "FAIL":
            fail(f"代码 bypass confirmation 应 V8-6 FAIL，实为 {rows['V8-6']}")
        dang_doc = make_skill(tmp, "dangerous-doc-skill", GOOD_FM,
                              body="\nGotchas: 不得绕过用户确认。\n")
        rows = levels(ss.scan(dang_doc, [])[0])
        if rows["V8-6"] != "WARN":
            fail(f"文档合规表述应 V8-6 WARN，实为 {rows['V8-6']}")
        ok("V8-6 危险指令关键词：代码 FAIL / 文档 WARN 两级语义")

        # 9. 扫描面纪律：.verification 内 secret 不触发（工具留痕非交付物）
        sv = make_skill(tmp, "skipdir-skill", GOOD_FM,
                        skipdirs={"leak.md": "AKIAIOSFODNN7EXAMPLE\n"})
        rows = levels(ss.scan(sv, [])[0])
        if rows["V8-1"] != "PASS":
            fail(f".verification 应被跳过，实为 {rows['V8-1']}: "
                 f"{[r for r in ss.scan(sv, [])[0] if r['vid']=='V8-1'][0]['ev']}")
        ok("扫描面纪律：.verification 目录跳过（留痕非交付物）")

        # 10. 覆盖不全不假 PASS（v1.0.1 评审 3 修订语义）：读取失败 → 独立 COV 行 WARN，
        # V8-1 结论仅由真实命中决定（零命中→PASS 降 WARN，绝不 FAIL/不混入"读取失败"证据）
        import unittest.mock as mock
        broken = make_skill(tmp, "broken-skill", GOOD_FM)
        ghost = Path("__ghost__/ghost.md")
        with mock.patch.object(ss, "iter_scan_files", lambda d: iter([(ghost, d / "nope" / "x.md")])):
            rows = {r["vid"]: r for r in ss.scan(broken, [])[0]}
        if rows["COV"]["level"] != "WARN":
            fail(f"读取失败时覆盖行应 WARN，实为 {rows['COV']['level']}")
        if "读取失败" not in rows["COV"]["ev"]:
            fail(f"COV 行证据应载明读取失败: {rows['COV']['ev']}")
        for vid in ("V8-1", "V8-2", "V8-3", "V8-4", "V8-5", "V8-6"):
            if rows[vid]["level"] == "PASS":
                fail(f"读取失败时 {vid} 不得假 PASS")
            if rows[vid]["level"] == "FAIL":
                fail(f"读取失败时 {vid} 不得 FAIL（{vid} 仅由真实命中决定）")
            if "ghost" in rows[vid]["ev"] or "读取失败（" in rows[vid]["ev"]:
                fail(f"文件级读取失败细节混入 {vid} 证据（只允许 COV 行与降级缘由注记）: {rows[vid]['ev']}")
        ok("覆盖不全纪律：COV 行单独承载读取失败；V8 各行不假 PASS 亦不因读取失败 FAIL")

        # 10b. 折叠标量 compatibility（v1.0.1 评审 5）：续行 URL 应被提取为声明
        folded = make_skill(tmp, "folded-skill",
                            "name: folded-skill\ndescription: t\ncompatibility: >\n"
                            "  需要访问 https://api.example.com/v1 以同步数据\n",
                            body="\n访问 https://api.example.com/v1/data\n")
        rows = levels(ss.scan(folded, [])[0])
        if rows["V8-3"] != "PASS":
            fail(f"折叠标量声明的 URL 应放行，实为 {rows['V8-3']}: "
                 f"{[r for r in ss.scan(folded, [])[0] if r['vid']=='V8-3'][0]['ev']}")
        ok("frontmatter 折叠标量：compatibility 续行 URL 提取为声明")

        # 10c. 符号链接跳过（v1.0.1 评审 7；Windows 无特权可能拒建 symlink，条件跳过）
        import os as _os
        linky = make_skill(tmp, "symlink-skill", GOOD_FM)
        secret_outside = tmp / "outside-secret.md"
        secret_outside.write_text("AKIAIOSFODNN7EXAMPLE\n", encoding="utf-8")
        link = linky / "link.md"
        try:
            link.symlink_to(secret_outside)
            rows = levels(ss.scan(linky, [])[0])
            if rows["V8-1"] != "PASS":
                fail(f"符号链接目标不应被读取，实为 {rows['V8-1']}: "
                     f"{[r for r in ss.scan(linky, [])[0] if r['vid']=='V8-1'][0]['ev']}")
            ok("符号链接：跳过不跟随（技能目录外目标不泄露）")
        except OSError:
            ok("符号链接：本环境无 symlink 权限，条件跳过（逻辑经代码走查覆盖）")

        # 11. 退出码 0/1/2 与 --out 落盘（子进程级验证）
        def run_exit(skill: Path, *extra_args: str) -> int:
            return subprocess.run(
                [sys.executable, str(TOOLS / "security_scan.py"), str(skill), *extra_args],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30, stdin=subprocess.DEVNULL).returncode

        if run_exit(good) != 0:
            fail("合规夹具退出码应为 0")
        if run_exit(leak) != 1:
            fail("含 FAIL 夹具退出码应为 1")
        out_path = tmp / "report" / "sec.md"
        if run_exit(itx_doc, "--out", str(out_path)) != 2:
            fail("仅 WARN 夹具退出码应为 2")
        if not out_path.is_file() or "V8 安全扫描报告" not in out_path.read_text(encoding="utf-8"):
            fail("--out 报告未落盘或内容缺失")
        ok("退出码 0/1/2 约定 + --out 报告落盘")

        # 12. --out 空串校验（v1.0.3 收官回填：原 `--out ""` 静默不落盘，现 fail-fast）
        if run_exit(good, "--out", "") != 1 or run_exit(good, "--out", "  ") != 1:
            fail("--out 空/空白串应 exit 1 而非静默跳过落盘")
        ok("--out 空串 → exit 1（v1.0.3 收官回填固化）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nALL PASS ({len(passed)} 组断言)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
