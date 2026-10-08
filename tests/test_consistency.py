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

from skillverify import (  # noqa: E402
    audit, discover, evalx, library, material, mount, review, runner, trigger,
)
from skillverify.encoding import force_utf8_stdio  # noqa: E402
from skillverify.lint import RULES as LINT_RULES  # noqa: E402
from skillverify.spec import RULES as SPEC_RULES  # noqa: E402

_passed: list[str] = []
_failed: list[str] = []
_skipped: list[str] = []

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
    ("assertions_added_at", "断言写入时机的显式声明（EVAL-011）"),
    ("adjacency.md", "相邻技能边界清单（review material，W-11 的材料）"),
    ("adjudications.json", "WARN 的人工裁决留痕"),
    ("REV-013", "⚑ 逐条双评（署名判定）"),
    ("R-03", "bad case 回流为评测用例（本项目新增提示词）"),
    ("E-11", "跨宿主/模型差异归因（本项目新增提示词）"),
)

#: 面向使用者的文档（开发者向的 AGENTS/结构说明不在其列）
USER_DOCS = ("操作手册.md", "验证流程指南.md")


def ok(msg: str) -> None:
    _passed.append(msg)
    print(f"  PASS {msg}")


def fail(msg: str) -> None:
    _failed.append(msg)
    print(f"  FAIL {msg}")


def skip(msg: str) -> None:
    """本项**未执行**（环境或前置条件缺失）：既不算通过、也不算失败。"""
    _skipped.append(msg)
    print(f"  SKIP {msg}")


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

    # #2 口径统一：凡"指本工具"的提示词条数都必须等于目录事实；引用**旧体系**那 29 条时，
    # 必须写成「旧体系 29」这种限定说法。**说法的每个变体都由 run_prompt_counts 对账**
    # （此前只查「N 条提示词」一种写法，换个说法就绕过守卫）。
    cov = read("覆盖对照-生命周期验证方案.md")
    check(f"{catalog_n} 条提示词" in cov,
          f"覆盖对照写明了本工具的提示词条数（{catalog_n}）")

    # 逐族规则数：《覆盖对照》里那两处「机械层（N 条规则：spec a / lint b / 评测 c / …）」
    # 此前一直没人查，于是长期写着 评测 29 / 评审 13 / 库级·挂载·审计 15（合计对、分项全错）。
    # 这里把它与代码事实对账——**合计对了不代表分项对了**，而分项正是读者判断
    # 「哪一层做了多少」的依据。
    families = {
        "spec": len(SPEC_RULES),
        "lint": len(LINT_RULES),
        "评测": len(evalx.RULES),
        "触发": len(trigger.RULES),
        "评审": len(review.RULES),
        "材料·执行器": len(material.RULES) + len(runner.RULES),
        "发现": len(discover.RULES),
        "库级·挂载·审计": len(library.RULES) + len(mount.RULES) + len(audit.RULES),
    }
    pattern = (r"(\d+) 条规则[（(：:]\s*spec (\d+) / lint (\d+) / 评测 (\d+) / 触发 (\d+)"
               r" / 评审 (\d+) / 材料·执行器 (\d+) / 发现 (\d+) / 库级·挂载·审计 (\d+)")
    hits = list(re.finditer(pattern, cov))
    check(len(hits) >= 2, f"《覆盖对照》里能找到逐族规则数（找到 {len(hits)} 处）")
    reported = {}
    for m in hits:
        declared_total = int(m.group(1))
        declared = dict(zip(families, (int(m.group(i)) for i in range(2, 10))))
        check(declared_total == sum(declared.values()),
              f"逐族规则数之和 = 声明的总数（{declared_total} vs {sum(declared.values())}）")
        check(declared == families,
              f"逐族规则数与代码一致（文档 {declared}，实际 {families}）")
    # 总数必须等于**全仓** RULES 之和：分族表漏掉一个模块（早先漏过 DISC-* 与 MAT/RUN），
    # 合计就会静默偏小——这是"合计对不代表分项对"的镜像（分项全了、分母却缺一块）。
    all_rules = sum(families.values())
    check(all_rules == 143,
          f"规则总数 = 143（全仓 RULES 之和，实得 {all_rules}）——加规则时要同步文档")


