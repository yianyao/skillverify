"""evalx —— 评测资产校验（官方 evals.json 与评测工作区产物）。

**为什么这一层必须单独存在**：官方评估页给出了一整套硬约定（文件路径、键名、类型、
聚合口径），但官方**没有任何工具**校验它们；旧体系用两个 36KB 的工具各查一半，
还留了"只看前 20 条断言""样例目录一律降级为 WARN"这类后门，导致报告会安静地骗人。

**官方条款**（逐条溯源，见每条规则的 source）：
https://agentskills.io/skill-creation/evaluating-skills

资产形态（官方原文的形状）：
- `evals/evals.json`（**手工编写**，技能目录内）
  `{"skill_name": str, "evals": [{"id", "prompt", "expected_output",
                                  "files"?: [str], "assertions"?: [str]}]}`
- 工作区（**运行期产物**，位于技能目录**旁边**，官方示例命名 `<技能名>-workspace/`）：
  `iteration-N/eval-<名>/{with_skill, without_skill|old_skill}/{outputs/, timing.json, grading.json}`
  + `iteration-N/benchmark.json` + `feedback.json`
- `timing.json` = `{"total_tokens": int, "duration_ms": int}`
- `grading.json` = `{"assertion_results": [{"text", "passed", "evidence"}],
                     "summary": {"passed","failed","total","pass_rate"}}`
- `benchmark.json` = `{"run_summary": {with_skill:{pass_rate:{mean,stddev},
                     time_seconds:{mean,stddev}, tokens:{mean,stddev}}, <基线>: {...},
                     delta: {pass_rate, time_seconds, tokens}}}`
- `feedback.json` = `{"<eval 目录名>": "<反馈文本，空串表示这条没问题>"}`

**刻意不做的后门**（旧体系的教训）：
- 不做"前 N 条断言只看一部分"——那等于把大文件里的错误藏起来；
- 不做"位于 references//assets/ 就降级为 WARN"——真坏掉的样例永远不算错；
- 不把"断言文本与 eval 对不上"当 FAIL：官方没有定义 eval 目录名与 eval id 的映射，
  机械层只能按文本做集合比对，故记 WARN 并说清理由。

**关于 BOM**：工作区文件在技能目录之外，lint 的 ENC 族扫不到，因此这里用 `utf-8-sig`
宽容读取（不因 BOM 报"JSON 语法错误"，那是误导性报错）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .encoding import read_json, read_text
from .report import FAIL, INFO, PASS, SKIP, WARN, Report, Result, Rule
from .spec import find_skill_md

_EVAL = "https://agentskills.io/skill-creation/evaluating-skills"
_EVAL_JSON = _EVAL + "#designing-test-cases"
_WS = _EVAL + "#workspace-structure"
_GRADING = _EVAL + "#grading-outputs"
_BENCH = _EVAL + "#aggregating-results"
_FEEDBACK = _EVAL + "#reviewing-results-with-a-human"

#: 工作区目录命名（官方示例：与技能目录并列的 `<技能名>-workspace/`）
WORKSPACE_SUFFIX = "-workspace"

#: 迭代目录
ITERATION_RE = re.compile(r"^iteration-(\d+)$")
EVAL_DIR_RE = re.compile(r"^eval-(.+)$")

#: 臂目录：with_skill = 带技能；without_skill = 无技能基线；old_skill = 旧版技能基线
ARM_MAIN = "with_skill"
ARM_BASELINES = ("without_skill", "old_skill")

#: 聚合时容许的相对/绝对误差（官方示例里的 delta 是四舍五入过的）
TOL_ABS = 0.011
TOL_REL = 0.02

#: 官方点名的"空洞/脆弱"断言措辞（机械初筛，命中须人工判断）
VAGUE_ASSERTION_RE = re.compile(
    r"^\s*(?:the\s+)?output\s+(?:is|looks)\s+(?:good|fine|ok|okay|nice|correct)\s*[.。]?\s*$"
    r"|^\s*(?:looks?\s+good|works?\s+well|没问题|看着不错|效果不错)\s*[.。]?\s*$"
    # 中文里最常见的空洞断言形态：「输出是好的」「结果正确」「功能正常」——
    # 规则自己的整改文案就点名了「输出是好的」，正则里必须有它，否则规则抓不到自己说的例子
    r"|^\s*(?:输出|结果|效果|功能|表现)(?:是|看起来|看着)?"
    r"(?:好的?|正常的?|正确的?|对的?|没错|没问题|可以|还行|不错|能用|可用)"
    r"\s*[.。]?\s*$",
    re.I,
)
BRITTLE_ASSERTION_RE = re.compile(r"exactly\s+the\s+phrase|逐字包含|一字不差", re.I)

#: 委托执行的评测命令失败时的整改提示
RUN_HINT = (
    "看命令输出的最后几行。评测的**执行**由官方 skill-creator 或你的宿主负责，"
    "本工具只校验产物；命令不对（路径/参数/环境）时先修命令再重跑"
)

#: 判定"恒真/恒假"所需的最少观测次数（少于它不足以说明没有区分度）
MIN_ASSERTION_OBSERVATIONS = 3


#: 执行轮次自证文件（放在每个 iteration 目录下）
RUN_INPUTS_NAME = "run-inputs.json"

#: 允许的隔离级别。**「降级」「未执行」不是失败，但必须写出来**——
#: 那一轮的数据只能当「参考级证据」，不许被算成技能带来的增益。
ISOLATION_LEVELS = ("隔离", "降级", "未执行")

#: 断言写入时机的**显式声明字段**（写在 iteration-N/ 的 run-inputs.json 里）。
#:
#: 为什么只认显式声明：旧实现比较文件 mtime 来推断「断言是什么时候补的」——复制、克隆、
#: 任何一次重写都会改掉 mtime，而「断言是不是看过输出之后才写的」这件事**根本不在文件系统里**。
#: 所以这里不猜：声明了就读出来登记，没声明就记 INFO（不适用）。EVAL-011。
ASSERTIONS_TIME_FIELD = "assertions_added_at"
#: 同一份自证里可选的「本轮输出产出时间」，用来给出先后关系。
#: 注意：给出先后关系**不等于**判定好坏——官方明确允许"先跑一轮再补断言"，
#: 而"先写断言再跑"同样有它的道理；本项只登记事实，不替使用者选一种流程。
OUTPUTS_TIME_FIELD = "outputs_produced_at"


RULES: dict[str, Rule] = {
    # ---- evals/evals.json ----
    "EVAL-000": Rule(
        "EVAL-000",
        "技能提供评测资产（evals/evals.json）",
        "HOUSE",
        _EVAL_JSON,
        "先写 2–3 条用例：真实用户会说的话 + 「成功长什么样」；跑一轮之后再补断言",
    ),
    "EVAL-001": Rule(
        "EVAL-001",
        "evals/evals.json 可解析为 JSON 对象",
        "SHOULD",
        _EVAL_JSON,
        "修掉 JSON 语法错误；文件必须以 UTF-8 保存",
    ),
    "EVAL-002": Rule(
        "EVAL-002",
        "必填键 skill_name（字符串）与非空数组 evals",
        "SHOULD",
        _EVAL_JSON,
        "按官方形状补齐 `skill_name` 与 `evals`",
    ),
    "EVAL-003": Rule(
        "EVAL-003",
        "每条 eval 的必填字段 id / prompt / expected_output",
        "SHOULD",
        _EVAL_JSON,
        "补齐字段；prompt 写真实用户会说的话，expected_output 写清「成功长什么样」",
    ),
    "EVAL-004": Rule(
        "EVAL-004",
        "可选字段类型：files / assertions 为字符串数组",
        "SHOULD",
        _EVAL_JSON,
        "改为字符串数组；assertions 每条是一句可判定的陈述",
    ),
    "EVAL-005": Rule(
        "EVAL-005",
        "files 列出的输入文件必须存在（相对技能根）",
        "SHOULD",
        _EVAL_JSON,
        "补上输入文件或修正路径（官方示例为 `evals/files/<名>`）",
    ),
    "EVAL-006": Rule(
        "EVAL-006",
        "eval id 唯一",
        "HOUSE",
        "本项目收紧：官方未显式要求唯一，但重复 id 无法定位用例",
        "把重复的 id 改掉（保留它们在报告与工作区目录名里的可追溯性）",
    ),
    "EVAL-007": Rule(
        "EVAL-007",
        "skill_name 与技能名一致",
        "HOUSE",
        "本项目收紧：官方未要求，但多半是从别的技能复制过来忘了改",
        "改成当前技能的名字（frontmatter 的 name）",
    ),
    "EVAL-008": Rule(
        "EVAL-008",
        "evals 非空（官方建议 2–3 条起步）",
        "HOUSE",
        _EVAL_JSON,
        "先写 2–3 条互不重复的用例；覆盖至少一个边界情况",
    ),
    "EVAL-009": Rule(
        "EVAL-009",
        "断言措辞避开官方点名的空洞/脆弱写法",
        "HOUSE",
        _EVAL + "#writing-assertions",
        "空洞断言（「输出是好的」）无法判定；脆弱断言（逐字匹配某句话）会误杀正确输出",
    ),
    # ---- grading.json ----
    "GRAD-001": Rule(
        "GRAD-001",
        "grading.json 结构：assertion_results 数组 + summary 对象",
        "SHOULD",
        _GRADING,
        "按官方形状补齐 `assertion_results` 与 `summary`",
    ),
    "GRAD-002": Rule(
        "GRAD-002",
        "每条断言结果含 text（字符串）/ passed（布尔）/ evidence（字符串）",
        "SHOULD",
        _GRADING,
        "补齐三个字段；`passed` 必须是 JSON 布尔值，不能用字符串",
    ),
    "GRAD-003": Rule(
        "GRAD-003",
        "summary 与逐条结果一致（total = passed + failed；pass_rate = passed/total）",
        "SHOULD",
        _GRADING,
        "按逐条结果重算 summary（官方示例的 pass_rate 是小数）",
    ),
    "GRAD-004": Rule(
        "GRAD-004",
        "PASS 必须有实质 evidence；FAIL 的 evidence 不得为空",
        "SHOULD",
        _GRADING + "（“Require concrete evidence for a PASS”）",
        "evidence 要引用/摘录输出内容，而不是复述断言",
    ),
    "GRAD-005": Rule(
        "GRAD-005",
        "断言的 text 应能在 evals.json 的 assertions 中找到",
        "HOUSE",
        "本项目收紧：官方未定义 eval 目录名与 eval id 的映射，只能按文本比对",
        "要么把断言写回 evals.json，要么确认这条断言是评分时新加的并补录",
    ),
    # ---- timing.json ----
    "TIME-001": Rule(
        "TIME-001",
        "timing.json：total_tokens / duration_ms 为非负整数",
        "SHOULD",
        _BENCH,
        "按官方形状写成整数；布尔值不算整数（Python 里 True 是 int，别被骗）",
    ),
    # ---- benchmark.json ----
    "BENCH-001": Rule(
        "BENCH-001",
        "benchmark.json 含 with_skill 与基线（without_skill/old_skill）的 run_summary",
        "SHOULD",
        _BENCH,
        "补齐两侧配置；没有基线就无法回答「技能到底有没有用」",
    ),
    "BENCH-002": Rule(
        "BENCH-002",
        "mean / stddev 为数值且 stddev ≥ 0",
        "SHOULD",
        _BENCH,
        "改为数值；stddev 缺失时应说明是单次运行（官方：方差只在多次运行时才有意义）",
    ),
    "BENCH-003": Rule(
        "BENCH-003",
        "delta 与两侧 mean 之差一致（容许四舍五入）",
        "SHOULD",
        _BENCH,
        "按 `with_skill.mean - 基线.mean` 重算 delta",
    ),
    "BENCH-004": Rule(
        "BENCH-004",
        "聚合值与逐次产物一致（pass_rate / time_seconds / tokens）",
        "SHOULD",
        _BENCH,
        "按各 arm 的 grading.json 与 timing.json 重算聚合值——不一致说明有人手改过或漏跑",
    ),
    "BENCH-005": Rule(
        "BENCH-005",
        "方差的可解释性（每个配置的运行次数）",
        "HOUSE",
        _BENCH + "（“stddev is only meaningful with multiple runs per eval”）",
        "单次运行时不要读 stddev，只看 pass 计数与 delta；要方差就多跑几次",
    ),
    "BENCH-006": Rule(
        "BENCH-006",
        "增益方向：with_skill 的 pass_rate 不低于基线",
        "HOUSE",
        _EVAL + "#analyzing-patterns",
        "技能没体现出增益：先看是不是断言太容易（两边都过），再考虑技能本身是否值得保留",
    ),
    # ---- 工作区结构 ----
    "WS-001": Rule(
        "WS-001",
        "工作区含 iteration-N 目录",
        "SHOULD",
        _WS,
        "按官方结构建 `iteration-1/`；每轮迭代一个目录",
    ),
    "WS-002": Rule(
        "WS-002",
        "每个 eval 目录同时具备 with_skill 与基线 arm",
        "SHOULD",
        _WS,
        "补齐基线（无技能用 `without_skill/`，改版对比用 `old_skill/`）",
    ),
    "WS-003": Rule(
        "WS-003",
        "每个 arm 目录含 outputs/ 与 timing.json",
        "SHOULD",
        _WS,
        "补齐该次运行的产物目录与计时文件",
    ),
    "WS-004": Rule(
        "WS-004",
        "iteration 编号从 1 开始且无缺号",
        "HOUSE",
        _WS,
        "重编号或补上缺失的那一轮——缺号会让「哪轮改了什么」无法追溯",
    ),
    "WS-005": Rule(
        "WS-005",
        "同一 eval 目录下各 arm 的断言集合一致",
        "HOUSE",
        _WS,
        "两侧必须按同一组断言评分，否则 pass_rate 不可比",
    ),
    "WS-006": Rule(
        "WS-006",
        "每个 iteration 有 benchmark.json",
        "SHOULD",
        _BENCH,
        "补上该轮的聚合结果（缺了就只剩逐条结果，无法看趋势）",
    ),
    "WS-007": Rule(
        "WS-007",
        "feedback.json 结构（若存在）",
        "SHOULD",
        _FEEDBACK,
        "按官方形状写：`{\"<eval 目录名>\": \"<反馈，空串表示没问题>\"}`",
    ),
    "EVAL-010": Rule(
        "EVAL-010",
        f"断言要有区分度（不得恒真/恒假，观测 ≥{MIN_ASSERTION_OBSERVATIONS} 次）",
        "HOUSE",
        "旧体系 E-05（断言难度复核）的机械部分；官方规范未覆盖",
        "恒真的断言换成更具体的判定（把「输出是好的」写成「输出列出 3 个月份且带数值」）；"
        "恒假的先查判据是否写反或环境是否满足",
    ),
    "WS-008": Rule(
        "WS-008",
        "每轮要留执行自证（隔离方式 / 执行器 / 输入哈希 / 两臂提示词哈希）",
        "HOUSE",
        "旧体系 §7.2.4 的 run-inputs.md（双跑对照每轮必写，降级/未执行须如实标注并留档作废轮）",
        f"在 iteration-N/ 下放一份 {RUN_INPUTS_NAME}（模板见 examples/）："
        f"写清 isolation（{'/'.join(ISOLATION_LEVELS)}）、executor、input_hash、prompt_hashes。"
        f"做不到隔离就如实写「降级」——那一轮只能当参考级证据，不许算增益",
    ),
    "EVAL-011": Rule(
        "EVAL-011",
        f"断言写入时机只认显式声明（{ASSERTIONS_TIME_FIELD}），不用文件时间推断",
        "HOUSE",
        "旧体系 V21（断言时机）的机械部分——**换机制**：旧实现靠文件 mtime 推断，"
        "本项目不猜时间（复制/克隆/重写都会误判）",
        f"想登记就在 iteration-N/{RUN_INPUTS_NAME} 里写 {ASSERTIONS_TIME_FIELD}"
        f"（ISO 8601 字符串，例如 2026-10-05T11:00:00+08:00），"
        f"可选再写 {OUTPUTS_TIME_FIELD} 让工具给出先后关系；不写就记「未声明」，"
        f"工具不替你推断",
    ),
}


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #


def _is_int(value: object) -> bool:
    """整数判定：**排除 bool**（Python 里 True 是 int 的子类，是典型陷阱）。"""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _summarize(items: list[str], limit: int = 5) -> str:
    if not items:
        return ""
    head = "；".join(items[:limit])
    return head + (f"；等共 {len(items)} 处" if len(items) > limit else "")


def find_workspace(skill_dir: Path, explicit: Path | None = None) -> Path | None:
    """定位评测工作区：显式指定优先，否则找并列的 `<技能名>-workspace/`（官方示例命名）。"""
    if explicit is not None:
        return explicit if explicit.is_dir() else None
    sibling = skill_dir.parent / (skill_dir.name + WORKSPACE_SUFFIX)
    return sibling if sibling.is_dir() else None


@dataclass
class EvalsDoc:
    """evals/evals.json 的解析结果。"""

    path: Path | None = None
    data: dict = field(default_factory=dict)
    entries: list[dict] = field(default_factory=list)
    error: str = ""

    @property
    def present(self) -> bool:
        return self.path is not None

    def assertions(self) -> list[str]:
        out: list[str] = []
        for entry in self.entries:
            for text in entry.get("assertions") or []:
                if isinstance(text, str):
                    out.append(text)
        return out


def _read_evals(skill_dir: Path) -> EvalsDoc:
    path = skill_dir / "evals" / "evals.json"
    if not path.is_file():
        return EvalsDoc()
    doc = EvalsDoc(path=path)
    data, error = read_json(path)
    if error:
        doc.error = error
        return doc
    if not isinstance(data, dict):
        doc.error = f"顶层必须是对象，实为 {type(data).__name__}"
        return doc
    doc.data = data
    entries = data.get("evals")
    if isinstance(entries, list):
        doc.entries = [e for e in entries if isinstance(e, dict)]
    return doc


def _res(rule: Rule, status: str, evidence: str = "") -> Result:
    return Result(
        rid=rule.rid, title=rule.title, status=status, level=rule.level,
        evidence=evidence, remediation=rule.remediation if status in (FAIL, WARN) else "",
    )


#: 识别旧体系方言，把"不符合官方形状"说成可操作的一句话
#: （实测：旧体系语料里的 4 个 `evals/evals.json` 全是 `queries` 方言的触发评测草案；
#: 该语料已归档到仓库外，此处只作经验记录）
_DIALECTS: dict[str, str] = {
    "queries": "顶层是 `queries`（旧体系触发评测查询集草案）",
    "cases": "顶层是 `cases`（旧体系用例方言）",
    "assertions": "顶层是 `assertions`（旧体系方言；官方把 assertions 放在每条 eval 内）",
}


def _dialect(data: dict) -> str | None:
    """返回命中的旧方言键名；official 形状返回 None。"""
    if isinstance(data.get("evals"), list):
        return None
    for key in ("queries", "cases", "assertions"):
        if isinstance(data.get(key), list):
            return key
    return None


def _official_shape_hint(data: dict) -> str:
    key = _dialect(data)
    if key is None:
        return ""
    return (f"；检测到{_DIALECTS[key]}——官方 evals.json 形状是 "
            f"{{skill_name, evals:[{{id, prompt, expected_output, files?, assertions?}}]}}，需迁移")


# --------------------------------------------------------------------------- #
# evals.json
# --------------------------------------------------------------------------- #


def _check_evals_json(skill_dir: Path, doc: EvalsDoc, skill_name: str) -> list[Result]:
    out: list[Result] = []

    if doc.error:
        out.append(_res(RULES["EVAL-001"], FAIL, f"evals/evals.json: {doc.error}"))
        for rid in ("EVAL-002", "EVAL-003", "EVAL-004", "EVAL-005", "EVAL-006",
                    "EVAL-007", "EVAL-008", "EVAL-009"):
            out.append(_res(RULES[rid], SKIP, "未执行：evals.json 无法解析，先修 EVAL-001"))
        return out
    out.append(_res(RULES["EVAL-001"], PASS, "evals/evals.json 可解析为 JSON 对象"))

    data = doc.data
    problems: list[str] = []
    if not isinstance(data.get("skill_name"), str) or not (data.get("skill_name") or "").strip():
        problems.append("skill_name 缺失或不是非空字符串")
    raw_evals = data.get("evals")
    entries: list[dict] = [e for e in raw_evals if isinstance(e, dict)] if isinstance(raw_evals, list) else []
    if not isinstance(raw_evals, list):
        problems.append(f"evals 缺失或不是数组（实为 {type(raw_evals).__name__}）")
    elif not raw_evals:
        problems.append("evals 是空数组")
    out.append(
        _res(RULES["EVAL-002"], FAIL if problems else PASS,
             ("；".join(problems) + _official_shape_hint(data)) if problems
             else f"skill_name={data.get('skill_name')!r}，{len(raw_evals)} 条用例")
    )

    if not entries:
        # 没有可校验的用例时，逐条规则记 SKIP（本项未执行），
        # 而不是记"没有任何用例"的 WARN——那会和 EVAL-002 重复报同一件事。
        reason = "未执行：没有可校验的用例（先修 EVAL-002）"
        for rid in ("EVAL-003", "EVAL-004", "EVAL-005", "EVAL-006",
                    "EVAL-007", "EVAL-008", "EVAL-009"):
            out.append(_res(RULES[rid], SKIP, reason))
        return out

    missing: list[str] = []
    bad_type: list[str] = []
    ids: list[str] = []
    for idx, entry in enumerate(entries, 1):
        label = f"第 {idx} 条"
        for key in ("id", "prompt", "expected_output"):
            if key not in entry:
                missing.append(f"{label} 缺 {key}")
                continue
            value = entry[key]
            if key == "id":
                if not (_is_int(value) or (isinstance(value, str) and value.strip())):
                    bad_type.append(f"{label} 的 id 应为整数或非空字符串（实为 {value!r}）")
                else:
                    ids.append(str(value))
            elif not (isinstance(value, str) and value.strip()):
                bad_type.append(f"{label} 的 {key} 应为非空字符串")
    out.append(
        _res(RULES["EVAL-003"], FAIL if (missing or bad_type) else PASS,
             _summarize(missing + bad_type) if (missing or bad_type)
             else f"{len(entries)} 条用例的必填字段齐备")
    )

    opt_bad: list[str] = []
    files_refs: list[str] = []
    all_assertions: list[str] = []
    for idx, entry in enumerate(entries, 1):
        label = f"第 {idx} 条"
        for key in ("files", "assertions"):
            value = entry.get(key)
            if value is None:
                continue
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                opt_bad.append(f"{label} 的 {key} 应为字符串数组")
                continue
            if key == "assertions" and not value:
                opt_bad.append(f"{label} 的 assertions 是空数组（要么别写，要么写可判定的陈述）")
            if key == "files":
                files_refs.extend(value)
            else:
                all_assertions.extend(value)
    out.append(
        _res(RULES["EVAL-004"], WARN if opt_bad else PASS,
             _summarize(opt_bad) if opt_bad else "可选字段类型均正确")
    )

    missing_files: list[str] = []
    for ref in files_refs:
        if not (skill_dir / ref).exists():
            missing_files.append(ref)
    if not files_refs:
        out.append(_res(RULES["EVAL-005"], INFO, "不适用：没有用例声明输入文件"))
    else:
        out.append(
            _res(RULES["EVAL-005"], FAIL if missing_files else PASS,
                 _summarize([f"{r}（不存在）" for r in missing_files]) if missing_files
                 else f"{len(files_refs)} 个输入文件均存在")
        )

    dupes = sorted({i for i in ids if ids.count(i) > 1})
    out.append(
        _res(RULES["EVAL-006"], WARN if dupes else PASS,
             _summarize([f"id={d} 出现 {ids.count(d)} 次" for d in dupes]) if dupes
             else f"{len(ids)} 个 id 均唯一")
    )

    declared = data.get("skill_name")
    if not isinstance(declared, str) or not declared.strip():
        out.append(_res(RULES["EVAL-007"], INFO, "不适用：skill_name 缺失（见 EVAL-002）"))
    elif skill_name and declared.strip() == skill_name:
        out.append(_res(RULES["EVAL-007"], PASS, f"skill_name 与技能名一致（{skill_name}）"))
    else:
        out.append(_res(RULES["EVAL-007"], WARN,
                        f"skill_name={declared!r} 与技能名 {skill_name!r} 不一致"))

    count = len(raw_evals) if isinstance(raw_evals, list) else 0
    if count == 0:
        out.append(_res(RULES["EVAL-008"], WARN, "没有任何用例"))
    elif count == 1:
        out.append(_res(RULES["EVAL-008"], INFO,
                        "只有 1 条用例（官方建议 2–3 条起步并覆盖一个边界情况）"))
    else:
        out.append(_res(RULES["EVAL-008"], PASS, f"{count} 条用例"))

    vague = [t for t in all_assertions if VAGUE_ASSERTION_RE.search(t)]
    brittle = [t for t in all_assertions if BRITTLE_ASSERTION_RE.search(t)]
    if not all_assertions:
        out.append(_res(RULES["EVAL-009"], INFO, "不适用：尚未写断言（官方也建议先跑一轮再写）"))
    else:
        hits = [f"空洞：{t}" for t in vague] + [f"脆弱：{t}" for t in brittle]
        out.append(
            _res(RULES["EVAL-009"], WARN if hits else PASS,
                 _summarize(hits) if hits else f"{len(all_assertions)} 条断言未见空洞/脆弱措辞")
        )

    return out


# --------------------------------------------------------------------------- #
# 工作区
# --------------------------------------------------------------------------- #


def _iterations(workspace: Path) -> tuple[list[tuple[int, Path]], list[str]]:
    found: list[tuple[int, Path]] = []
    odd: list[str] = []
    try:
        children = sorted(workspace.iterdir())
    except OSError as exc:
        return [], [f"工作区不可读（{exc.strerror or exc}）"]
    for child in children:
        if not child.is_dir():
            continue
        match = ITERATION_RE.match(child.name)
        if match:
            found.append((int(match.group(1)), child))
        elif child.name.startswith("iteration"):
            odd.append(child.name)
    return sorted(found), odd


def _arms(eval_dir: Path) -> tuple[Path | None, Path | None, list[str]]:
    main = eval_dir / ARM_MAIN if (eval_dir / ARM_MAIN).is_dir() else None
    baseline = None
    for name in ARM_BASELINES:
        if (eval_dir / name).is_dir():
            baseline = eval_dir / name
            break
    extra = [
        child.name for child in sorted(eval_dir.iterdir())
        if child.is_dir() and child.name != ARM_MAIN and child.name not in ARM_BASELINES
    ]
    return main, baseline, extra


def _grading_of(arm: Path) -> tuple[dict | None, str | None]:
    path = arm / "grading.json"
    if not path.is_file():
        return None, None
    data, error = read_json(path)
    if error:
        return None, f"{path.name}: {error}"
    if not isinstance(data, dict):
        return None, f"{path.name}: 顶层必须是对象"
    return data, None


def _check_grading(where: str, data: dict, declared_assertions: set[str],
                   out: list[Result], sink: dict) -> None:
    """校验一个 grading.json，并把逐条结果写入 sink 供聚合比对。"""
    results = data.get("assertion_results")
    summary = data.get("summary")
    struct_bad = []
    if not isinstance(results, list):
        struct_bad.append(f"assertion_results 缺失或不是数组（实为 {type(results).__name__}）")
    if not isinstance(summary, dict):
        struct_bad.append(f"summary 缺失或不是对象（实为 {type(summary).__name__}）")
    if struct_bad:
        out.append(_res(RULES["GRAD-001"], FAIL, f"{where}: " + "；".join(struct_bad)))
        return
    if not results:
        out.append(_res(RULES["GRAD-001"], WARN, f"{where}: assertion_results 为空数组"))
    else:
        out.append(_res(RULES["GRAD-001"], PASS,
                        f"{where}: {len(results)} 条断言结果 + summary"))

    field_bad: list[str] = []
    texts: list[str] = []
    passed_count = 0
    empty_evidence_pass: list[str] = []
    empty_evidence_fail: list[str] = []
    for idx, item in enumerate(results, 1):
        if not isinstance(item, dict):
            field_bad.append(f"第 {idx} 条不是对象")
            continue
        text, passed, evidence = item.get("text"), item.get("passed"), item.get("evidence")
        if not isinstance(text, str) or not text.strip():
            field_bad.append(f"第 {idx} 条 text 非空字符串缺失")
        else:
            texts.append(text)
        if not isinstance(passed, bool):
            field_bad.append(f"第 {idx} 条 passed 必须是布尔（实为 {type(passed).__name__}）")
        elif passed:
            passed_count += 1
        if not isinstance(evidence, str):
            field_bad.append(f"第 {idx} 条 evidence 必须是字符串")
        elif not evidence.strip():
            (empty_evidence_pass if passed is True else empty_evidence_fail).append(text or f"第 {idx} 条")
    out.append(
        _res(RULES["GRAD-002"], FAIL if field_bad else PASS,
             _summarize(field_bad) if field_bad else f"{len(results)} 条字段类型均正确")
    )

    # GRAD-003：summary 与逐条一致
    issues: list[str] = []
    total = summary.get("total")
    passed = summary.get("passed")
    failed = summary.get("failed")
    rate = summary.get("pass_rate")
    for key, value in (("total", total), ("passed", passed), ("failed", failed)):
        if not _is_int(value):
            issues.append(f"summary.{key} 应为整数（实为 {value!r}）")
    if _is_num(rate) and not (0 <= rate <= 1):
        issues.append(f"summary.pass_rate 应在 0–1 之间（实为 {rate!r}）")
    elif not _is_num(rate):
        issues.append(f"summary.pass_rate 应为数值（实为 {rate!r}）")
    failed_count = len(results) - passed_count
    if _is_int(total) and total != len(results):
        issues.append(f"summary.total={total} 与逐条数 {len(results)} 不符")
    if _is_int(passed) and passed != passed_count:
        issues.append(f"summary.passed={passed} 与实际通过数 {passed_count} 不符")
    if _is_int(failed) and failed != failed_count:
        issues.append(f"summary.failed={failed} 与实际未通过数 {failed_count} 不符")
    if _is_int(total) and _is_int(passed) and _is_int(failed) and total != passed + failed:
        issues.append(f"summary 自身不自洽：total={total} ≠ passed+failed={passed + failed}")
    if _is_num(rate) and len(results):
        expected = passed_count / len(results)
        if abs(float(rate) - expected) > TOL_ABS:
            issues.append(f"summary.pass_rate={rate} 与 {passed_count}/{len(results)}"
                          f"（={expected:.3f}）不符")
    out.append(
        _res(RULES["GRAD-003"], FAIL if issues else PASS,
             _summarize([f"{where}: {i}" for i in issues]) if issues
             else f"{where}: summary 与逐条结果一致")
    )

    if empty_evidence_pass:
        out.append(_res(RULES["GRAD-004"], FAIL,
                        f"{where}: {len(empty_evidence_pass)} 条 PASS 没有 evidence"
                        f"（官方要求 PASS 必须有具体证据）：{_summarize(empty_evidence_pass)}"))
    elif empty_evidence_fail:
        out.append(_res(RULES["GRAD-004"], WARN,
                        f"{where}: {len(empty_evidence_fail)} 条 FAIL 的 evidence 为空："
                        f"{_summarize(empty_evidence_fail)}"))
    else:
        out.append(_res(RULES["GRAD-004"], PASS, f"{where}: 每条都有 evidence"))

    unknown = [t for t in texts if declared_assertions and t not in declared_assertions]
    if not declared_assertions:
        out.append(_res(RULES["GRAD-005"], INFO,
                        f"{where}: 不适用（evals.json 未写断言或无法解析）"))
    elif unknown:
        out.append(_res(RULES["GRAD-005"], WARN,
                        f"{where}: {len(unknown)} 条断言的文本不在 evals.json 里："
                        f"{_summarize(unknown)}"))
    else:
        out.append(_res(RULES["GRAD-005"], PASS, f"{where}: 断言文本均能在 evals.json 中找到"))

    sink.setdefault("pass_rates", []).append(passed_count / len(results) if results else 0.0)
    sink.setdefault("texts", set()).update(texts)


def _check_timing(where: str, arm: Path) -> Result:
    """校验 timing.json 的形状。**不**在这里收集数值序列。

    数值序列（tokens / seconds / pass_rates）的唯一收集处是 `_arm_stats`。
    早先这里也往同一个 dict 追加，于是每个 timing 被算了两遍：均值恰好不受影响
    （重复值不改变均值），但 stddev 与"各 N 次"会错——加上 stddev 对账后才暴露。
    """
    path = arm / "timing.json"
    if not path.is_file():
        return _res(RULES["TIME-001"], SKIP, f"未执行：{where} 缺 timing.json（见 WS-003）")
    data, error = read_json(path)
    if error:
        return _res(RULES["TIME-001"], FAIL, f"{where}: {error}")
    if not isinstance(data, dict):
        return _res(RULES["TIME-001"], FAIL, f"{where}: timing.json 顶层必须是对象")
    issues = []
    for key in ("total_tokens", "duration_ms"):
        value = data.get(key)
        if not _is_int(value):
            issues.append(f"{key} 应为整数（实为 {value!r}）")
        elif value < 0:
            issues.append(f"{key} 不得为负（{value}）")
    if issues:
        return _res(RULES["TIME-001"], FAIL, f"{where}: " + "；".join(issues))
    return _res(RULES["TIME-001"], PASS,
                f"{where}: {data['total_tokens']} tokens / {data['duration_ms']} ms")


def _mean_stddev(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return mean, var ** 0.5


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(TOL_ABS, TOL_REL * max(abs(a), abs(b)))


def _stddev_candidates(values: list[float]) -> list[float]:
    """总体（÷n）与样本（÷n−1）两种标准差都算出来。

    官方没定义用哪一种，所以**任一匹配即算一致**；只认一种会把正确数据判错。
    少于 2 个样本时只有一种可能（0），直接返回。
    """
    if len(values) < 2:
        return [_mean_stddev(values)[1]]
    mean, pop = _mean_stddev(values)
    sample = (sum((v - mean) ** 2 for v in values) / (len(values) - 1)) ** 0.5
    return [pop, sample]


def _num_map(data: dict, key: str) -> tuple[dict, list[str]]:
    value = data.get(key)
    if not isinstance(value, dict):
        return {}, [f"{key} 缺失或不是对象（实为 {type(value).__name__}）"]
    issues = []
    for stat in ("mean", "stddev"):
        if stat in value and not _is_num(value[stat]):
            issues.append(f"{key}.{stat} 应为数值（实为 {value[stat]!r}）")
    if "mean" not in value:
        issues.append(f"{key}.mean 缺失")
    if "stddev" in value and _is_num(value["stddev"]) and value["stddev"] < 0:
        issues.append(f"{key}.stddev 不得为负（{value['stddev']}）")
    return value, issues


def _check_benchmark(
    where: str, iteration_dir: Path, arm_stats: dict[str, dict]
) -> tuple[list[Result], Result]:
    """校验一个 iteration 的 benchmark.json。返回 (BENCH-* 结果, WS-006 结果)。"""
    out: list[Result] = []
    path = iteration_dir / "benchmark.json"
    if not path.is_file():
        bench_skip = [
            _res(RULES[rid], SKIP, "未执行：本 iteration 没有 benchmark.json")
            for rid in ("BENCH-001", "BENCH-002", "BENCH-003", "BENCH-004", "BENCH-005",
                        "BENCH-006")
        ]
        return bench_skip, _res(RULES["WS-006"], WARN, f"{where}: 缺 benchmark.json")

    data, error = read_json(path)
    if error or not isinstance(data, dict):
        reason = error or "顶层必须是对象"
        bench_fail = [
            _res(RULES[rid], FAIL if rid == "BENCH-001" else SKIP,
                 f"{where}: benchmark.json {reason}")
            for rid in ("BENCH-001", "BENCH-002", "BENCH-003", "BENCH-004", "BENCH-005",
                        "BENCH-006")
        ]
        return bench_fail, _res(RULES["WS-006"], FAIL, f"{where}: benchmark.json {reason}")

    summary = data.get("run_summary")
    if not isinstance(summary, dict):
        out.append(_res(RULES["BENCH-001"], FAIL,
                        f"{where}: run_summary 缺失或不是对象（实为 {type(summary).__name__}）"))
        out.extend(_res(RULES[rid], SKIP, "未执行：run_summary 不可用")
                   for rid in ("BENCH-002", "BENCH-003", "BENCH-004", "BENCH-005", "BENCH-006"))
        return out, _res(RULES["WS-006"], PASS, f"{where}: benchmark.json 在场")

    has_main = isinstance(summary.get(ARM_MAIN), dict)
    baseline_key = next((k for k in ARM_BASELINES if isinstance(summary.get(k), dict)), None)
    problems = []
    if not has_main:
        problems.append(f"缺 {ARM_MAIN}")
    if baseline_key is None:
        problems.append("缺基线（" + " 或 ".join(ARM_BASELINES) + "）")
    out.append(
        _res(RULES["BENCH-001"], FAIL if problems else PASS,
             f"{where}: " + "；".join(problems) if problems
             else f"{where}: 含 {ARM_MAIN} 与基线 {baseline_key}")
    )
    if not has_main or baseline_key is None:
        out.extend(_res(RULES[rid], SKIP, "未执行：run_summary 两侧配置不完整")
                   for rid in ("BENCH-002", "BENCH-003", "BENCH-004", "BENCH-005", "BENCH-006"))
        return out, _res(RULES["WS-006"], PASS, f"{where}: benchmark.json 在场")

    stat_issues: list[str] = []
    parsed: dict[str, dict] = {}
    for key in (ARM_MAIN, baseline_key):
        parsed[key] = {}
        for metric in ("pass_rate", "time_seconds", "tokens"):
            values, issues = _num_map(summary[key], metric)
            parsed[key][metric] = values
            stat_issues.extend(f"{key}.{i}" for i in issues)
    out.append(
        _res(RULES["BENCH-002"], WARN if stat_issues else PASS,
             _summarize([f"{where}: {i}" for i in stat_issues]) if stat_issues
             else f"{where}: mean/stddev 形态正确")
    )

    delta_issues: list[str] = []
    delta = summary.get("delta")
    if not isinstance(delta, dict):
        delta_issues.append("delta 缺失或不是对象")
    else:
        for metric in ("pass_rate", "time_seconds", "tokens"):
            declared = delta.get(metric)
            left = parsed[ARM_MAIN][metric].get("mean")
            right = parsed[baseline_key][metric].get("mean")
            if declared is None:
                delta_issues.append(f"delta.{metric} 缺失")
            elif not _is_num(declared):
                delta_issues.append(f"delta.{metric} 应为数值（实为 {declared!r}）")
            elif _is_num(left) and _is_num(right) and not _close(float(declared),
                                                                float(left) - float(right)):
                delta_issues.append(
                    f"delta.{metric}={declared} 与 {left} - {right}"
                    f"（={float(left) - float(right):.6g}）不符")
    out.append(
        _res(RULES["BENCH-003"], WARN if delta_issues else PASS,
             _summarize([f"{where}: {i}" for i in delta_issues]) if delta_issues
             else f"{where}: delta 与两侧 mean 一致（容许四舍五入）")
    )

    agg_issues: list[str] = []
    for key, stats in arm_stats.items():
        if key not in parsed:
            continue
        for metric, values_key in (("pass_rate", "pass_rates"),
                                   ("time_seconds", "seconds"),
                                   ("tokens", "tokens")):
            values = stats.get(values_key) or []
            if not values:
                continue
            numeric = [float(v) for v in values]
            mean, _stddev = _mean_stddev(numeric)
            declared = parsed[key][metric].get("mean")
            if _is_num(declared) and not _close(float(declared), mean):
                agg_issues.append(
                    f"{key}.{metric}.mean={declared} 与逐次产物算得的 {mean:.6g}"
                    f"（{len(values)} 次）不符")
            declared_sd = parsed[key][metric].get("stddev")
            if _is_num(declared_sd) and len(numeric) >= 2:
                candidates = _stddev_candidates(numeric)
                if not any(_close(float(declared_sd), c) for c in candidates):
                    agg_issues.append(
                        f"{key}.{metric}.stddev={declared_sd} 与逐次产物算得的 "
                        + " 或 ".join(f"{c:.6g}" for c in candidates)
                        + f"（{len(numeric)} 次；总体/样本两种口径都不符）")
    out.append(
        _res(RULES["BENCH-004"], WARN if agg_issues else PASS,
             _summarize([f"{where}: {i}" for i in agg_issues]) if agg_issues
             else f"{where}: 聚合值与逐次产物一致")
    )

    runs = {key: len(stats.get("pass_rates") or []) for key, stats in arm_stats.items()}
    detail = "；".join(f"{k} 各 {v} 次" for k, v in runs.items()) or "无逐次产物"
    thin = min(runs.values(), default=0) <= 1
    out.append(_res(RULES["BENCH-005"], INFO,
                    f"{where}: {detail}——"
                    + ("单次运行下 stddev 无意义，只看计数与 delta（官方说明）"
                       if thin else "多次运行，stddev 可读")))

    main_rate = parsed[ARM_MAIN]["pass_rate"].get("mean")
    base_rate = parsed[baseline_key]["pass_rate"].get("mean")
    if _is_num(main_rate) and _is_num(base_rate):
        if float(main_rate) < float(base_rate):
            out.append(_res(RULES["BENCH-006"], WARN,
                            f"{where}: with_skill 的 pass_rate 均值 {main_rate} 低于基线 "
                            f"{baseline_key} 的 {base_rate}（技能未体现增益）"))
        elif _close(float(main_rate), float(base_rate)):
            out.append(_res(RULES["BENCH-006"], WARN,
                            f"{where}: with_skill 与基线 pass_rate 持平（{main_rate}）——"
                            f"技能可能没有价值，或断言太容易（两边都过）"))
        else:
            out.append(_res(RULES["BENCH-006"], PASS,
                            f"{where}: with_skill {main_rate} > 基线 {base_rate}"))
    else:
        out.append(_res(RULES["BENCH-006"], SKIP, "未执行：两侧 pass_rate.mean 不可用"))
    return out, _res(RULES["WS-006"], PASS, f"{where}: benchmark.json 在场")


def _arm_stats(arm: Path) -> dict:
    """从某个 arm 的逐次产物里收集聚合所需的原始值。"""
    stats: dict = {}
    data, _error = _grading_of(arm)
    if isinstance(data, dict):
        results = data.get("assertion_results")
        if isinstance(results, list) and results:
            passed = sum(1 for i in results if isinstance(i, dict) and i.get("passed") is True)
            stats.setdefault("pass_rates", []).append(passed / len(results))
            stats.setdefault("texts", set()).update(
                i["text"] for i in results if isinstance(i, dict) and isinstance(i.get("text"), str)
            )
    timing = arm / "timing.json"
    if timing.is_file():
        tdata, _terr = read_json(timing)
        if isinstance(tdata, dict):
            if _is_int(tdata.get("total_tokens")):
                stats.setdefault("tokens", []).append(tdata["total_tokens"])
            if _is_int(tdata.get("duration_ms")):
                stats.setdefault("seconds", []).append(tdata["duration_ms"] / 1000.0)
    return stats


def _check_feedback(path: Path) -> Result:
    if not path.is_file():
        return _res(RULES["WS-007"], INFO,
                    "不适用：没有 feedback.json（官方说“例如”存这里，属可选）")
    data, error = read_json(path)
    if error:
        return _res(RULES["WS-007"], WARN, f"{path.name}: {error}")
    if isinstance(data, dict):
        bad = [k for k, v in data.items() if not isinstance(v, str)]
        if bad:
            return _res(RULES["WS-007"], WARN,
                        f"{path.name}: 值必须是字符串（{_summarize([repr(k) for k in bad])}）")
        empty = sum(1 for v in data.values() if not v.strip())
        return _res(RULES["WS-007"], PASS,
                    f"{path.name}: {len(data)} 条反馈（其中 {empty} 条为空=人工复核无异议）")
    if isinstance(data, list):
        return _res(RULES["WS-007"], WARN,
                    f"{path.name}: 是数组（旧体系方言）；官方形状是"
                    f"「eval 目录名 → 反馈文本」的对象")
    return _res(RULES["WS-007"], WARN,
                f"{path.name}: 顶层应为对象（实为 {type(data).__name__}）")


def _check_run_inputs(workspace: Path, iteration: int | None) -> Result:
    """WS-006：本轮的执行自证（隔离方式 / 执行器 / 输入冻结哈希 / 两臂提示词哈希）。

    来历：旧体系双跑对照要求每轮写 `run-inputs.md`，如实写明"两臂各派新进程、禁用 Skill 工具、
    禁 resume"，或在做不到时写明"降级为同会话顺序执行""未执行"——**并把作废轮留档**。
    我们只查"目录与文件在不在"，**完全不管这轮是不是真在隔离环境里跑的**：执行层不自研是对的，
    但「无声地假装隔离过」必须被堵住，否则 delta 就是无源之水。

    判定：
    - 有 `run-inputs.json` 且 `isolation` 合法、字段齐 → PASS（降级/未执行 → WARN「参考级证据」）；
    - 有迭代目录但一个自证文件都没有 → WARN（无法确认输入冻结与隔离方式）；
    - 没有迭代目录 → INFO（不适用）。
    """
    iterations, _odd = _iterations(workspace)
    if iteration is not None:
        iterations = [item for item in iterations if item[0] == iteration]
    if not iterations:
        return _res(RULES["WS-008"], INFO, "不适用：没有 iteration 目录")

    found: list[tuple[str, dict]] = []
    bad: list[str] = []
    degraded: list[str] = []
    missing: list[str] = []
    for number, path in iterations:
        record = path / RUN_INPUTS_NAME
        if not record.is_file():
            missing.append(f"iteration-{number}")
            continue
        data, error = read_json(record)
        if error or not isinstance(data, dict):
            bad.append(f"iteration-{number}: 不可读（{error or '形状不符'}）")
            continue
        level = str(data.get("isolation", "")).strip()
        fields = [key for key in ("isolation", "executor", "input_hash", "prompt_hashes")
                  if not data.get(key)]
        if level not in ISOLATION_LEVELS:
            bad.append(f"iteration-{number}: isolation 取值应为 {'/'.join(ISOLATION_LEVELS)}"
                       f"（实为 {level or '空'}）")
            continue
        if fields:
            bad.append(f"iteration-{number}: 缺字段 {'、'.join(fields)}")
            continue
        found.append((f"iteration-{number}", data))
        if level != "隔离":
            degraded.append(f"iteration-{number}（{level}）")

    if bad:
        return _res(RULES["WS-008"], WARN,
                    "执行自证有问题：" + "；".join(bad[:3])
                    + f"（模板见 examples/{RUN_INPUTS_NAME}）")
    if degraded:
        return _res(RULES["WS-008"], WARN,
                    f"本轮为**参考级证据**：{'、'.join(degraded)} 不是隔离环境跑的——"
                    f"该轮的 delta 不得当作技能带来的增益（旧体系要求如实写明并在作废轮留档）")
    if missing and not found:
        # 记 INFO 而不是 WARN：执行自证是**增强项**（放了才检查），跟评委校准同一口径——
        # 强制它会让人人恒返回 2，也会让"全绿基线"这类夹具无端变脏。
        return _res(RULES["WS-008"], INFO,
                    f"未提供执行自证（{'、'.join(missing[:3])}）：放了就会被检查"
                    f"（模板见 examples/{RUN_INPUTS_NAME}）；没有它，这一轮的 delta "
                    f"只能当参考级证据")
    note = f"{len(found)} 轮执行自证齐备（隔离方式、执行器、输入哈希、两臂提示词哈希）"
    if missing:
        note += f"；另有 {len(missing)} 轮缺自证（{'、'.join(missing[:3])}）"
    return _res(RULES["WS-008"], PASS if not missing else WARN, note)


def _check_discrimination(workspace: Path, iteration: int | None) -> Result:
    """跨 iteration/arm 的**断言区分度**：恒真与恒假的断言都没有区分度。

    - 恒真：每次都过——多半是空洞断言（"输出是好的"换个说法），也可能判据写得太松；
    - 恒假：每次都不通过——判据可能写反，或环境从来没满足过。

    只记 WARN：断言的价值最终由人判断（`E-05` 断言难度复核也管这件事）。
    """
    iterations, _odd = _iterations(workspace)
    if iteration is not None:
        iterations = [item for item in iterations if item[0] == iteration]
    seen: dict[str, list[bool]] = {}
    files = 0
    for _number, path in iterations:
        for grading in sorted(path.rglob("grading.json")):
            data, error = read_json(grading)
            if error or not isinstance(data, dict):
                continue
            files += 1
            for item in data.get("assertion_results") or []:
                if not isinstance(item, dict) or not isinstance(item.get("passed"), bool):
                    continue
                text = str(item.get("text", "")).strip()
                if text:
                    seen.setdefault(text, []).append(item["passed"])
    if not files:
        return _res(RULES["EVAL-010"], INFO, "不适用：工作区里没有可读的 grading.json")
    enough = {text: flags for text, flags in seen.items()
              if len(flags) >= MIN_ASSERTION_OBSERVATIONS}
    if not enough:
        return _res(RULES["EVAL-010"], INFO,
                    f"不适用：没有断言被观测到 {MIN_ASSERTION_OBSERVATIONS} 次以上"
                    f"（最多 {max((len(v) for v in seen.values()), default=0)} 次）")
    always_true = [t for t, v in enough.items() if all(v)]
    always_false = [t for t, v in enough.items() if not any(v)]
    if always_true or always_false:
        parts = []
        if always_true:
            parts.append(f"恒真 {len(always_true)} 条（{_summarize(always_true)}）")
        if always_false:
            parts.append(f"恒假 {len(always_false)} 条（{_summarize(always_false)}）")
        return _res(RULES["EVAL-010"], WARN,
                    f"断言没有区分度：{'；'.join(parts)}——"
                    f"恒真的多半空洞（换成更具体的判定），恒假的先查判据是否写反")
    return _res(RULES["EVAL-010"], PASS,
                f"{len(enough)} 条断言都有区分度（每条观测 ≥{MIN_ASSERTION_OBSERVATIONS} 次）")


def parse_iso_time(value: object) -> datetime | None:
    """把声明里的时间解析成 `datetime`；解析不了返回 None。

    只接受 ISO 8601（`date.fromisoformat`/`datetime.fromisoformat` 能吃的形态，
    含 `Z` 后缀）。**宽松一点没关系**：这是人写的自证字段，不是机器产出；
    但它必须**能被解析**——无法解析的声明等于没有声明（记 WARN 而不是当它不存在）。
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _check_assertion_timing(workspace: Path, iteration: int | None) -> Result:
    """EVAL-011：断言写入时机**只认显式声明**，绝不用文件 mtime 推断。

    来历：旧体系 V21 要求"断言与用例的时机关系"可核对，旧实现靠比较文件 mtime 来推断
    "断言是什么时候补的"。这条路本机实测就不可靠：复制、克隆、重写、git checkout
    都会改 mtime，而真正想知道的事（有没有看过输出才写断言）根本不在文件系统里。
    本项目**明确舍弃 mtime 推断**，改为：谁想登记就在执行自证里写一句时间。

    判定：
    - 没有 iteration 目录 / 没有 run-inputs.json / 没写这个字段 → INFO（不适用：未声明）；
    - 写了但解析不出 ISO 8601 → **WARN**（无法解析的声明等于没声明，但要让人知道）；
    - 写了且可解析 → PASS，证据给出先后关系（同时声明了输出产出时间时）。
      **先后关系只登记、不判好坏**：官方明确允许"先跑一轮再补断言"，
      "先写断言再跑"也自有道理——工具不替使用者选一种流程，只把事实写进报告。
    """
    iterations, _odd = _iterations(workspace)
    if iteration is not None:
        iterations = [item for item in iterations if item[0] == iteration]
    if not iterations:
        return _res(RULES["EVAL-011"], INFO, "不适用：没有 iteration 目录")

    declared: list[str] = []
    bad: list[str] = []
    for number, path in iterations:
        record = path / RUN_INPUTS_NAME
        if not record.is_file():
            continue
        data, error = read_json(record)
        if error or not isinstance(data, dict) or ASSERTIONS_TIME_FIELD not in data:
            continue
        raw = data.get(ASSERTIONS_TIME_FIELD)
        added = parse_iso_time(raw)
        if added is None:
            bad.append(f"iteration-{number}: {ASSERTIONS_TIME_FIELD} 应为 ISO 8601 字符串"
                       f"（实为 {raw!r}）——无法解析的声明等于没有声明")
            continue
        produced_raw = data.get(OUTPUTS_TIME_FIELD)
        produced = parse_iso_time(produced_raw)
        if produced is None:
            declared.append(f"iteration-{number}：断言写入 {raw}"
                            f"（未声明 {OUTPUTS_TIME_FIELD}，只登记时间，不给先后关系）")
        elif added < produced:
            declared.append(f"iteration-{number}：断言 {raw} 早于输出 {produced_raw}"
                            f"（先写断言再跑）")
        else:
            declared.append(f"iteration-{number}：断言 {raw} 不早于输出 {produced_raw}"
                            f"（先跑一轮再补断言——官方允许的流程，只登记不判缺陷）")
    if bad:
        return _res(RULES["EVAL-011"], WARN, "；".join(bad[:3]))
    if not declared:
        return _res(RULES["EVAL-011"], INFO,
                    f"未声明：{RUN_INPUTS_NAME} 里没有 {ASSERTIONS_TIME_FIELD}"
                    f"——本项**不做推断**（旧实现用文件 mtime 猜「断言何时补的」，"
                    f"复制/克隆/重写都会误判）；想登记就写一句 ISO 时间")
    return _res(RULES["EVAL-011"], PASS, _summarize(declared, limit=3))


