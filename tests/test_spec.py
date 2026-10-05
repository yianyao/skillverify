"""spec 模块回归测试。

**本文件的特殊价值**：测试用例直接复刻官方 `skills-ref` 的
`tests/test_validator.py`，并在官方 CLI 在场时**双向对账**——
既验证"我们判对了"，也验证"我们与官方一致"。

用法：
    python -m tests.test_spec              # 离线运行（官方 CLI 缺席时对账项自动 SKIP）
    python -m tests.test_spec --require-official   # 官方 CLI 缺席即失败
"""

from __future__ import annotations

import os

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):  # 允许 `python tests/test_spec.py` 直接运行
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skillverify.encoding import force_utf8_stdio  # noqa: E402
from skillverify.report import FAIL, PASS  # noqa: E402
from skillverify.spec import check_spec, find_official_cli, run_official  # noqa: E402

_VALID = (
    "---\n"
    "name: {name}\n"
    "description: A test skill used by the regression suite for validation.\n"
    "---\n\n"
    "# Body\n"
)

#: (用例名, 目录名, SKILL.md 内容或 None 表示不创建, 期望是否合法)
CASES: list[tuple[str, str, str | None, bool]] = [
    ("valid", "my-skill", _VALID.format(name="my-skill"), True),
    ("missing_skill_md", "my-skill", None, False),
    ("no_frontmatter", "my-skill", "# 没有 frontmatter\n", False),
    ("unclosed_frontmatter", "my-skill", "---\nname: my-skill\ndescription: x\n", False),
    ("invalid_yaml", "my-skill", "---\nname: [invalid\ndescription: x\n---\n", False),
    ("frontmatter_not_mapping", "my-skill", "---\n- a\n- b\n---\n", False),
    ("missing_name", "my-skill", "---\ndescription: x\n---\n", False),
    ("missing_description", "my-skill", "---\nname: my-skill\n---\n", False),
    ("unexpected_field", "my-skill",
     "---\nname: my-skill\ndescription: x\nunknown_field: y\n---\n", False),
    ("uppercase_name", "my-skill", _VALID.format(name="My-Skill"), False),
    ("name_too_long", "my-skill", _VALID.format(name="a" * 70), False),
    ("leading_hyphen", "my-skill", _VALID.format(name="-myskill"), False),
    ("trailing_hyphen", "my-skill", _VALID.format(name="myskill-"), False),
    ("consecutive_hyphens", "my-skill", _VALID.format(name="my--skill"), False),
    ("invalid_chars", "my-skill", _VALID.format(name="my_skill"), False),
    ("dir_name_mismatch", "other-dir", _VALID.format(name="my-skill"), False),
    ("description_too_long", "my-skill",
     _VALID.format(name="my-skill").replace(
         "A test skill used by the regression suite for validation.", "x" * 1100),
     False),
    ("compatibility_too_long", "my-skill",
     "---\nname: my-skill\ndescription: x\ncompatibility: " + "y" * 550 + "\n---\n", False),
    ("allowed_tools_accepted", "my-skill",
     "---\nname: my-skill\ndescription: x\nallowed-tools: Bash(jq:*) Bash(git:*) Read\n---\n",
     True),
    ("all_fields_ok", "my-skill",
     "---\nname: my-skill\ndescription: x\nlicense: MIT\n"
     "allowed-tools: Bash Read\nmetadata:\n  author: me\n  version: 1.0\n"
     "compatibility: Requires Python 3.11+\n---\n", True),
    ("metadata_values_stringified", "my-skill",
     "---\nname: my-skill\ndescription: x\nmetadata:\n  version: 1.0\n---\n", True),
    ("i18n_chinese_name", "技能", _VALID.format(name="技能"), True),
    ("i18n_uppercase_rejected", "навык", _VALID.format(name="НАВЫК"), False),
]

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


def run_case_matrix(tmp: Path, official: str | None) -> None:
    """逐用例验证：「我们的判定 == 期望」且「我们的判定 == 官方判定」。"""
    print("[test_case_matrix]")
    for name, dirname, content, expect_valid in CASES:
        case_dir = tmp / name / dirname
        case_dir.mkdir(parents=True, exist_ok=True)
        if content is not None:
            (case_dir / "SKILL.md").write_text(content, encoding="utf-8", newline="\n")

        _, report = check_spec(case_dir)
        ours_valid = report.exit_code() != 1

        if ours_valid != expect_valid:
            fail(f"{name}: 本地判定 {ours_valid} 与期望 {expect_valid} 不符")
            continue

        if official:
            off = run_official(case_dir, official)
            if off.status == "SKIP":
                ok(f"{name}: 本地判定符合期望（官方对账 SKIP）")
                continue
            off_valid = off.status != "FAIL"
            if off_valid != ours_valid:
                fail(f"{name}: 本地 {ours_valid} 与官方 {off_valid} 不一致｜{off.evidence}")
                continue
        ok(f"{name}: 判定符合期望，且与官方一致" if official else f"{name}: 判定符合期望")