# --------------------------------------------------------------------------- #
# 守卫 1b：「本工具有几条提示词」的说法变体全覆盖
# --------------------------------------------------------------------------- #
#: 总数说法的写法（每条 = 数字在第几组）。此前只认「N 条提示词」，
#: 于是同一件事换个说法就绕过守卫——实测加 W-17 之后这 6 处一直写着旧数字：
#: 「看全部 29 条」「默认 29 条」「（29 条，每条带…）」「29 条带判据的提示词」「W 组 16 条」。
_PROMPT_TOTAL_RES = (
    r"(\d+)\s*条(?:语义评审|评审|带判据的)?提示词",        # 32 条提示词 / 32 条带判据的提示词
    r"提示词(?:目录|清单)[^\n]{0,6}?[（(]\s*(\d+)\s*条",   # 提示词目录（32 条
    r"(?:全部|默认)\s*(\d+)\s*条",                          # 看全部 32 条 / 默认 32 条
    r"(\d+)\s*条[，,]\s*每条带",                            # 32 条，每条带 PASS/FAIL
)
#: 只在**提示词语境**里判「全部/默认 N 条」——否则「全部 143 条规则」会被当成提示词条数
_PROMPT_SCOPE_RE = re.compile(r"提示词|语义评审|review\s+prompts|review\s+pack|--family")
#: 家族说法的写法：(正则, 家族字母/阶段名所在组, 数字所在组)
_FAMILY_COUNT_RES = (
    (r"([DWER])\s*组\s*(\d+)\s*条", 1, 2),                          # W 组 16 条提示词
    (r"--family\s+([DWER])[^\n]{0,24}?(\d+)\s*条", 1, 2),            # --family W 只看编写期 17 条
    (r"只看(编写期|测试期|运行期|设计期)[^\d]{0,8}(\d+)\s*条", 1, 2),  # 只看编写期那 17 条
)
_STAGE_TO_FAMILY = {stage: fam for fam, stage in review.FAMILY_STAGE.items()}
#: 限定语：写了它说明这个数字讲的是**历史来源**（旧体系 / 合并 / 本项目新增），不是当前总口径
_SCOPE_RE = re.compile(r"旧体系|旧方案|legacy|合并为|合并成|本项目新增|另有")


def _scoped(line: str, m: re.Match, *, before_only: bool) -> bool:
    """这个数字有没有被显式限定为历史来源（旧体系/合并/新增）。

    两类说法的窗口方向不同：总数说法的限定语写在数字**前**（「旧体系 29 条」「合并为 16 条」），
    家族说法的限定语跟在数字**后**（「E 组 10 条旧体系提示词」）——所以分别处理，
    而不是"整行出现旧体系就放过"（那会让「30 条提示词（旧体系 29 + 新增 W-17）」这种
    最常见的句子整句豁免，而它恰恰是最该查的一句）。
    """
    left = line[max(0, m.start() - 12):m.start()]
    right = "" if before_only else line[m.end():m.end() + 12]
    return _SCOPE_RE.search(left + right) is not None


def prompt_count_drift(name: str, lineno: int, line: str, total: int,
                       families: dict[str, int], added: int) -> list[str]:
    """一行文本里「提示词条数」写错的地方（空列表 = 这一行没问题）。

    抽成纯函数是为了**能被反向自检**：守卫自己也得能红——喂几行旧数字必须报出来，
    否则"永远不会失败的守卫"和没有守卫一样（本项目反复踩过这条）。
    """
    out: list[str] = []
    if _PROMPT_SCOPE_RE.search(line):
        for pattern in _PROMPT_TOTAL_RES:
            for m in re.finditer(pattern, line):
                if int(m.group(1)) != total and not _scoped(line, m, before_only=True):
                    out.append(f"{name}:{lineno}「{m.group(0)}」应为 {total}")
    for m in re.finditer(r"本项目(?:在[^\n]{0,24}?)?新增(?:了)?\s*(\d+)\s*条", line):
        if int(m.group(1)) != added:
            out.append(f"{name}:{lineno}「{m.group(0)}」应为 {added}")
    for pattern, letter_group, num_group in _FAMILY_COUNT_RES:
        for m in re.finditer(pattern, line):
            key = m.group(letter_group)
            letter = _STAGE_TO_FAMILY.get(key, key)
            want = families.get(letter)
            if want is not None and int(m.group(num_group)) != want \
                    and not _scoped(line, m, before_only=False):
                out.append(f"{name}:{lineno}「{m.group(0)}」应为 {want}（{letter} 族）")
    return out