def _check_workspace(skill_dir: Path, workspace: Path, doc: EvalsDoc,
                     iteration: int | None) -> list[Result]:
    out: list[Result] = []
    iterations, odd = _iterations(workspace)
    if iteration is not None:
        iterations = [item for item in iterations if item[0] == iteration]
        if not iterations:
            # 只回**本函数负责的**规则族：早先这里遍历了全部 RULES，于是 EVAL 族
            # 被回了第二遍（同 rid 两行）。另外"指定的 iteration 不存在"是实打实的
            # 问题（打错了？产物没落盘？）→ 记 WARN，而不是 INFO（INFO 是"不适用"）。
            reason = f"指定的 iteration-{iteration} 在工作区里不存在"
            out.append(_res(RULES["WS-001"], WARN, reason))
            for rule in RULES.values():
                if rule.rid != "WS-001" and rule.rid.startswith(
                        ("WS-", "GRAD-", "BENCH-", "TIME-")):
                    out.append(_res(rule, SKIP, f"未执行：{reason}"))
            return out

    if not iterations:
        reason = (f"工作区 {workspace} 里没有 iteration-N 目录"
                  + (f"（发现可疑目录：{_summarize(odd)}）" if odd else ""))
        # WS-001 是"工作区有没有迭代目录"这条规则本身 → WARN；
        # 其余规则确实无从执行 → SKIP（本项未执行，不许冒充 PASS）。
        out.append(_res(RULES["WS-001"], WARN, reason))
        for rule in RULES.values():
            if rule.rid != "WS-001" and rule.rid.startswith(("WS-", "GRAD-", "BENCH-", "TIME-")):
                out.append(_res(rule, SKIP, f"未执行：{reason}"))
        return out

    numbers = [n for n, _path in iterations]
    out.append(_res(RULES["WS-001"], PASS,
                    f"{workspace.name}: {len(numbers)} 轮迭代（{numbers}）"
                    + (f"；另有可疑目录 {_summarize(odd)}" if odd else "")))
    gaps = [n for n in range(1, max(numbers) + 1) if n not in numbers]
    out.append(
        _res(RULES["WS-004"], WARN if gaps else PASS,
             f"缺 iteration-{_summarize([str(g) for g in gaps])}" if gaps
             else f"iteration 编号连续（1–{max(numbers)}）")
    )

    declared_assertions = set(doc.assertions())
    arm_missing: list[str] = []
    outputs_missing: list[str] = []
    set_mismatch: list[str] = []
    extra_arms: list[str] = []
    grading_errors: list[str] = []
    no_eval_dirs: list[str] = []
    timing_results: list[Result] = []
    grad_by_rid: dict[str, list[Result]] = {
        rid: [] for rid in ("GRAD-001", "GRAD-002", "GRAD-003", "GRAD-004", "GRAD-005")
    }
    bench_results: list[Result] = []
    ws006_results: list[Result] = []

    for number, iteration_dir in iterations:
        where = f"iteration-{number}"
        arm_stats: dict[str, dict] = {}
        eval_dirs = [c for c in sorted(iteration_dir.iterdir())
                     if c.is_dir() and EVAL_DIR_RE.match(c.name)]
        if not eval_dirs:
            no_eval_dirs.append(where)

        for eval_dir in eval_dirs:
            main, baseline, extra = _arms(eval_dir)
            if main is None or baseline is None:
                missing = []
                if main is None:
                    missing.append(ARM_MAIN)
                if baseline is None:
                    missing.append(" 或 ".join(ARM_BASELINES))
                arm_missing.append(f"{where}/{eval_dir.name}: 缺 {'、'.join(missing)}")
            if extra:
                extra_arms.append(f"{where}/{eval_dir.name}: {_summarize(extra)}")

            texts_by_arm: dict[str, set[str]] = {}
            for arm in (main, baseline):
                if arm is None:
                    continue
                label = f"{where}/{eval_dir.name}/{arm.name}"
                lacks = []
                if not (arm / "outputs").is_dir():
                    lacks.append("outputs/")
                if not (arm / "timing.json").is_file():
                    lacks.append("timing.json")
                if lacks:
                    outputs_missing.append(f"{label}: 缺 {'、'.join(lacks)}")

                stats = arm_stats.setdefault(arm.name, {})
                timing_results.append(_check_timing(label, arm))

                data, error = _grading_of(arm)
                if error:
                    grading_errors.append(f"{label}: {error}")
                    continue
                if data is None:
                    continue
                bucket: list[Result] = []
                sink: dict = {}
                _check_grading(label, data, declared_assertions, bucket, sink)
                for res in bucket:
                    grad_by_rid[res.rid].append(res)
                merged_stats = _arm_stats(arm)
                for key, value in merged_stats.items():
                    if key == "texts":
                        stats.setdefault("texts", set()).update(value)
                    else:
                        stats.setdefault(key, []).extend(value)
                texts_by_arm[arm.name] = set(merged_stats.get("texts", set()))

            if len(texts_by_arm) == 2:
                left, right = texts_by_arm.values()
                if left != right:
                    only = sorted(left.symmetric_difference(right))
                    set_mismatch.append(
                        f"{where}/{eval_dir.name}: 两侧断言不一致（差异：{_summarize(only)}）")

        bench, ws006 = _check_benchmark(where, iteration_dir, arm_stats)
        bench_results.extend(bench)
        ws006_results.append(ws006)

    for rid, bucket in grad_by_rid.items():
        out.append(_merge(bucket, rid, "未执行：工作区里没有可校验的 grading.json"))
    for rid in ("BENCH-001", "BENCH-002", "BENCH-003", "BENCH-004", "BENCH-005", "BENCH-006"):
        out.append(_merge([r for r in bench_results if r.rid == rid], rid,
                          "未执行：工作区里没有 iteration-N 目录"))
    out.append(_merge(timing_results, "TIME-001", "未执行：工作区里没有 timing.json"))

    ws2_issues = arm_missing + [f"{w}: 没有 eval-* 目录" for w in no_eval_dirs]
    out.append(
        _res(RULES["WS-002"], WARN if ws2_issues else PASS,
             _summarize(ws2_issues) if ws2_issues
             else f"{len(iterations)} 轮迭代的 eval 目录均具备 with_skill 与基线")
    )
    ws3_issues = outputs_missing + [f"{e}: 出现约定外的 arm 目录" for e in extra_arms]
    out.append(
        _res(RULES["WS-003"], WARN if ws3_issues else PASS,
             _summarize(ws3_issues) if ws3_issues else "各 arm 均含 outputs/ 与 timing.json")
    )
    out.append(
        _res(RULES["WS-005"], WARN if set_mismatch else PASS,
             _summarize(set_mismatch) if set_mismatch else "同一 eval 目录下两侧断言集合一致")
    )
    out.append(_merge(ws006_results, "WS-006", "未执行：工作区里没有 iteration-N 目录"))
    out.append(_check_feedback(workspace / "feedback.json"))
    if grading_errors:
        out.append(_res(RULES["GRAD-001"], FAIL, _summarize(grading_errors)))
    return out