def run_semantics(tmp: Path) -> None:
    """规则语义本身的断言（不依赖官方 CLI）。"""
    print("[test_semantics]")

    # 1. 未知字段的错误必须点名该字段，并列出允许字段
    d = tmp / "sem_unexpected" / "my-skill"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: x\ncustom_thing: 1\n---\n",
        encoding="utf-8", newline="\n")
    _, rep = check_spec(d)
    hit = [r for r in rep.results if r.rid == "SKILL-004" and r.status == "FAIL"]
    if hit and "custom_thing" in hit[0].evidence:
        ok("未知字段报错点名具体字段名")
    else:
        fail(f"未知字段报错未点名字段: {hit}")

    # 2. name 的 i18n 差异只记 INFO，绝不判 FAIL
    d2 = tmp / "sem_i18n" / "技能"
    d2.mkdir(parents=True)
    (d2 / "SKILL.md").write_text(_VALID.format(name="技能"), encoding="utf-8", newline="\n")
    _, rep2 = check_spec(d2)
    info = [r for r in rep2.results if r.rid == "SPEC-TEXT"]
    if info and info[0].status == "INFO" and rep2.exit_code() == 0:
        ok("i18n name：记 INFO 且不阻断（exit 0）")
    else:
        fail(f"i18n name 处理异常: status={info[0].status if info else None} exit={rep2.exit_code()}")

    # 3. 前置短路时后续规则必须记 SKIP，而不是假装 PASS
    d3 = tmp / "sem_short" / "my-skill"
    d3.mkdir(parents=True)
    (d3 / "SKILL.md").write_text("# 无 frontmatter\n", encoding="utf-8", newline="\n")
    _, rep3 = check_spec(d3)
    skipped = [r for r in rep3.results if r.status == "SKIP"]
    passed = [r for r in rep3.results if r.status == "PASS"]
    if skipped and not passed:
        ok(f"前置短路：{len(skipped)} 项记 SKIP，0 项假 PASS")
    else:
        fail(f"短路语义错误: SKIP={len(skipped)} PASS={len(passed)}")

    # 4. 元数据值被强制转字符串（与官方 parser 一致）
    d4 = tmp / "sem_meta" / "my-skill"
    d4.mkdir(parents=True)
    (d4 / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: x\nmetadata:\n  version: 1.0\n---\n",
        encoding="utf-8", newline="\n")
    doc, _ = check_spec(d4)
    meta = doc.frontmatter.get("metadata") if doc.frontmatter else None
    if isinstance(meta, dict) and meta.get("version") == "1.0":
        ok("metadata 值强制转字符串（version: 1.0 -> \"1.0\"）")
    else:
        fail(f"metadata 值类型处理异常: {meta!r}")


def run_path_errors(tmp: Path) -> None:
    """路径级错误。"""
    print("[test_path_errors]")
    _, rep = check_spec(tmp / "does-not-exist")
    if rep.exit_code() == 1 and any(r.rid == "SKILL-001" for r in rep.results):
        ok("路径不存在 -> SKILL-001 FAIL")
    else:
        fail("路径不存在未正确报错")

    a_file = tmp / "a-file.md"
    a_file.write_text("x", encoding="utf-8")
    _, rep2 = check_spec(a_file)
    if rep2.exit_code() == 1:
        ok("传入文件而非目录 -> FAIL")
    else:
        fail("传入文件未报错")