def run_prompt_counts() -> None:
    """守卫：凡「本工具有几条提示词」的说法都要与目录对账，**说法变体全覆盖**。"""
    print("[test_prompt_counts]")
    catalog = review.load_catalog()
    total = len(catalog)
    families = {f: sum(1 for p in catalog if p.family == f) for f in review.FAMILY_ORDER}
    added = len([p for p in catalog if not p.legacy_id])
    drift: list[str] = []
    for name in sorted(p.name for p in REPO.glob("*.md")):
        for lineno, line in enumerate(read(name).splitlines(), 1):
            drift += prompt_count_drift(name, lineno, line, total, families, added)
    check(not drift,
          f"全部根文档的提示词条数说法 = 目录事实（共 {total} 条，家族 {families}；"
          f"漂移 {len(drift)} 处: {drift[:6]}）")

    # 反向自检：探针必须**真的会红**，豁免项必须真的不红（用当前真实数字，不写死 29/30）
    stale = total - 1
    w = families["W"]
    probes = (
        (f"那部分由 {stale} 条语义评审提示词负责", True),
        (f"skillverify review prompts                 # 看全部 {stale} 条", True),
        (f"skillverify review pack <技能目录>   # 生成任务包（默认 {stale} 条）", True),
        (f"skillverify review prompts --family W      # 只看编写期那 {w - 1} 条", True),
        (f"本项目新增 {added + 1} 条", True),
        ("由旧体系 29 条提示词逐条改写而来", False),
        ("31（合并为 W 组 16 条提示词）", False),
        (f"由 {total} 条语义评审提示词负责（旧体系 29 条 + 本项目新增 {added} 条）", False),
        (f"E 组 10 条旧体系提示词，另有本项目新增的 E-11", False),
    )
    bad = [text for text, want in probes
           if bool(prompt_count_drift("_probe.md", 1, text, total, families, added)) != want]
    check(not bad, f"反向自检：探针行的判定与预期一致（不符 {len(bad)} 条: {bad[:3]}）")


# --------------------------------------------------------------------------- #
# 守卫 1c：根文档里的**仓库内路径引用**不能是死链
# --------------------------------------------------------------------------- #
#: 只认这些仓库目录前缀——`evals/evals.json` 这类是**技能里的示例路径**（教学用），
#: 不在仓库里，上一版扫描把它们全报成"死引用"，是典型的误报。
_DOC_PATH_PREFIXES = ("skillverify/", "tests/", "examples/", ".github/", "handoff/", "legacy/",
                      "data/")


def doc_path_drift(name: str, lineno: int, line: str) -> list[str]:
    """一行文档里指向仓库内、却**不存在**的文件引用（空列表 = 没问题）。

    为什么要有这条：实测抓到过《覆盖对照》开头引 `legacy/归档冻结说明.md`——旧语料早已移出仓库，
    那个文件哪儿都不存在，读者照着找只会扑空（同类还有代码侧 `legacy/<路径>`，那条早有守卫）。
    抽成纯函数是为了能反向自检；通配符（`skillverify/lint/*.py`）与 `data/`（写成
    `skillverify/data/` 的简写）按下面的规则处理，不靠"看起来像"。
    """
    out: list[str] = []
    for m in re.finditer(r"`([^`\n]+)`", line):
        tok = m.group(1).strip().rstrip("/")
        if not tok.startswith(_DOC_PATH_PREFIXES) or "*" in tok:
            continue
        if not re.search(r"\.[A-Za-z0-9]{1,6}$", tok):
            continue
        candidate = REPO / tok
        if not candidate.exists() and tok.startswith("data/"):
            candidate = REPO / "skillverify" / tok     # 文档里常把 data/ 当 skillverify/data/
        if not candidate.exists():
            out.append(f"{name}:{lineno}「{tok}」")
    return out


def run_doc_paths() -> None:
    """守卫：根文档不许引用仓库里不存在的文件（死链会浪费读者的时间，也没人会回头发现）。"""
    print("[test_doc_paths]")
    drift: list[str] = []
    for name in sorted(p.name for p in REPO.glob("*.md")):
        for lineno, line in enumerate(read(name).splitlines(), 1):
            drift += doc_path_drift(name, lineno, line)
    check(not drift, f"根文档引用的仓库内文件都真实存在（死引用: {drift[:5]}）")

    # 反向自检：探针必须一个抓得住、一个放得过（否则这条守卫要么恒真、要么全是误报）
    probes = (
        ("见 `tests/definitely-missing.py`", True),
        ("见 `legacy/归档冻结说明.md`", True),
        ("见 `skillverify/lint/*.py`", False),      # 通配符：不是可解析的具体文件
        ("见 `evals/evals.json`", False),           # 技能里的示例路径，不在仓库里
        ("见 `data/hosts.toml`", False),            # data/ 是 skillverify/data/ 的简写
    )
    bad = [text for text, want in probes
           if bool(doc_path_drift("_probe.md", 1, text)) != want]
    check(not bad, f"反向自检：探针判定与预期一致（不符: {bad[:3]}）")


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