def _merge(results: list[Result], rid: str, empty_reason: str) -> Result:
    """把逐文件的多条结果合并成一条（同 rid 取最严判定，证据合并）。"""
    if not results:
        return _res(RULES[rid], SKIP, empty_reason)
    order = {FAIL: 0, WARN: 1, SKIP: 2, INFO: 3, PASS: 4}
    worst = min(results, key=lambda r: order.get(r.status, 9))
    others = [r for r in results if r.status == worst.status and r is not worst]
    evidence = worst.evidence
    if others:
        evidence += f"；同类另有 {len(others)} 处"
    total = len(results)
    passed = sum(1 for r in results if r.status == PASS)
    if worst.status == PASS and passed > 1:
        evidence = f"{passed} 个文件全部通过"
    return Result(rid=worst.rid, title=worst.title, status=worst.status, level=worst.level,
                  evidence=evidence, remediation=worst.remediation, optional=False)


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #


def check_evals(
    skill_dir: Path,
    *,
    workspace: Path | None = None,
    iteration: int | None = None,
) -> Report:
    """校验一个技能的评测资产。没有 evals 资产时全部记 INFO（不适用）。"""
    report = Report(target=str(skill_dir), stage="evals")
    skill_dir = skill_dir.resolve()
    doc = _read_evals(skill_dir)

    name = skill_dir.name
    skill_md = find_skill_md(skill_dir)
    if skill_md is not None:
        try:
            from .frontmatter import parse_frontmatter

            parsed = parse_frontmatter(read_text(skill_md))
            declared = parsed.get("name")
            if isinstance(declared, str) and declared.strip():
                name = declared.strip()
        except Exception:  # noqa: BLE001 - frontmatter 问题归 spec 阶段，这里不重复报
            pass

    if not doc.present:
        # 「一个评测资产都没有」必须显式说出来：否则"没有 evals"与"evals 全绿色"在
        # 报告里长得一模一样，而这两件事的含义天差地别。
        report.add(_res(RULES["EVAL-000"], WARN,
                        "技能没有 evals/evals.json：没有任何质量证据"
                        "（官方建议先写 2–3 条用例再迭代）"))
        for rid, rule in RULES.items():
            if rid == "EVAL-000":
                continue
            report.add(_res(rule, INFO,
                            "不适用：技能未提供 evals/evals.json"
                            "（官方建议但不强制：先写 2–3 条用例再迭代）"))
        report.meta["评测资产"] = "无 evals/evals.json"
        return report

    results = [_res(RULES["EVAL-000"], PASS,
                    f"提供评测资产（{len(doc.entries)} 条用例）")]
    results.extend(_check_evals_json(skill_dir, doc, name))

    ws = find_workspace(skill_dir, workspace)
    if ws is None:
        for rid in ("WS-001", "WS-002", "WS-003", "WS-004", "WS-005", "WS-006", "WS-007",
                    "TIME-001", "GRAD-001", "GRAD-002", "GRAD-003", "GRAD-004", "GRAD-005",
                    "BENCH-001", "BENCH-002", "BENCH-003", "BENCH-004", "BENCH-005",
                    "BENCH-006"):
            results.append(_res(RULES[rid], INFO,
                                f"不适用：未找到评测工作区"
                                f"（默认找并列目录 <技能名>{WORKSPACE_SUFFIX}/，可用 --workspace 指定）"))
        results.append(_res(RULES["EVAL-010"], INFO,
                            "不适用：未找到评测工作区（没有跨轮次观测，谈不上区分度）"))
        results.append(_res(RULES["WS-008"], INFO,
                            "不适用：未找到评测工作区（谈不上执行自证）"))
        results.append(_res(RULES["EVAL-011"], INFO,
                            "不适用：未找到评测工作区（没有执行自证可读，"
                            "谈不上断言写入时机）"))
    else:
        results.extend(_check_workspace(skill_dir, ws, doc, iteration))
        results.append(_check_discrimination(ws, iteration))
        results.append(_check_assertion_timing(ws, iteration))
        # 幂等：某些路径（例如指定的 iteration 不存在）会先行产出 WS-008 的空结论
        if not any(item.rid == "WS-008" for item in results):
            results.append(_check_run_inputs(ws, iteration))

    for res in results:
        report.add(res)
    produced = {r.rid for r in results}
    for rid, rule in RULES.items():
        if rid not in produced:
            report.add(_res(rule, SKIP, "实现遗漏：本规则未产生记录（请报 bug）"))
    report.meta["评测资产"] = str(doc.path) if doc.path else "无"
    report.meta["评测工作区"] = str(ws) if ws else "未找到"
    if doc.path:
        report.meta["用例数"] = str(len(doc.entries))
    return report