def run_regressions(tmp: Path) -> None:
    """外部评审确认并修掉的两类缺陷的回归断言。"""
    print("[test_regressions]")
    from skillverify.frontmatter import parse_frontmatter
    from skillverify.spec import check_spec

    # ① 相对路径：`spec .` 曾因 Path(".").name 是空串而误报 SKILL-012
    skill = tmp / "rel-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: rel-skill\ndescription: A demo skill for the relative path probe.\n"
        "---\n\n# D\n", encoding="utf-8", newline="")
    cwd = Path.cwd()
    try:
        os.chdir(skill)
        _doc, report = check_spec(Path("."))
        row = next(r for r in report.results if r.rid == "SKILL-012")
        check(row.status == PASS,
              f"`spec .` 不再误报 SKILL-012（实得 {row.status}：{row.evidence[:60]}）")
    finally:
        os.chdir(cwd)
    _doc2, report2 = check_spec(skill)
    check(next(r for r in report2.results if r.rid == "SKILL-012").status == PASS,
          "绝对路径仍然 PASS（对照组）")

    # ② 双引号转义必须单遍处理：链式 replace 会把 `a\\nb` 里的 `\\n` 先换成换行
    doc = parse_frontmatter('---\nkey: "a\\\\nb"\n---\n\n# b\n')
    check(doc.get("key") == "a\\nb",
          f"`a\\\\nb` 解析为字面反斜杠+n（实得 {doc.get('key')!r}）")
    doc2 = parse_frontmatter('---\nkey: "a\\nb"\n---\n\n# b\n')
    check(doc2.get("key") == "a\nb",
          f"`a\\nb` 解析为换行（实得 {doc2.get('key')!r}）")
    doc3 = parse_frontmatter('---\nkey: "say \\"hi\\""\n---\n\n# b\n')
    check(doc3.get("key") == 'say "hi"', f"转义引号（实得 {doc3.get('key')!r}）")

    # ③ 块标量必须保留**相对**缩进（逐行 strip 会吃掉它）
    doc4 = parse_frontmatter(
        "---\nkey: |\n  第一行\n    缩进两格的第二行\n  第三行\n---\n\n# b\n")
    check(doc4.get("key") == "第一行\n  缩进两格的第二行\n第三行\n",
          f"块标量 | 保留相对缩进（实得 {doc4.get('key')!r}）")
    # ④ 主文件名大小写：在大小写不敏感的系统上，`(dir / "SKILL.md").is_file()` 对
    #    `Skill.md` 也返回 True —— 于是本机 PASS、Linux 宿主加载失败。必须拦住。
    wrong = tmp / "wrong-case"
    wrong.mkdir(parents=True)
    (wrong / "Skill.md").write_text(
        "---\nname: wrong-case\ndescription: A wrong case filename probe here.\n---\n\n# D\n",
        encoding="utf-8", newline="")
    _doc_w, report_w = check_spec(wrong)
    row = next(r for r in report_w.results if r.rid == "SKILL-002")
    check(row.status == FAIL and "大小写" in row.evidence,
          f"`Skill.md`（错大小写）→ SKILL-002 FAIL 且点名大小写（实得 {row.status}："
          f"{row.evidence[:70]}）")
    check(report_w.exit_code() == 1, "该情况阻断")
    right = tmp / "right-case"
    right.mkdir(parents=True)
    (right / "SKILL.md").write_text(
        "---\nname: right-case\ndescription: A correct case filename probe here.\n---\n\n# D\n",
        encoding="utf-8", newline="")
    _doc_r, report_r = check_spec(right)
    check(next(r for r in report_r.results if r.rid == "SKILL-002").status == PASS,
          "正确大小写仍然 PASS（对照组）")

    doc5 = parse_frontmatter("---\nkey: |-\n  第一行\n  第二行\n---\n\n# b\n")
    check(doc5.get("key") == "第一行\n第二行", f"`|-` 去掉末尾换行（实得 {doc5.get('key')!r}）")


def run_repo_skills(tmp: Path) -> None:
    """本仓库**自己发布**的技能必须过自家 spec（legacy/ 是冻结语料，不算）。

    为什么需要：`evals-skill/SKILL.md` 曾带一个 `version:` 顶层字段（违反 SKILL-004），
    而 `--dogfood` 只拉 `legacy/`，于是自家回归永远抓不到「我们自己的技能过不了自己的校验器」。
    """
    print("[test_repo_skills]")
    repo = Path(__file__).resolve().parent.parent
    found: list[Path] = []
    for path in repo.rglob("SKILL.md"):
        rel = path.relative_to(repo).as_posix()
        if rel.startswith("legacy/") or ".agents/" in rel or ".verify" in rel:
            continue
        found.append(path)
    check(bool(found), f"仓库里有自家发布的技能可检查（{len(found)} 个）")
    bad: list[str] = []
    for path in found:
        _doc, report = check_spec(path.parent)
        fails = [r.rid for r in report.results if r.status == FAIL]
        if fails:
            bad.append(f"{path.relative_to(repo).as_posix()}: {', '.join(fails)}")
    check(not bad, f"自家技能全部通过 spec（不过的: {bad}）")


def main() -> int:
    force_utf8_stdio()
    parser = argparse.ArgumentParser(description="skillverify spec 模块回归测试")
    parser.add_argument("--require-official", action="store_true",
                        help="官方 CLI 缺席时直接失败")
    args = parser.parse_args()

    official = find_official_cli()
    print(f"官方 CLI: {official or '未找到（对账项跳过）'}\n")
    if args.require_official and not official:
        print("FAIL: --require-official 但未找到官方 CLI", file=sys.stderr)
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="sv_test_spec_"))
    try:
        run_case_matrix(tmp, official)
        run_semantics(tmp)
        run_path_errors(tmp)
        run_regressions(tmp)
        run_repo_skills(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = len(_passed) + len(_failed)
    print(f"\n结果: PASS={len(_passed)} FAIL={len(_failed)} 合计={total}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