HANDOFF_STATUS_MARK = "## 〇、现状与待办"
#: 除 §〇 以外不许再出现这些标题——它们就是「多处待办互相矛盾」的来源
#: （实测过：旧交接里同时存在「下一步：M5」「下一步（M7）」「阶段计划」三份清单，
#:  新会话照着任一份做都是错的，只能靠重读代码重建现状）。
#: `#{2,3}\s` 的 `\s` 是必需的：没有它，`#### 第八轮：把最后一条待办做掉` 这种
#: **四级小标题**会被 `#{2,3}` 吞掉前缀后误判成竞争者（本守卫第一次上阵就误报了一次）。
HANDOFF_RIVAL_RE = re.compile(r"^#{2,3}\s.*(现状|待办|下一步|启动指令|从这里开始)")
#: §〇 里必须被守卫核对的结构数字：(标签, 正则, 期望值取法)
HANDOFF_FACTS = ("套件", "命令", "机械规则", "语义提示词")


def run_handoff() -> None:
    """守卫 **交接文档**：它是跨会话唯一的记忆，不能靠自觉保持准确。

    两条（都对着本次踩过的坑）：
    1. 只有**一处**「现状/待办」标题——多处清单必然互相矛盾；
    2. §〇 里的结构数字（套件/命令/规则/提示词）与代码事实一致。
    `handoff/` 不在时跳过（它已 gitignore，别的机器上没有）。
    """
    print("[test_handoff]")
    path = REPO / "handoff" / "会话交接-2026-10-04.md"
    if not path.is_file():
        skip("handoff/ 不存在（本地会话目录，未随仓库分发）：交接守卫未执行")
        return
    text = path.read_text(encoding="utf-8")
    heads = [line for line in text.splitlines() if HANDOFF_RIVAL_RE.match(line)]
    # 「历史：…（已被 §〇 取代）」这类**指回 §〇**的标题不算竞争者：它们不含活的口径
    rival = [line for line in heads if not re.search(r"历史|已被 §〇 取代|见 §〇", line)]
    check(len(rival) == 1 and rival[0].startswith(HANDOFF_STATUS_MARK),
          f"交接文档只有 §〇 一处「现状/待办」标题（实得 {len(rival)} 处：{rival[:3]}）")

    total, _default = suites()
    facts = {
        "套件": total,
        "命令": _command_count(),
        "机械规则": len(SPEC_RULES) + len(LINT_RULES) + len(evalx.RULES) + len(trigger.RULES)
                  + len(review.RULES) + len(material.RULES) + len(runner.RULES)
                  + len(library.RULES) + len(mount.RULES) + len(audit.RULES)
                  + len(discover.RULES),
        "语义提示词": len(review.load_catalog()),
    }
    # 只认一种写法（`套件 **14**`）：§〇 的格式由本守卫固定，省得"对上了但没人看得懂"
    missing = [f"{name}={want}" for name, want in facts.items()
               if f"{name} **{want}**" not in text]
    check(not missing, f"§〇 的结构数字与代码一致（不符: {missing}）")


def _command_count() -> int:
    """CLI 顶层子命令数（11 个）：只数 `sub.add_parser(` 那一层。

    **别用 `add_parser` 的裸计数**：`hook`/`review` 还有自己的二级子解析器
    （`hook_sub` / `review_sub`），裸计数会得到 18。
    """
    text = read("skillverify/cli/__init__.py")
    return len(set(re.findall(r"^\s*p_\w+ = sub\.add_parser\(\s*\n?\s*\"([\w-]+)\"",
                              text, re.MULTILINE)))


def cli_surface() -> tuple[list[str], list[str]]:
    """CLI 的全部子命令与旗标，**从解析器里抠出来**（手抄一份必然漂移）。"""
    import argparse as _ap

    from skillverify.cli import build_parser

    subs: list[str] = []
    flags: list[str] = []

    def walk(parser) -> None:
        for action in parser._actions:  # noqa: SLF001 - 读自己的解析器
            if isinstance(action, _ap._SubParsersAction):  # noqa: SLF001
                for name, sub in action.choices.items():
                    subs.append(name)
                    walk(sub)
            else:
                flags.extend(action.option_strings)

    walk(build_parser())
    return sorted(set(subs)), sorted(set(flags))


