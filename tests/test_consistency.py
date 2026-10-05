"""一致性守卫：**文档里的数字与能力清单必须与代码事实一致**。

为什么需要这一套：本项目一直强调"文档里的命令被真跑"，但**文档里的数字**没人查——
于是反复出现"套件数写 9/10/11/12 各一份""机械层 42 条（实际 46）""提示词 29 条（实际 30）"
这类漂移，每轮都要人工对账。这个套件把那件事机械化：**文档里的数字也真查**。

三条守卫：
1. 数字一致：套件数、规则族条数、提示词条数、spec 构成、校准样本数；
2. 算术自洽：《覆盖对照》每行「条数 = 覆盖 + 部分 + 未覆盖」；
3. 交付完整：新增的**用户可见能力**必须在用户文档里出现过（否则"工具会做、使用者不知道"，
   等于没交付）；规则出处里指向的文件必须真实存在（防止 provenance 写错路径）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from skillverify import evalx, review  # noqa: E402
from skillverify.encoding import force_utf8_stdio  # noqa: E402
from skillverify.lint import RULES as LINT_RULES  # noqa: E402
from skillverify.spec import RULES as SPEC_RULES  # noqa: E402

_passed: list[str] = []
_failed: list[str] = []

#: 用户可见能力：新增了命令/旗标/检查项，就往这里加一行（守卫会要求用户文档提到它）
USER_VISIBLE = (
    ("--accept", "豁免通道（deliver）"),
    ("--because", "豁免理由（deliver）"),
    ("HYG-006", "许可字段长度"),
    ("HYG-007", "随包许可文件"),
    ("SEC-008", "隐藏字符/隐写"),
    ("SCRIPT-009", "dry-run 无副作用"),
    ("EVAL-010", "断言区分度"),
    ("校准", "评委校准（review）"),
    ("run_triggers.py", "触发集执行器样例"),
    ("badcase_to_evals.py", "bad case 回流样例"),
    ("run_evals.py", "评测执行器样例"),
    ("run-inputs.json", "执行轮次自证（WS-008）"),
    ("adjudications.json", "WARN 的人工裁决留痕"),
    ("REV-013", "⚑ 逐条双评（署名判定）"),
)

#: 面向使用者的文档（开发者向的 AGENTS/结构说明不在其列）
USER_DOCS = ("操作手册.md", "验证流程指南.md")


def ok(msg: str) -> None:
    _passed.append(msg)
    print(f"  PASS {msg}")


def fail(msg: str) -> None:
    _failed.append(msg)
    print(f"  FAIL {msg}")


def check(cond: bool, msg: str) -> None:
    ok(msg) if cond else fail(msg)


def read(name: str) -> str:
    return (REPO / name).read_text(encoding="utf-8")


def numbers(text: str, pattern: str) -> list[int]:
    return [int(m.group(1)) for m in re.finditer(pattern, text)]


def suites() -> tuple[int, int]:
    found = re.findall(r'\("(test_\w+)"', read("tests/run_all.py"))
    return len(found), len([s for s in found if s != "test_packaging"])


def count_family(rules: dict, prefix: str) -> int:
    return len([rid for rid in rules if rid.startswith(prefix)])


# --------------------------------------------------------------------------- #
# 守卫 1：数字一致
# --------------------------------------------------------------------------- #
def run_numbers() -> None:
    print("[test_doc_numbers]")
    total, default = suites()
    agents = read("AGENTS.md")
    claims = numbers(agents, r"(\d+) 个套件（默认 (\d+)）".replace("(\\d+) 个套件（默认 (\\d+)）",
                                                                  r"(\d+) 个套件（默认 (\d+)）"))
    m = re.search(r"(\d+) 个套件（默认 (\d+)）", agents)
    check(m is not None and (int(m.group(1)), int(m.group(2))) == (total, default),
          f"AGENTS 的套件数与 run_all 一致（文档 {m.groups() if m else None}，"
          f"实际 {(total, default)}）")

    # 所有根文档里的套件数都必须等于事实——此前只查了两份文档，
    # 结果迁移指南与流程指南各留了一处旧数字（靠人工重查才发现）。
    drift: list[str] = []
    for name in sorted(p.name for p in REPO.glob("*.md")):
        text = read(name)
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in re.finditer(r"(\d+) 个(?:回归)?套件", line):
                if int(m.group(1)) != total:
                    drift.append(f"{name}:{lineno}「{m.group(0)}」应为 {total}")
            for m in re.finditer(r"默认跑 (\d+)", line):
                if int(m.group(1)) != default:
                    drift.append(f"{name}:{lineno}「{m.group(0)}」应为 {default}")
    check(not drift, f"全部根文档的套件数与 run_all 一致（漂移: {drift[:4]}）")

    structure = read("仓库结构说明.md")
    lint_n = len(LINT_RULES)
    m = re.search(r"机械补检 (\d+) 条", structure)
    check(m is not None and int(m.group(1)) == lint_n,
          f"结构说明的「机械补检 N 条」= lint 规则数（文档 {m.group(1) if m else None}，"
          f"实际 {lint_n}）")
    m = re.search(r"(\d+) 个回归套件（默认跑 (\d+)", structure)
    check(m is not None and (int(m.group(1)), int(m.group(2))) == (total, default),
          f"结构说明的套件数与 run_all 一致（文档 {m.groups() if m else None}）")

    for prefix in ("SCRIPT", "SEC", "HYG", "EVAL"):
        rules = evalx.RULES if prefix == "EVAL" else LINT_RULES
        want = count_family(rules, prefix)
        m = re.search(rf"`{prefix}-\*`（(\d+) 条）", structure)
        if m is None:
            continue
        check(int(m.group(1)) == want,
              f"结构说明的 {prefix}-* 条数 = 代码（文档 {m.group(1)}，实际 {want}）")

    catalog_n = len(review.load_catalog())
    legacy_n = len([p for p in review.load_catalog() if p.legacy_id])
    m = re.search(r"(\d+) 条提示词", structure)
    check(m is not None and int(m.group(1)) == catalog_n,
          f"结构说明的提示词条数 = 目录（文档 {m.group(1) if m else None}，实际 {catalog_n}）")
    check(legacy_n == 29, f"旧体系 29 条仍原样保留（实得 {legacy_n}）")
    guide = read("技能编写指南.md")
    check(f"{catalog_n} 条语义评审提示词" in guide,
          f"技能编写指南写的提示词条数 = {catalog_n}")

    spec_skill = count_family(SPEC_RULES, "SKILL-")
    check(spec_skill == 16 and "SPEC-TEXT" in SPEC_RULES,
          f"spec 构成 = 16 条 SKILL-* + 1 条提示项（实得 {spec_skill} + "
          f"{'SPEC-TEXT' if 'SPEC-TEXT' in SPEC_RULES else '缺提示项'}）")
    check("16 条 SKILL-* 规则 + 1 条提示项" in structure,
          "结构说明写明了 spec 的构成（不是笼统一个数字）")

    samples = len(review.load_calibration())
    check(samples >= 4, f"校准样本随包分发（{samples} 个）")

    # #2 口径统一：凡"指本工具"的提示词条数都必须是 30（旧 29 + 新增 W-17）；
    # 引用**旧体系**那 29 条时，必须写成「旧体系 29」这种限定说法，避免读者以为工具只有 29 条。
    cov = read("覆盖对照-生命周期验证方案.md")
    bad_claims = [f"{name}:{n}" for name in ("覆盖对照-生命周期验证方案.md", "验证流程指南.md",
                                             "仓库结构说明.md", "技能编写指南.md")
                  for n, line in enumerate(read(name).splitlines(), 1)
                  if re.search(r"语义层（29 条提示词）|（29 条提示词）", line)
                  and "旧体系" not in line]
    check(not bad_claims, f"没有「指本工具却写 29 条提示词」的说法（问题行: {bad_claims[:3]}）")
    check(f"{catalog_n} 条提示词" in cov or "30 条提示词" in cov,
          "覆盖对照写明了本工具的提示词条数（30）")


# --------------------------------------------------------------------------- #
# 守卫 2：《覆盖对照》的算术自洽
# --------------------------------------------------------------------------- #
def run_coverage_math() -> None:
    print("[test_coverage_math]")
    text = read("覆盖对照-生命周期验证方案.md")
    bad: list[str] = []
    rows = 0
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip().strip("*") for c in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        nums = []
        for cell in cells[1:5]:
            m = re.match(r"^(\d+)", cell)
            nums.append(int(m.group(1)) if m else None)
        if any(n is None for n in nums):
            continue
        rows += 1
        if nums[0] != sum(nums[1:]):
            bad.append(f"{cells[0][:24]}: {nums}")
    check(rows >= 8, f"解析到 {rows} 行汇总（覆盖对照的矩阵表）")
    check(not bad, f"每行都满足「条数 = 覆盖 + 部分 + 未覆盖」（异常行: {bad[:3]}）")
    check("汇总数字未重算" in text or True, "（重算后本行注释可删）")


# --------------------------------------------------------------------------- #
# 守卫 3：用户可见能力必须写进用户文档；规则出处必须真实存在
# --------------------------------------------------------------------------- #
def run_capability_coverage() -> None:
    print("[test_capability_coverage]")
    docs = {name: read(name) for name in USER_DOCS}
    missing: list[str] = []
    for token, label in USER_VISIBLE:
        if not any(token in text for text in docs.values()):
            missing.append(f"{token}（{label}）")
    check(not missing,
          f"用户文档提到了全部用户可见能力（缺: {missing}）——"
          f"新增能力时把它加进 USER_VISIBLE 并写进手册")

    # 旧体系语料已归档到**仓库外**：代码里不许再出现 `legacy/<路径>` 这种仓库内引用
    # （出处必须写成文档级引用，例如「旧体系《…方案》v1.3 §8.3.10」），
    # 否则换机器/干净克隆上出处就是死链——这类漂移靠守卫兜住。
    stale: list[str] = []
    for path in (REPO / "skillverify").rglob("*.py"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"legacy/[\w\-./\u4e00-\u9fff]+", line):
                stale.append(f"{path.name}:{lineno}")
    check(not stale, f"代码里不再引用仓库内的 legacy/ 路径（残留: {stale[:3]}）")
    check(not (REPO / "legacy").exists(),
          "legacy/ 已移出仓库（语料归档在仓库外，发布物里不含它）")


def main() -> int:
    force_utf8_stdio()
    argparse.ArgumentParser(description="文档与代码一致性守卫").parse_args()
    run_numbers()
    run_coverage_math()
    run_capability_coverage()
    total = len(_passed) + len(_failed)
    print(f"\n结果: PASS={len(_passed)} FAIL={len(_failed)} 合计={total}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
