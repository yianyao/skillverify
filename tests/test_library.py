"""库级检查（多技能组合）、外来技能审计、评测委托执行。

为什么单独一套：这三件事的观察对象都不是"单个技能的内部质量"，而是
**把技能集合当成整体**（元数据预算 / 描述互相抢触发）与**把外来技能当成待决策对象**
（来源、能力、内容有没有被换过）。放在 lint/evalx 那几套里会稀释它们的主题。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skillverify import cli  # noqa: E402
from skillverify.audit import edit_distance, name_lookalikes  # noqa: E402
from skillverify.encoding import force_utf8_stdio  # noqa: E402
from skillverify.library import (  # noqa: E402
    DEFAULT_METADATA_BUDGET, check_description_overlap, check_metadata_budget, overlap, tokens,
)
from skillverify.report import FAIL, INFO, PASS, WARN  # noqa: E402

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


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    """跑 CLI；抛出前先把捕获的输出打出来（否则现象是"套件安静地没了"）。"""
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(argv)
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
    except BaseException:
        print("  ---- stdout ----")
        print(out.getvalue()[-2000:])
        print("  ---- stderr ----")
        print(err.getvalue()[-2000:])
        raise
    return code, out.getvalue(), err.getvalue()


class Ref:
    """最小技能引用（library 只需要 name 与 path）。"""

    def __init__(self, name: str, path: Path) -> None:
        self.name = name
        self.path = path


def write_skill(root: Path, name: str, description: str, *, body: str = "# Demo\n",
                extra: dict[str, str] | None = None) -> Path:
    target = root / name
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}",
        encoding="utf-8", newline="")
    for rel, content in (extra or {}).items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="")
    return target


# --------------------------------------------------------------------------- #
# LIB-001 元数据预算
# --------------------------------------------------------------------------- #


def run_metadata_budget(tmp: Path) -> None:
    print("[test_metadata_budget]")
    root = tmp / "budget" / ".agents" / "skills"
    write_skill(root, "alpha", "A" * 60)
    write_skill(root, "beta", "B" * 30)
    refs = [Ref("alpha", root / "alpha"), Ref("beta", root / "beta")]

    total = len("alpha") + 60 + len("beta") + 30          # name + description 逐技能相加
    result = check_metadata_budget(refs, budget=DEFAULT_METADATA_BUDGET)
    check(result.status == PASS, f"预算充足 → PASS（实得 {result.status}）")
    check(f"合计 {total} 字符" in result.evidence,
          f"证据里给出**总量** {total}（这就是那个「组合视图」）")
    check("最大贡献" in result.evidence and "alpha(65)" in result.evidence,
          "证据里给出主要贡献者（谁最占预算）")
    check("不含宿主包装开销" in result.evidence,
          "口径写明只计 name+description——不许让人以为是官方全量口径")

    tight = check_metadata_budget(refs, budget=10)
    check(tight.status == WARN and f"超出 {total - 10}" in tight.evidence,
          f"超预算 → WARN 且给出超出量（实得 {tight.status}：{tight.evidence[-40:]}）")
    check("静默丢弃" in tight.evidence, "说清后果：宿主截断时技能会被静默丢弃")

    empty = check_metadata_budget([])
    check(empty.status == INFO, "没有技能 → INFO（不适用），不是 PASS")


# --------------------------------------------------------------------------- #
# LIB-002 描述词面重叠
# --------------------------------------------------------------------------- #


def run_description_overlap(tmp: Path) -> None:
    print("[test_description_overlap]")
    root = tmp / "overlap" / ".agents" / "skills"
    base = "Generate weekly CSV reports from sales data and email them to the team."
    write_skill(root, "csv-report", base)
    write_skill(root, "csv-reports", base + " Also handle refunds.")
    write_skill(root, "pdf-tool", "Convert scanned documents into searchable PDF files.")
    refs = [Ref(n, root / n) for n in ("csv-report", "csv-reports", "pdf-tool")]

    result = check_description_overlap(refs)
    check(result.status == WARN, f"高度重叠的两个描述 → WARN（实得 {result.status}）")
    check("csv-report ↔ csv-reports" in result.evidence, "点名是哪两个技能")
    check("共同词元" in result.evidence and "reports" in result.evidence,
          "列出共同词元（让人能自己判断，而不是只给一个分数）")
    check("词面重叠不等于冲突" in result.evidence, "说明这是提示、不是判定")

    single = check_description_overlap(refs[:1])
    check(single.status == INFO, "技能不足 2 个 → INFO")

    # 短描述不该被拿去比：词元太少，比出来全是噪声
    short = tmp / "short" / ".agents" / "skills"
    write_skill(short, "a-skill", "Do A.")
    write_skill(short, "b-skill", "Do B.")
    short_refs = [Ref("a-skill", short / "a-skill"), Ref("b-skill", short / "b-skill")]
    result_short = check_description_overlap(short_refs)
    # 词元不足时**不比对**：既不能报重叠（噪声），也不该报"没有重叠"（那是假通过）
    check(result_short.status == INFO and "无法可靠比对" in result_short.evidence,
          f"描述过短 → INFO 并如实说明（实得 {result_short.status}："
          f"{result_short.evidence[:50]}）")
    # 一长一短：短的仍不参与，但长的那些照常比
    write_skill(short, "c-skill", base)
    write_skill(short, "d-skill", base + " Also handle refunds.")
    mixed = [*short_refs, Ref("c-skill", short / "c-skill"), Ref("d-skill", short / "d-skill")]
    result_mixed = check_description_overlap(mixed)
    check(result_mixed.status == WARN and "c-skill ↔ d-skill" in result_mixed.evidence,
          "混入过短描述时，仍对可比对的那部分给出结论")

    # 词元与重叠系数本身要有明确语义（这两条是"能失败"的单元断言）
    toks = tokens("Generate weekly CSV reports 生成周报")
    check("generate" in toks and "csv" in toks, "ASCII 词进入词元集合")
    check("生成" in toks or "周报" in toks, "CJK 按字符 bigram 切分")
    check("the" not in toks and "for" not in toks, "功能词被过滤（否则每条描述都互相像）")
    score, shared = overlap({"x", "y"}, {"x", "y", "z", "w"})
    check(score == 1.0 and shared == ["x", "y"],
          "重叠系数用「交集/较小集合」：短描述被长描述完全覆盖时应当是 1.0")


# --------------------------------------------------------------------------- #
# audit
# --------------------------------------------------------------------------- #


def run_audit(tmp: Path) -> None:
    print("[test_audit]")
    proj = tmp / "audit-proj"
    lib = proj / ".agents" / "skills"
    write_skill(lib, "csv-report", "Generate weekly CSV reports from sales data.")
    foreign = write_skill(
        tmp / "incoming", "csv_report",
        "Generate weekly CSV reports from sales data.",
        body="# Demo\n\n引用不存在的文件：`references/missing.md`\n")
    (foreign / "scripts").mkdir(exist_ok=True)
    (foreign / "scripts" / "tool.py").write_text(
        "import argparse\np = argparse.ArgumentParser()\np.parse_args()\n",
        encoding="utf-8", newline="")
    home = tmp / "audit-home"
    home.mkdir(parents=True, exist_ok=True)
    common = ["--project", str(proj), "--user-home", str(home), "--root", str(lib)]

    code, out, _err = run_cli(["audit", str(foreign), *common, "--record", "--json"])
    payload = json.loads(out)
    by_rid = {r["rid"]: r for r in payload["results"]}
    check(code == 1, f"审计发现 FAIL（断链 + 名字非法字符）→ exit 1（实得 {code}）")
    check(by_rid["AUDIT-001"]["status"] == PASS and "指纹" in by_rid["AUDIT-001"]["evidence"],
          "记录内容指纹（下次比对的依据）")
    check(by_rid["AUDIT-002"]["status"] == INFO,
          "第一次审计 → INFO「没有可比的上一份」")
    check(by_rid["AUDIT-003"]["status"] == WARN
          and "csv-report" in by_rid["AUDIT-003"]["evidence"],
          f"名字近似提示（csv_report vs csv-report，实得 {by_rid['AUDIT-003']['status']}）")
    check(by_rid["AUDIT-004"]["status"] == INFO, "没有 git 信息 → INFO 并提示人工写明来源")
    check("脚本 1 项" in by_rid["AUDIT-005"]["evidence"],
          f"能力清单汇总到脚本数量（实得 {by_rid['AUDIT-005']['evidence'][:60]}）")
    check(any(r["rid"] == "REF-001" and r["status"] == FAIL for r in payload["results"]),
          "组合了 lint 的结论（断链被抓出来）——审计不是另起一套判据")

    record_dir = proj / ".agents" / "skillverify" / "audit"
    check((record_dir / "csv_report.json").is_file() and (record_dir / "csv_report.md").is_file(),
          "审计单落盘（json 供比对 + md 给人看）")
    md = (record_dir / "csv_report.md").read_text(encoding="utf-8")
    check("信任级别" in md and "人工填写" in md,
          "审计单里有**留给人填**的信任级别栏（机械层判定不了信任，就不假装能判）")
    check("不是安全背书" in md, "审计单写明它不是安全背书（不跑脚本、不模拟触发）")

    # 内容被换过 → 再审计必须报出来
    (foreign / "SKILL.md").write_text(
        (foreign / "SKILL.md").read_text(encoding="utf-8") + "\n新增一行。\n",
        encoding="utf-8", newline="")
    _code2, out2, _e2 = run_cli(["audit", str(foreign), *common, "--json"])
    again = {r["rid"]: r for r in json.loads(out2)["results"]}
    check(again["AUDIT-002"]["status"] == WARN and "内容与上次审计" in again["AUDIT-002"]["evidence"],
          "内容变了 → WARN 并给出前后指纹（这是审计留痕唯一的意义所在）")

    # stdout 纪律：--json 时不得再打印审计单正文
    _code3, out3, _e3 = run_cli(["audit", str(foreign), *common, "--json"])
    check(out3.strip().startswith("{") and out3.strip().endswith("}"),
          "`--json` 的 stdout 是纯 JSON（审计单正文不许混进来）")

    # 名字近似与编辑距离的单元断言
    check(edit_distance("csvreport", "csvreports") == 1, "编辑距离：加一个字符 = 1")
    check(name_lookalikes("csv-report", ["csv_report", "csvreports", "pdf-tool"])
          == [("csv_report", 0), ("csvreports", 1)],
          "分隔符差异按「同名」看待（距离 0），差一个字符记为 1")


# --------------------------------------------------------------------------- #
# 评测委托执行
# --------------------------------------------------------------------------- #


def run_evals_delegation(tmp: Path) -> None:
    print("[test_evals_delegation]")
    skill = write_skill(tmp / "delegate", "ev-skill", "An eval delegation probe skill.")
    (skill / "evals").mkdir(exist_ok=True)
    (skill / "evals" / "evals.json").write_text(json.dumps({
        "skill_name": "ev-skill",
        "evals": [{"id": 1, "prompt": "p", "expected_output": "o", "assertions": ["输出是好的"]}],
    }, ensure_ascii=False), encoding="utf-8", newline="")

    # ① 不委托时的提示：本工具不执行评测，并指出该找谁
    _code, out, _err = run_cli(["evals", str(skill), "--json"])
    layer = json.loads(out)["meta"].get("执行层", "")
    check("不执行" in layer and "skill-creator" in layer,
          f"报告 meta 显式声明执行层委托官方工具（实得 {layer[:50]}）")

    # ② 委托执行成功 → 重新校验产物，并记下命令
    # 用一个真实脚本当"官方评测器的入口"：委托执行不关心它是什么，只看退出码与副作用
    ok_file = tmp / "delegated-ok.txt"
    runner = tmp / "runner.py"
    runner.write_text(
        "from pathlib import Path\n"
        "Path(r'%s').write_text('ran', encoding='utf-8')\n" % ok_file,
        encoding="utf-8", newline="")
    command = f'"{sys.executable}" "{runner}"'
    code2, out2, err2 = run_cli(["evals", str(skill), "--json", "--run-with", command])
    check(ok_file.is_file(), "委托的命令确实被执行了（副作用可见）")
    check("委托执行" in err2, "stderr 说明委托执行的结果")
    check(json.loads(out2)["meta"].get("委托执行", "").startswith('"'), "记录里带上被执行的命令")

    # ③ 委托执行失败 → FAIL，绝不写成"不适用/通过"
    code3, out3, _err3 = run_cli(["evals", str(skill), "--json", "--run-with",
                                  f'"{sys.executable}" -c "import sys; sys.exit(3)"'])
    row = next(r for r in json.loads(out3)["results"] if r["rid"] == "RUN-101")
    check(code3 == 1 and row["status"] == FAIL,
          f"委托命令失败 → RUN-101 FAIL 且退出 1（实得 {row['status']}）")
    check("退出码 3" in row["evidence"], "证据里写明退出码，便于排查")


def main() -> int:
    force_utf8_stdio()
    argparse.ArgumentParser(description="skillverify 库级检查 / 审计 / 委托执行").parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="sv_test_library_"))
    try:
        run_metadata_budget(tmp)
        run_description_overlap(tmp)
        run_audit(tmp)
        run_evals_delegation(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    total = len(_passed) + len(_failed)
    print(f"\n结果: PASS={len(_passed)} FAIL={len(_failed)} 合计={total}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