def run_cli_coverage() -> None:
    """**正向**覆盖：实现了的每个子命令与旗标，至少在某份根文档里出现过一次。

    已有的 `test_docs` 只查反方向（文档里不许出现不存在的命令/旗标），于是"实现了但没人写"
    这一半从没被查过——实测一次就抓出 **14 个旗标在任何文档里都没有**
    （`--iteration`、`--trace`、`--fail-closed`、`--blind-seed`…）。
    口径是**出现过一次**，但要带词边界：`--blind-seed-X` 不算写了 `--blind-seed`
    （第一次写这条守卫时用的裸子串匹配，反向探针一测就发现它太宽）。不要求逐条解释——
    文档质量机器判不了。
    """
    print("[test_cli_coverage]")
    text = "\n".join(read(name) for name in (
        "技能编写指南.md", "验证流程指南.md", "操作手册.md", "迁移与部署指南.md",
        "仓库结构说明.md", "覆盖对照-生命周期验证方案.md", "AGENTS.md"))

    def mentioned(flag: str) -> bool:
        # 尾巴上不许再跟字母/数字/短横线：`--iteration` 不能靠 `--iteration-x` 蒙过去
        return re.search(re.escape(flag) + r"(?![\w-])", text) is not None

    subs, flags = cli_surface()
    # `-h` 是 argparse 自带的简写（文档写 `--help` 就够），不单独要求
    flags = [f for f in flags if f != "-h"]
    check(len(subs) >= 11 and len(flags) >= 40,
          f"抠到 CLI 表面：{len(subs)} 个子命令 / {len(flags)} 个旗标")
    missing_subs = [s for s in subs if s not in text]
    missing_flags = [f for f in flags if not mentioned(f)]
    check(not missing_subs, f"每个子命令都在文档里出现过（缺: {missing_subs}）")
    check(not missing_flags, f"每个旗标都在文档里出现过（缺: {missing_flags}）")
    # 反向自检：匹配不是恒真的——编一个没人写的旗标，必须被判为缺失
    check(not mentioned("--definitely-not-a-real-flag"),
          "这条守卫能失败（探针旗标被判为缺失）")


def run_agents_counts() -> None:
    """《仓库结构说明》里写死的 AGENTS 条目数，必须与 AGENTS.md 的真实条目数一致。

    为什么单独立一条：同一个数字**在本会话里漂移了两次**（加坑 15/16 后还写 14；加了 17 又漏改 16）。
    "人写的数字"与"机器知道的事实"对账，正是这个项目反复强调的那条——那就别靠自觉。
    """
    print("[test_agents_counts]")
    agents = read("AGENTS.md")
    struct = read("仓库结构说明.md")

    def count_between(start: str, end: str) -> int:
        body = agents.split(start)[1].split(end)[0]
        return len(re.findall(r"^\d+\. \*\*", body, re.MULTILINE))

    pitfalls = count_between("## 五、", "## 六、")
    invariants = count_between("## 三、", "## 四、")
    hit = re.search(r"(\d+) 个已踩过的坑", struct)
    check(hit is not None, "《仓库结构说明》写了 AGENTS 的坑计数")
    if hit:
        check(int(hit.group(1)) == pitfalls,
              f"坑计数与 AGENTS 实际一致（结构说明写 {hit.group(1)}，实际 {pitfalls} 条）")
    hit2 = re.search(r"(\d+) 条不许破坏的不变量", struct)
    if hit2:
        check(int(hit2.group(1)) == invariants,
              f"不变量计数一致（结构说明写 {hit2.group(1)}，实际 {invariants} 条）")
    check(pitfalls >= 17 and invariants >= 11,
          f"抠到的条目数合理（坑 {pitfalls} / 不变量 {invariants}）")


def main() -> int:
    force_utf8_stdio()
    argparse.ArgumentParser(description="文档与代码一致性守卫").parse_args()
    run_numbers()
    run_prompt_counts()
    run_doc_paths()
    run_coverage_math()
    run_capability_coverage()
    run_handoff()
    run_cli_coverage()
    run_agents_counts()
    total = len(_passed) + len(_failed)
    print(f"\n结果: PASS={len(_passed)} FAIL={len(_failed)} SKIP={len(_skipped)} 合计={total}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
