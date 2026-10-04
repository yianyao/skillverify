"""trigger —— 触发评测资产校验（查询集与运行记录）。

**为什么单独一层**：官方评估页只覆盖"输出质量"评测（`evals/evals.json`），
**没有**覆盖"技能会不会被触发"这件事；而触发是技能能否起作用的前提。
旧体系为此自建了一套资产（查询集 + 运行记录），口径写在本项目交接文档 §3.3：

- 约 **20 条查询**，正例 8–10、负例 8–10，**负例以 near-miss 为主**；
- 每条查询跑 **3 次**，触发率阈值 **0.5**（正例 >0.5、负例 <0.5）；
- **train ~60% / validation ~40%** 固定切分；只据 train 失败修订，
  修订后另造 5–10 条全新查询做泛化终测。

**落点（M4 时明确留给后续的那件事）**：`evals/trigger-queryset.json` 与
`evals/trigger-runs.json`——**与官方 `evals/evals.json` 分开**。
旧体系把两者都塞进 `evals/evals.json`（顶层 `queries`）与 `.verification/trigger-eval/`
两处，这正是 M4 判那 4 个旧文件"需迁移"的原因。

字段沿用旧体系的名字（`id`/`subset`/`should_trigger`/`category`/`query`/`rationale`；
运行记录 `query_id`/`run`/`loaded`/`evidence`），这样旧资产能直接搬过来。
**`frozen.sha256` 不复刻**：本项目已定"git 单一真源"，再引入一套自建哈希清单只会打架。

**判定纪律**（对应旧体系实测踩过的坑）：
- `should_trigger` / `loaded` 必须是**严格布尔**——旧体系里非布尔 `loaded` 会被
  悄悄当成"未触发"，是真实的计分错误；此处一律报出来。
- 运行次数不足时报"数据不足"（WARN），**不**用不足的数据给出阈值结论。
- 触发率不达标（数据足够时）记 **FAIL**：技能压根不触发，交付出去也没用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .encoding import read_json
from .report import FAIL, INFO, PASS, SKIP, WARN, Report, Result, Rule

_SPEC = "https://agentskills.io/specification#description-field"
_EVAL = "https://agentskills.io/skill-creation/optimizing-descriptions"

#: 查询集落点（与官方 evals.json 分开）
QUERYSET_NAME = "trigger-queryset.json"
#: 运行记录落点
RUNS_NAME = "trigger-runs.json"

#: 旧体系的落点（M4 判"需迁移"的那批资产就在这里）——只用于给出迁移指引，
#: 不做静默回退读取：单一来源才有意义，两处都能读等于又回到旧体系的问题。
LEGACY_DIR = Path(".verification/trigger-eval")
LEGACY_QUERYSET_NAME = "queryset.json"

#: 官方口径（交接文档 §3.3）
TARGET_TOTAL = 20
MIN_PER_SIDE = 8
MAX_PER_SIDE = 10
MIN_TOTAL = 12
RUNS_PER_QUERY = 3
TRIGGER_THRESHOLD = 0.5
TRAIN_SHARE_MIN = 0.55
TRAIN_SHARE_MAX = 0.65

#: 负例的 near-miss 类别名（旧体系用 `negative-near-miss`）
NEAR_MISS_HINTS = ("near", "nearmiss", "near-miss", "近似", "擦边")

RULES: dict[str, Rule] = {
    "TRIG-000": Rule(
        "TRIG-000",
        "技能提供触发评测资产（evals/trigger-queryset.json）",
        "HOUSE",
        _EVAL,
        "至少写 8 条正例 + 8 条负例（负例以 near-miss 为主），每条跑 3 次",
    ),
    "TRIG-001": Rule(
        "TRIG-001",
        "查询集可解析为对象，且含 skill_name 与非空 queries",
        "HOUSE",
        "本项目约定：触发评测与官方输出质量评测分开两个文件",
        "按 `skillverify review prompts --family E` 里的 E-01 判据组织查询集",
    ),
    "TRIG-002": Rule(
        "TRIG-002",
        "每条查询必填 id / query / should_trigger（严格布尔）/ subset",
        "HOUSE",
        _EVAL,
        "补齐字段；`should_trigger` 必须是 JSON 布尔值（不能用 \"true\" 或 1）",
    ),
    "TRIG-003": Rule(
        "TRIG-003",
        "查询 id 唯一",
        "HOUSE",
        "id 重复时运行记录无法归属",
        "改掉重复的 id",
    ),
    "TRIG-004": Rule(
        "TRIG-004",
        f"查询集规模与配比（约 {TARGET_TOTAL} 条，正负各 {MIN_PER_SIDE}–{MAX_PER_SIDE}）",
        "SHOULD",
        _EVAL,
        "补齐正例与负例；负例太少会高估触发质量",
    ),
    "TRIG-005": Rule(
        "TRIG-005",
        f"train 占比 {TRAIN_SHARE_MIN:.0%}–{TRAIN_SHARE_MAX:.0%}（固定切分，只据 train 修订）",
        "HOUSE",
        _EVAL,
        "按约 6:4 切分 train/validation；validation 只用于泛化终测，不参与修订",
    ),
    "TRIG-006": Rule(
        "TRIG-006",
        "负例宜以 near-miss 为主（category 标注情况）",
        "HOUSE",
        _EVAL,
        "给负例标 `category`（如 `negative-near-miss`）；明显不相关的负例测不出触发边界",
    ),
    "TRIG-007": Rule(
        "TRIG-007",
        "运行记录可解析为对象，且含非空 runs 数组与必需字段",
        "HOUSE",
        "本项目约定：运行记录与查询集分开文件，逐次可追溯",
        "每条记录写 query_id / run / loaded（严格布尔）/ evidence",
    ),
    "TRIG-008": Rule(
        "TRIG-008",
        f"每条查询至少 {RUNS_PER_QUERY} 次运行",
        "SHOULD",
        _EVAL,
        "补跑；单次运行无法区分「稳定触发」与「碰巧触发」",
    ),
    "TRIG-009": Rule(
        "TRIG-009",
        f"触发率：正例 >{TRIGGER_THRESHOLD}、负例 <{TRIGGER_THRESHOLD}（数据足够时）",
        "HOUSE",
        _EVAL,
        "改 description：把没触发的正例里出现的说法写进描述；把误触发的负例与描述区分开",
    ),
    "TRIG-010": Rule(
        "TRIG-010",
        "运行记录可归属：query_id 必须在查询集中，loaded 必须是布尔",
        "HOUSE",
        "旧体系实测：非布尔 loaded 被当成「未触发」静默改变计分",
        "修正 query_id 与 loaded；不要用字符串冒充布尔",
    ),
}


@dataclass
class Queryset:
    """`evals/trigger-queryset.json` 的解析结果。"""

    path: Path | None = None
    data: dict = field(default_factory=dict)
    queries: list[dict] = field(default_factory=list)
    error: str = ""

    @property
    def present(self) -> bool:
        return self.path is not None


def _res(rule: Rule, status: str, evidence: str = "") -> Result:
    return Result(rid=rule.rid, title=rule.title, status=status, level=rule.level,
                  evidence=evidence,
                  remediation=rule.remediation if status in (FAIL, WARN) else "")


def _summarize(items: list[str], limit: int = 5) -> str:
    if not items:
        return ""
    head = "；".join(items[:limit])
    return head + (f"；等共 {len(items)} 处" if len(items) > limit else "")


def _is_bool(value: object) -> bool:
    return isinstance(value, bool)


def read_queryset(skill_dir: Path) -> Queryset:
    path = Path(skill_dir) / "evals" / QUERYSET_NAME
    if not path.is_file():
        return Queryset()
    doc = Queryset(path=path)
    data, error = read_json(path)
    if error:
        doc.error = error
        return doc
    if not isinstance(data, dict):
        doc.error = f"顶层必须是对象，实为 {type(data).__name__}"
        return doc
    doc.data = data
    queries = data.get("queries")
    if isinstance(queries, list):
        doc.queries = [q for q in queries if isinstance(q, dict)]
    return doc


# --------------------------------------------------------------------------- #
# 查询集
# --------------------------------------------------------------------------- #


def _check_queryset(doc: Queryset) -> list[Result]:
    out: list[Result] = []
    if doc.error:
        out.append(_res(RULES["TRIG-001"], FAIL, f"evals/{QUERYSET_NAME}: {doc.error}"))
        for rid in ("TRIG-002", "TRIG-003", "TRIG-004", "TRIG-005", "TRIG-006"):
            out.append(_res(RULES[rid], SKIP, "未执行：查询集无法解析，先修 TRIG-001"))
        return out
    out.append(_res(RULES["TRIG-001"], PASS, f"evals/{QUERYSET_NAME} 可解析"))

    problems: list[str] = []
    name = doc.data.get("skill_name")
    if not isinstance(name, str) or not name.strip():
        problems.append("skill_name 缺失或非空字符串")
    raw = doc.data.get("queries")
    if not isinstance(raw, list):
        problems.append(f"queries 缺失或不是数组（实为 {type(raw).__name__}）")
    elif not raw:
        problems.append("queries 是空数组")
    out.append(_res(RULES["TRIG-001"], FAIL if problems else PASS,
                    "；".join(problems) if problems
                    else f"skill_name={name!r}，{len(raw)} 条查询"))

    field_bad: list[str] = []
    ids: list[str] = []
    for idx, item in enumerate(doc.queries, 1):
        label = f"第 {idx} 条"
        pid = item.get("id")
        if not (isinstance(pid, str) and pid.strip()) and not isinstance(pid, int):
            field_bad.append(f"{label} 缺 id")
        else:
            ids.append(str(pid))
        query = item.get("query")
        if not isinstance(query, str) or not query.strip():
            field_bad.append(f"{label} 的 query 应为非空字符串")
        if not _is_bool(item.get("should_trigger")):
            field_bad.append(f"{label} 的 should_trigger 必须是布尔"
                             f"（实为 {item.get('should_trigger')!r}）")
        if item.get("subset") not in ("train", "validation"):
            field_bad.append(f"{label} 的 subset 应为 train/validation"
                             f"（实为 {item.get('subset')!r}）")
    if not doc.queries and isinstance(raw, list) and raw:
        field_bad.append("queries 里没有一条是对象")
    out.append(_res(RULES["TRIG-002"], FAIL if field_bad else PASS,
                    _summarize(field_bad) if field_bad
                    else f"{len(doc.queries)} 条字段齐备"))

    dupes = sorted({i for i in ids if ids.count(i) > 1})
    out.append(_res(RULES["TRIG-003"], FAIL if dupes else PASS,
                    f"重复 id: {_summarize(dupes)}" if dupes else f"{len(ids)} 个 id 均唯一"))

    positives = [q for q in doc.queries if q.get("should_trigger") is True]
    negatives = [q for q in doc.queries if q.get("should_trigger") is False]
    total = len(doc.queries)
    size_issues: list[str] = []
    if total < MIN_TOTAL:
        size_issues.append(f"总数 {total} 少于 {MIN_TOTAL}（数据太少，结论不稳）")
    if positives and len(positives) < MIN_PER_SIDE:
        size_issues.append(f"正例 {len(positives)} 少于 {MIN_PER_SIDE}")
    if negatives and len(negatives) < MIN_PER_SIDE:
        size_issues.append(f"负例 {len(negatives)} 少于 {MIN_PER_SIDE}")
    if not negatives:
        size_issues.append("没有负例（无法测误触发）")
    if abs(total - TARGET_TOTAL) > 4 and total >= MIN_TOTAL:
        size_issues.append(f"总数 {total} 偏离官方口径 ~{TARGET_TOTAL} 较多")
    if not positives:
        size_issues.append("没有正例")
    out.append(_res(RULES["TRIG-004"], WARN if size_issues else PASS,
                    _summarize(size_issues) if size_issues
                    else f"{total} 条（正 {len(positives)} / 负 {len(negatives)}）"))

    train = [q for q in doc.queries if q.get("subset") == "train"]
    validation = [q for q in doc.queries if q.get("subset") == "validation"]
    if not validation:
        out.append(_res(RULES["TRIG-005"], WARN,
                        "没有 validation 项：泛化终测无从进行（train 只用于修订）"))
    elif not train:
        out.append(_res(RULES["TRIG-005"], WARN, "没有 train 项：没有可用于修订的切分"))
    else:
        share = len(train) / (len(train) + len(validation))
        if not (TRAIN_SHARE_MIN <= share <= TRAIN_SHARE_MAX):
            out.append(_res(RULES["TRIG-005"], WARN,
                            f"train 占比 {share:.0%} 不在 "
                            f"{TRAIN_SHARE_MIN:.0%}–{TRAIN_SHARE_MAX:.0%} 之间"
                            f"（train {len(train)} / validation {len(validation)}）"))
        else:
            out.append(_res(RULES["TRIG-005"], PASS,
                            f"train {len(train)} / validation {len(validation)}"
                            f"（train 占比 {share:.0%}）"))

    if not negatives:
        out.append(_res(RULES["TRIG-006"], INFO, "不适用：没有负例"))
    else:
        tagged = [q for q in negatives if isinstance(q.get("category"), str) and q["category"]]
        near = [q for q in tagged
                if any(hint in str(q.get("category", "")).lower() for hint in NEAR_MISS_HINTS)]
        if not tagged:
            out.append(_res(RULES["TRIG-006"], WARN,
                            f"{len(negatives)} 条负例都没标 category，"
                            f"无法判断是否以 near-miss 为主"))
        elif len(near) < len(negatives) / 2:
            out.append(_res(RULES["TRIG-006"], WARN,
                            f"标为 near-miss 的负例仅 {len(near)}/{len(negatives)}；"
                            f"明显不相关的负例测不出触发边界"))
        else:
            out.append(_res(RULES["TRIG-006"], PASS,
                            f"{len(near)}/{len(negatives)} 条负例标为 near-miss"))
    return out


# --------------------------------------------------------------------------- #
# 运行记录
# --------------------------------------------------------------------------- #


def _check_runs(skill_dir: Path, doc: Queryset) -> list[Result]:
    out: list[Result] = []
    path = Path(skill_dir) / "evals" / RUNS_NAME
    if not path.is_file():
        out.append(_res(RULES["TRIG-007"], SKIP,
                        f"未执行：没有 evals/{RUNS_NAME}（尚未跑过触发评测）"))
        for rid in ("TRIG-008", "TRIG-009", "TRIG-010"):
            out.append(_res(RULES[rid], SKIP, f"未执行：没有 evals/{RUNS_NAME}"))
        return out

    data, error = read_json(path)
    if error or not isinstance(data, dict):
        reason = error or f"顶层必须是对象（实为 {type(data).__name__}）"
        out.append(_res(RULES["TRIG-007"], FAIL, f"evals/{RUNS_NAME}: {reason}"))
        for rid in ("TRIG-008", "TRIG-009", "TRIG-010"):
            out.append(_res(RULES[rid], SKIP, f"未执行：{reason}"))
        return out

    runs = data.get("runs")
    if not isinstance(runs, list) or not runs:
        out.append(_res(RULES["TRIG-007"], FAIL,
                        f"evals/{RUNS_NAME}: runs 必须是至少含一条记录的数组"))
        for rid in ("TRIG-008", "TRIG-009", "TRIG-010"):
            out.append(_res(RULES[rid], SKIP, "未执行：runs 不可用"))
        return out

    field_bad: list[str] = []
    for idx, item in enumerate(runs, 1):
        if not isinstance(item, dict):
            field_bad.append(f"第 {idx} 条不是对象")
            continue
        if not (isinstance(item.get("query_id"), str) and item["query_id"].strip()):
            field_bad.append(f"第 {idx} 条缺 query_id")
        if not _is_bool(item.get("loaded")):
            field_bad.append(f"第 {idx} 条 loaded 必须是布尔（实为 {item.get('loaded')!r}）")
    out.append(_res(RULES["TRIG-007"], FAIL if field_bad else PASS,
                    _summarize(field_bad) if field_bad
                    else f"evals/{RUNS_NAME}: {len(runs)} 条运行记录"))

    known = {str(q.get("id")) for q in doc.queries}
    unknown = sorted({str(r.get("query_id")) for r in runs
                      if isinstance(r, dict) and str(r.get("query_id")) not in known}) \
        if known else []
    non_bool = [str(r.get("query_id")) for r in runs
                if isinstance(r, dict) and not _is_bool(r.get("loaded"))]
    issues = []
    if unknown:
        issues.append(f"query_id 不在查询集中: {_summarize(unknown)}")
    if non_bool:
        issues.append(f"loaded 非布尔（旧体系会静默当成未触发）: {_summarize(non_bool)}")
    if not known:
        issues.append("查询集不可用，无法判断归属")
    out.append(_res(RULES["TRIG-010"], WARN if issues else PASS,
                    _summarize(issues) if issues else "运行记录均可归属且类型正确"))

    counts: dict[str, int] = {}
    loaded: dict[str, int] = {}
    for item in runs:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("query_id"))
        counts[pid] = counts.get(pid, 0) + 1
        if item.get("loaded") is True:
            loaded[pid] = loaded.get(pid, 0) + 1
    thin = sorted(pid for pid, n in counts.items() if n < RUNS_PER_QUERY)
    missing = sorted(known - set(counts)) if known else []
    thin_all = sorted(set(thin) | set(missing))
    if thin_all:
        out.append(_res(RULES["TRIG-008"], WARN,
                        f"运行次数不足 {RUNS_PER_QUERY} 次的查询: "
                        f"{_summarize([f'{p}（{counts.get(p, 0)} 次）' for p in thin_all])}"))
    else:
        out.append(_res(RULES["TRIG-008"], PASS,
                        f"每条查询均 ≥{RUNS_PER_QUERY} 次（共 {len(runs)} 条记录）"))

    insufficient = [p for p in thin_all]
    rates: list[str] = []
    bad_pos: list[str] = []
    bad_neg: list[str] = []
    for item in doc.queries:
        pid = str(item.get("id"))
        n = counts.get(pid, 0)
        if n == 0:
            continue
        rate = loaded.get(pid, 0) / n
        verifiable = n >= RUNS_PER_QUERY
        if item.get("should_trigger") is True and rate <= TRIGGER_THRESHOLD and verifiable:
            bad_pos.append(f"{pid} 触发率 {rate:.0%}（正例应 >{TRIGGER_THRESHOLD:.0%}）")
        elif item.get("should_trigger") is False and rate >= TRIGGER_THRESHOLD and verifiable:
            bad_neg.append(f"{pid} 触发率 {rate:.0%}（负例应 <{TRIGGER_THRESHOLD:.0%}）")
        if not verifiable:
            rates.append(f"{pid}={rate:.0%}(n={n})")
    if not doc.queries:
        out.append(_res(RULES["TRIG-009"], SKIP, "未执行：查询集不可用"))
    elif bad_pos or bad_neg:
        out.append(_res(RULES["TRIG-009"], FAIL,
                        _summarize(bad_pos + bad_neg)))
    elif insufficient:
        out.append(_res(RULES["TRIG-009"], WARN,
                        f"数据不足，未给阈值结论（不足 {RUNS_PER_QUERY} 次的查询: "
                        f"{_summarize(insufficient)}）"))
    else:
        out.append(_res(RULES["TRIG-009"], PASS,
                        f"正负例触发率均在阈值正确一侧（已核对 {len(rates) or len(doc.queries)} 条）"))
    return out


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #


def check_trigger(skill_dir: Path) -> Report:
    """校验触发评测资产。没有资产时 TRIG-000 记 WARN、其余记 INFO（不适用）。"""
    skill_dir = Path(skill_dir)
    report = Report(target=str(skill_dir), stage="evals")
    doc = read_queryset(skill_dir)

    if not doc.present:
        legacy = skill_dir / LEGACY_DIR / LEGACY_QUERYSET_NAME
        if legacy.is_file():
            report.add(_res(RULES["TRIG-000"], WARN,
                            f"检测到旧落点 {LEGACY_DIR.as_posix()}/{LEGACY_QUERYSET_NAME}："
                            f"请迁移到 evals/{QUERYSET_NAME}（单一来源；"
                            f"两处并存正是旧体系对不上账的原因）"))
        else:
            report.add(_res(RULES["TRIG-000"], WARN,
                            f"技能没有 evals/{QUERYSET_NAME}："
                            f"没有任何「会不会被触发」的证据（官方不覆盖这一层）"))
        for rid, rule in RULES.items():
            if rid == "TRIG-000":
                continue
            report.add(_res(rule, INFO,
                            f"不适用：技能未提供 evals/{QUERYSET_NAME}"))
        report.meta["触发评测"] = f"无 evals/{QUERYSET_NAME}"
        return report

    results = [_res(RULES["TRIG-000"], PASS,
                    f"提供触发评测查询集（{len(doc.queries)} 条查询）")]
    results.extend(_check_queryset(doc))
    results.extend(_check_runs(skill_dir, doc))

    for res in results:
        report.add(res)
    produced = {r.rid for r in results}
    for rid, rule in RULES.items():
        if rid not in produced:
            report.add(_res(rule, SKIP, "实现遗漏：本规则未产生记录（请报 bug）"))
    report.meta["触发评测"] = str(doc.path)
    report.meta["查询数"] = str(len(doc.queries))
    return report
