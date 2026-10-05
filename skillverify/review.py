"""review —— 语义评审：提示词目录、任务包、回写校验与汇总（三档执行器同一 schema）。

**这一层解决的矛盾**：机械检查（spec/lint/evalx）能覆盖的只是一部分；"写得对不对、
好不好用、会不会误导 Agent"必须由人或 LLM 判断。旧体系有 29 条提示词，但只有提示词
没有判据，于是回写全是"我看了，还行"——**评审做了，却不可用**。本模块把评审变成
"有判据、有证据、可校验、可汇总"的流程。

**三档执行器（用户第 2 点要求）产出同一 schema**：
- 档 1 CLI 自动：把任务包喂给任意命令（`--runner`），收它的 stdout 当回写；
- 档 2 会话任务包：`review pack` 生成任务包与模板 → 任意 LLM/人填 → `review collect`；
- 档 3 人工兜底：手写同一个 JSON 模板 → `review collect`。
三档的产物都由 `validate_writeback` 校验，都汇入同一份记录，都进同一张报告。

**回写 schema**（`skillverify.review/1`）：
`{"schema", "skill", "reviewer", "tier", "generated_at", "prompt_ids", "results":[
{"prompt_id", "verdict": PASS|FAIL|NA, "evidence", "finding", "suggestion"}]}`

**判定纪律（逐条对应旧体系的失效点）**：
- **无签署的评审等于没有评审**：`reviewer` 为空直接 FAIL。
- **PASS 也要证据**，且证据必须**可定位**（文件名:行、原文片段、具体计数）——
  只写"符合要求"不算证据。
- **证据不得复述判据**：与提示词/判据文本高度重合即 WARN（这是"切实有效"的关键，
  旧体系 29 条提示词的回写大量是判据的改写）。
- **FAIL 必须写清问题**；**NA 必须说明不适用的理由**。
- **同一提示词被评两次且结论冲突** → 记冲突，须人工裁决（双评场景）。
- 覆盖不完整要显式列出来，不许默认通过。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .encoding import read_json, write_text
from .report import FAIL, INFO, PASS, SKIP, WARN, Report, Result, Rule

#: 提示词目录（随包分发的数据文件；提示词是数据，不是代码）
CATALOG_PATH = Path(__file__).resolve().parent / "data" / "review-prompts.json"

#: 回写契约（三档执行器共用）
WRITEBACK_SCHEMA = "skillverify.review/1"

#: 汇总后落到中央留痕的记录
RECORD_SCHEMA = "skillverify.review-record/1"

#: 目录里每条提示词必须有的字段
REQUIRED_FIELDS = ("id", "family", "title", "stage", "when", "inputs", "prompt",
                   "pass_criteria", "fail_criteria", "evidence_required", "blocking")

VERDICTS = ("PASS", "FAIL", "NA")

#: 各家族的显示顺序（设计 → 编写 → 测试 → 运行）
FAMILY_ORDER = ("D", "W", "E", "R")
FAMILY_STAGE = {"D": "设计期", "W": "编写期", "E": "测试期", "R": "运行期"}

#: 证据里应当出现"可定位信息"的形态
LOCATABLE_RE = re.compile(
    r"[\w./\\-]+\.[A-Za-z0-9]{1,6}\b"      # 文件名/路径
    r"|:\d+"                                # 行号
    r"|`[^`]{2,}`"                          # 反引号片段
    r"|「[^」]{2,}」|\"[^\"]{4,}\"|“[^”]{4,}”"  # 引用片段
    r"|\d"                                  # 具体计数
)

#: 证据最小长度（低于此值几乎不可能说清位置或内容）
MIN_EVIDENCE = 12

#: FAIL/NA 的说明最小长度
MIN_FINDING = 8

RULES: dict[str, Rule] = {
    "REV-000": Rule(
        "REV-000",
        "语义评审记录（存在、新鲜、结论可用）",
        "HOUSE",
        "本项目流程约定：机械层之外的判断必须留下可追溯的记录",
        "跑 `skillverify review pack` 生成任务包，评审后 `review collect` 汇总；"
        "或用 `deliver --skip-review` 显式跳过并留痕",
    ),
    "REV-001": Rule(
        "REV-001",
        "回写 JSON 可解析且 schema 正确",
        "HOUSE",
        WRITEBACK_SCHEMA,
        "用 `review pack` 生成的模板填写，不要手写结构",
    ),
    "REV-002": Rule(
        "REV-002",
        "skill 与 reviewer 均须填写",
        "HOUSE",
        "无签署的评审等于没有评审（出了事无法追溯是谁判的）",
        "填上被评审的技能名与评审判定人（人或模型标识）",
    ),
    "REV-003": Rule(
        "REV-003",
        "results 为非空数组且每条含 prompt_id / verdict / evidence",
        "HOUSE",
        WRITEBACK_SCHEMA,
        "按模板补齐；缺字段的条目无法被汇总",
    ),
    "REV-004": Rule(
        "REV-004",
        "prompt_id 必须存在于提示词目录",
        "HOUSE",
        "目录见 `skillverify review prompts`",
        "改成目录中的 id；自造 id 无法与其它轮次对比",
    ),
    "REV-005": Rule(
        "REV-005",
        "verdict 只能是 PASS / FAIL / NA",
        "HOUSE",
        WRITEBACK_SCHEMA,
        "不要用「基本通过」「待定」等无法汇总的措辞",
    ),
    "REV-006": Rule(
        "REV-006",
        "evidence 必须是可定位的实质证据（不得复述判据）",
        "HOUSE",
        "判据见目录中的 pass_criteria/fail_criteria",
        "引用具体位置或原文片段（如 `SKILL.md:42`、输出文件里的一句话、具体计数）",
    ),
    "REV-007": Rule(
        "REV-007",
        "FAIL 必须写清问题（finding）",
        "HOUSE",
        WRITEBACK_SCHEMA,
        "写清哪一处、为什么不行——只有结论的 FAIL 无法指导修复",
    ),
    "REV-008": Rule(
        "REV-008",
        "NA 必须说明不适用的理由",
        "HOUSE",
        WRITEBACK_SCHEMA,
        "在 evidence 里写明为什么这条提示词不适用（例如技能没有脚本）",
    ),
    "REV-009": Rule(
        "REV-009",
        "覆盖完整：声明的提示词都要有结论",
        "HOUSE",
        "未覆盖项不等于通过",
        "补评缺失的提示词，或在任务包里显式声明本次只评子集",
    ),
    "REV-010": Rule(
        "REV-010",
        "同一提示词不得有两条互相冲突的结论",
        "HOUSE",
        "双评场景：两人（或两次）结论不一致时须人工裁决",
        "留下裁决结论，并注明以哪次为准",
    ),
    "REV-011": Rule(
        "REV-011",
        "阻断项的 FAIL 需要修复建议",
        "HOUSE",
        "只有问题没有方向的 FAIL 会让使用者停在原地",
        "补一句可执行的 suggestion",
    ),
    "REV-012": Rule(
        "REV-012",
        "评委须先通过校准样本（判错则本轮结论不可用）",
        "HOUSE",
        "skill-up 的 Judges 校准实践；旧体系未覆盖",
        "先按样本材料的判据判一遍校准样本（答案明确），判错就换评委或先统一判据理解，"
        "再重做本轮评审",
    ),
}


# --------------------------------------------------------------------------- #
# 提示词目录
# --------------------------------------------------------------------------- #


@dataclass
class Prompt:
    """一条语义评审提示词（含判据与证据要求）。"""

    id: str
    family: str
    title: str
    stage: str
    when: str
    inputs: list[str]
    prompt: str
    pass_criteria: list[str]
    fail_criteria: list[str]
    evidence_required: str
    blocking: bool
    legacy_id: str = ""
    legacy_source: str = ""
    official: str = ""
    #: 与相邻提示词的分工（id -> 说明）。旧体系里有几对条目本就重叠，
    #: 这里把"谁负责判什么"写进数据，而不是合并条目（旧体系 29 条保留原编号，
    #: 本项目可在其后**新增**条目，新增者必须在 `legacy_source` 里声明来历）。
    overlaps: dict[str, str] = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.raw) if self.raw else {
            "id": self.id, "family": self.family, "title": self.title, "stage": self.stage,
            "when": self.when, "inputs": self.inputs, "prompt": self.prompt,
            "pass_criteria": self.pass_criteria, "fail_criteria": self.fail_criteria,
            "evidence_required": self.evidence_required, "blocking": self.blocking,
            "legacy_id": self.legacy_id, "legacy_source": self.legacy_source,
            "official": self.official,
        }


class CatalogError(Exception):
    """提示词目录缺失或结构不合法（随包数据，出问题必须立刻炸）。"""


def load_catalog(path: Path | None = None) -> list[Prompt]:
    """读取并校验提示词目录。结构问题一律抛异常（绝不静默降级成空目录）。"""
    target = Path(path) if path else CATALOG_PATH
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise CatalogError(f"提示词目录不可读: {target}（{exc.strerror or exc}）") from exc
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"提示词目录不是合法 JSON: {target}（{exc}）") from exc
    entries = data.get("prompts") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise CatalogError(f"提示词目录缺少非空的 prompts 数组: {target}")

    prompts: list[Prompt] = []
    seen: set[str] = set()
    for idx, item in enumerate(entries, 1):
        if not isinstance(item, dict):
            raise CatalogError(f"第 {idx} 条提示词不是对象")
        missing = [k for k in REQUIRED_FIELDS if k not in item]
        if missing:
            raise CatalogError(f"第 {idx} 条提示词缺字段 {missing}")
        pid = str(item["id"])
        if pid in seen:
            raise CatalogError(f"提示词 id 重复: {pid}")
        seen.add(pid)
        family = str(item["family"])
        if family not in FAMILY_ORDER:
            raise CatalogError(f"{pid} 的 family 非法: {family!r}")
        overlaps = item.get("overlaps") or {}
        if not isinstance(overlaps, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in overlaps.items()):
            raise CatalogError(f"{pid} 的 overlaps 必须是「id -> 分工说明」的字符串映射")
        prompts.append(Prompt(
            id=pid, family=family, title=str(item["title"]), stage=str(item["stage"]),
            when=str(item["when"]), inputs=[str(x) for x in item["inputs"]],
            prompt=str(item["prompt"]),
            pass_criteria=[str(x) for x in item["pass_criteria"]],
            fail_criteria=[str(x) for x in item["fail_criteria"]],
            evidence_required=str(item["evidence_required"]),
            blocking=bool(item["blocking"]),
            legacy_id=str(item.get("legacy_id", "")),
            legacy_source=str(item.get("legacy_source", "")),
            official=str(item.get("official", "")),
            overlaps={str(k): str(v) for k, v in (item.get("overlaps") or {}).items()},
            raw=item,
        ))
    known = {p.id for p in prompts}
    for prompt in prompts:
        unknown = sorted(k for k in prompt.overlaps if k not in known)
        if unknown:
            raise CatalogError(f"{prompt.id} 的 overlaps 指向不存在的 id: {unknown}")
    prompts.sort(key=lambda p: (FAMILY_ORDER.index(p.family), p.id))
    return prompts


def select_prompts(prompts: list[Prompt], spec: str | None,
                   families: list[str] | None = None) -> list[Prompt]:
    """按 `--prompts W-01,W-13` 或 `--family W` 选子集；都没给则全选。"""
    out = list(prompts)
    if families:
        wanted = {f.strip().upper() for f in families if f.strip()}
        unknown = wanted - set(FAMILY_ORDER)
        if unknown:
            raise CatalogError(f"未知家族 {sorted(unknown)}；可用 {list(FAMILY_ORDER)}")
        out = [p for p in out if p.family in wanted]
    if spec:
        ids = [x.strip() for x in re.split(r"[,\s]+", spec) if x.strip()]
        known = {p.id for p in prompts}
        unknown = [x for x in ids if x not in known]
        if unknown:
            raise CatalogError(f"未知提示词 id {unknown}")
        out = [p for p in out if p.id in set(ids)]
    return out


def render_prompts_md(prompts: list[Prompt]) -> str:
    lines = [
        f"# 语义评审提示词目录（{len(prompts)} 条）",
        "",
        "每条提示词都带 **PASS/FAIL 判据** 与 **证据要求**——判据是为了让评审结论可汇总，",
        "证据要求是为了让结论可复核。回写格式见 `review pack` 生成的任务包模板。",
        "",
    ]
    current = None
    for prompt in prompts:
        if prompt.family != current:
            current = prompt.family
            lines += [f"## {current} 组 · {FAMILY_STAGE[current]}", ""]
        block = "（FAIL 阻断交付）" if prompt.blocking else ""
        lines += [
            f"### {prompt.id} {prompt.title}{block}",
            "",
            f"- **适用**：{prompt.when}",
            f"- **材料**：{', '.join(f'`{i}`' for i in prompt.inputs)}",
        ]
        if prompt.legacy_source:
            lines.append(f"- **旧体系出处**：{prompt.legacy_source}")
        if prompt.official:
            lines.append(f"- **官方条款**：{prompt.official}")
        lines += ["", prompt.prompt, "", "**PASS 判据**", ""]
        lines += [f"- {c}" for c in prompt.pass_criteria]
        lines += ["", "**FAIL 判据**", ""]
        lines += [f"- {c}" for c in prompt.fail_criteria]
        lines += ["", f"**证据要求**：{prompt.evidence_required}"]
        if prompt.overlaps:
            lines += ["", "**与相邻条目的分工**", ""]
            lines += [f"- {pid}：{why}" for pid, why in sorted(prompt.overlaps.items())]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# 任务包
# --------------------------------------------------------------------------- #

#: 追加到每条提示词后面的输出格式说明（只写一次，避免 29 处各写一遍漂移）
OUTPUT_CONTRACT = """\
## 回写格式（必须遵守）

把结论写进任务包同目录的 `*-review-template.json`（或另存一份同结构的 JSON）：

```json
{
  "schema": "skillverify.review/1",
  "skill": "<被评审的技能名>",
  "reviewer": "<你的标识：人名或模型名>",
  "tier": "pack",
  "generated_at": "<ISO 8601 时间>",
  "prompt_ids": ["<本次覆盖的提示词 id>"],
  "results": [
    {"prompt_id": "W-01", "verdict": "PASS|FAIL|NA",
     "evidence": "可定位的证据（文件:行 / 原文片段 / 具体计数）",
     "finding": "FAIL 时必填：哪一处、为什么不行",
     "suggestion": "可选：怎么改"}
  ]
}
```

硬性要求：
1. **每一条结论都要证据**，且证据必须能被人按图索骥地核到（写清文件与位置，或直接引用原文）。
2. **不要复述判据**——复述判据会被机械校验标为"疑似非证据"。
3. FAIL 必须写 `finding`；NA 必须在 `evidence` 里写明不适用的理由。
4. 只评你确有材料判断的条目；没材料就记 NA 并说明，不要猜。
"""


def build_pack(
    skill_dir: Path,
    prompts: list[Prompt],
    *,
    out_dir: Path | None = None,
    split: bool = False,
) -> list[Path]:
    """生成任务包：人读的 Markdown + 待填的 JSON 模板 + manifest。返回写出的文件。"""
    from .watch import fingerprint  # 复用同一份"内容指纹"，避免两处定义漂移

    skill_dir = skill_dir.resolve()
    name = skill_dir.name
    out = Path(out_dir) if out_dir else (skill_dir.parent / f"{name}-review")
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if split:
        per_prompt_dir = out / name
        per_prompt_dir.mkdir(parents=True, exist_ok=True)
        for prompt in prompts:
            body = render_prompts_md([prompt])
            path = per_prompt_dir / f"{prompt.id}.md"
            write_text(path, _pack_header(name, [prompt])
                       + (render_calibration_md() if prompt is prompts[0] else "")
                       + body + "\n" + OUTPUT_CONTRACT)
            written.append(path)
    else:
        path = out / f"{name}-review-pack.md"
        write_text(path, _pack_header(name, prompts) + render_calibration_md()
                   + render_prompts_md(prompts) + "\n" + OUTPUT_CONTRACT)
        written.append(path)

    template = {
        "schema": WRITEBACK_SCHEMA,
        "skill": name,
        "reviewer": "",
        "tier": "pack",
        # 评委校准（第 0 步）：判错的结论不可用。留空表示本轮未做校准（记 INFO，不阻断）。
        "calibration": [{"sample_id": s.get("id"), "verdict": ""}
                        for s in load_calibration()],
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "prompt_ids": [p.id for p in prompts],
        "results": [
            {"prompt_id": p.id,
             "verdict": "",
             "evidence": "",
             "finding": "" if p.blocking else "",
             "suggestion": ""}
            for p in prompts
        ],
    }
    template_path = out / f"{name}-review-template.json"
    write_text(template_path, json.dumps(template, ensure_ascii=False, indent=2) + "\n")
    written.append(template_path)

    manifest = {
        "schema": "skillverify.review-manifest/1",
        "skill": name,
        "skill_dir": str(skill_dir),
        "fingerprint": fingerprint(skill_dir),
        "prompt_ids": [p.id for p in prompts],
        "blocking_prompt_ids": [p.id for p in prompts if p.blocking],
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "tool_version": __version__,
        "writeback_schema": WRITEBACK_SCHEMA,
        "split": split,
    }
    manifest_path = out / f"{name}-review-manifest.json"
    write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    written.append(manifest_path)
    return written


def _pack_header(name: str, prompts: list[Prompt]) -> str:
    blocking = [p.id for p in prompts if p.blocking]
    return (
        f"# 语义评审任务包 · {name}\n\n"
        f"- 待评技能：`{name}`\n"
        f"- 本轮提示词：{len(prompts)} 条（{', '.join(p.id for p in prompts)}）\n"
        f"- 其中 FAIL 会阻断交付：{', '.join(blocking) if blocking else '（无）'}\n"
        f"- 生成工具：skillverify {__version__}\n\n"
        "## 怎么用这个包\n\n"
        "1. 把本文件（以及必要时技能目录里的材料）交给任意 LLM 或人；\n"
        "2. 按每条提示词的 PASS/FAIL 判据逐条判断，**每条都要给可定位的证据**；\n"
        "3. 把结论填进同目录的 `*-review-template.json`；\n"
        "4. 跑 `skillverify review collect <填好的文件>` 汇总进中央记录。\n\n"
        "> 若本轮包含 **E-02 / E-03 / E-06 / E-07 / E-08**，先跑 "
        "`skillverify review material <技能目录>` 生成它们所需的材料\n"
        "> （description diff、修订信号、盲评 A/B、工作区数字）；"
        "生成不了时它会逐条说明缺什么。\n\n"
        "---\n\n"
    )


# --------------------------------------------------------------------------- #
# 回写校验
# --------------------------------------------------------------------------- #


def _res(rule: Rule, status: str, evidence: str = "") -> Result:
    return Result(rid=rule.rid, title=rule.title, status=status, level=rule.level,
                  evidence=evidence,
                  remediation=rule.remediation if status in (FAIL, WARN) else "")


def _norm(text: str) -> str:
    return re.sub(r"[\s，。、；：,.;:!?！？（）()「」\"'`]+", "", text or "")


def _is_restatement(evidence: str, prompt: Prompt) -> bool:
    """证据是否只是把判据/提示词换个说法抄一遍。"""
    ev = _norm(evidence)
    if len(ev) < 6:
        return False
    for source in (*prompt.pass_criteria, *prompt.fail_criteria, prompt.prompt):
        src = _norm(source)
        if not src:
            continue
        if ev == src or (len(ev) >= 8 and (ev in src or src in ev)):
            return True
    return False


#: 评委校准样本（数据文件）：让评委先判"答案明确"的几个样本
CALIBRATION_PATH = Path(__file__).resolve().parent / "data" / "judge-calibration.json"


def load_calibration() -> list[dict]:
    """读校准样本；文件缺失/损坏时返回空列表（校准是增强项，不该让工具崩）。"""
    try:
        raw = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    samples = raw.get("samples") if isinstance(raw, dict) else None
    return [s for s in samples if isinstance(s, dict)] if isinstance(samples, list) else []


def render_calibration_md(samples: list[dict] | None = None) -> str:
    """把校准样本渲染成任务包里的一节（第 0 步）。"""
    samples = load_calibration() if samples is None else samples
    if not samples:
        return ""
    lines = ["## 第 0 步（先做）：评委校准", "",
             "先判下面这几个**答案明确**的样本，把结果写进回写的 `calibration` 数组：",
             "判错说明你这个评委（人或模型）分不稳，本轮结论不可用。", ""]
    for sample in samples:
        lines += [f"### {sample.get('id')}（{sample.get('title', '')}）", "",
                  "```", str(sample.get("material", "")).strip(), "```", ""]
    return "\n".join(lines) + "\n"


def check_calibration(data: dict, *, label: str = "") -> Result:
    """REV-012：评委连校准样本都判错 → 本轮结论不可用。

    没做校准记 SKIP（未覆盖，默认不阻断）——校准是"增强可信度"，不是人人都要跑的仪式；
    但**做了且判错**就是硬问题：说明给结论的评委不可靠。
    """
    samples = load_calibration()
    prefix = f"{label}: " if label else ""
    if not samples:
        return _res(RULES["REV-012"], INFO, f"{prefix}不适用：校准样本数据缺失")
    recorded = data.get("calibration")
    if not isinstance(recorded, list) or not recorded:
        # 记 INFO 而不是 SKIP：校准是**增强项**（做了才更可信），不是每轮都必须的仪式。
        # 强制它会让所有"合格回写"恒返回 2；而"做了却判错"才是真问题（见下）。
        return _res(RULES["REV-012"], INFO,
                    f"{prefix}不适用：没有 calibration 数组（未做校准；"
                    f"补上它能让本轮结论更可信）")
    expected = {str(s.get("id")): str(s.get("expected", "")).upper() for s in samples}
    got = {}
    for item in recorded:
        if isinstance(item, dict):
            got[str(item.get("sample_id"))] = str(item.get("verdict", "")).upper()
    wrong = [f"{sid}（应 {expected[sid]}，实得 {got[sid]}）"
             for sid in sorted(expected) if got.get(sid) and got.get(sid) != expected[sid]]
    missing = [sid for sid in sorted(expected) if sid not in got]
    if wrong:
        return _res(RULES["REV-012"], FAIL,
                    f"{prefix}评委判错了校准样本：{'；'.join(wrong)}——"
                    f"校准不过，这一轮评审结论不可用（换评委或先统一判据理解）")
    if missing:
        return _res(RULES["REV-012"], WARN,
                    f"{prefix}校准样本没判全，缺 {'、'.join(missing)}（判全才能说明分得稳）")
    return _res(RULES["REV-012"], PASS, f"{prefix}{len(expected)} 个校准样本全部判对")


def validate_writeback(data: object, catalog: list[Prompt], *,
                       where: str = "") -> tuple[list[Result], dict]:
    """校验一份回写，返回 (结果列表, 归一化后的回写)。判定只看字段，不看措辞。"""
    by_id = {p.id: p for p in catalog}
    out: list[Result] = []
    label = where or "回写"

    if not isinstance(data, dict):
        out.append(_res(RULES["REV-001"], FAIL,
                        f"{label}: 顶层必须是对象（实为 {type(data).__name__}）"))
        return out, {}
    if data.get("schema") != WRITEBACK_SCHEMA:
        out.append(_res(RULES["REV-001"], FAIL,
                        f"{label}: schema 应为 {WRITEBACK_SCHEMA!r}"
                        f"（实为 {data.get('schema')!r}）"))
    else:
        out.append(_res(RULES["REV-001"], PASS, f"{label}: schema 正确"))

    who = []
    for key in ("skill", "reviewer"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            who.append(f"{key} 为空")
    out.append(_res(RULES["REV-002"], FAIL if who else PASS,
                    f"{label}: " + "；".join(who) if who
                    else f"{label}: skill={data['skill']!r} reviewer={data['reviewer']!r}"))

    results = data.get("results")
    if not isinstance(results, list) or not results:
        out.append(_res(RULES["REV-003"], FAIL,
                        f"{label}: results 必须是至少含一条结论的数组"))
        return out, {}
    field_bad: list[str] = []
    for idx, item in enumerate(results, 1):
        if not isinstance(item, dict):
            field_bad.append(f"第 {idx} 条不是对象")
            continue
        for key in ("prompt_id", "verdict", "evidence"):
            if not isinstance(item.get(key), str) or not (item.get(key) or "").strip():
                field_bad.append(f"第 {idx} 条缺 {key}")
    out.append(_res(RULES["REV-003"], FAIL if field_bad else PASS,
                    f"{label}: " + "；".join(field_bad) if field_bad
                    else f"{label}: {len(results)} 条结论字段齐备"))

    unknown = sorted({str(i.get("prompt_id")) for i in results
                      if isinstance(i, dict) and str(i.get("prompt_id")) not in by_id})
    out.append(_res(RULES["REV-004"], FAIL if unknown else PASS,
                    f"{label}: 不在目录中的 prompt_id: {', '.join(unknown[:5])}" if unknown
                    else f"{label}: prompt_id 均在目录中"))

    bad_verdict = sorted({str(i.get("verdict")) for i in results
                          if isinstance(i, dict) and i.get("verdict") not in VERDICTS})
    out.append(_res(RULES["REV-005"], FAIL if bad_verdict else PASS,
                    f"{label}: 非法 verdict {bad_verdict}" if bad_verdict
                    else f"{label}: verdict 取值合法"))

    out.append(check_calibration(data, label=label))

    thin: list[str] = []
    restated: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("prompt_id"))
        evidence = item.get("evidence") or ""
        if not isinstance(evidence, str):
            continue
        shortened = re.sub(r"\s+", "", evidence)
        if len(shortened) < MIN_EVIDENCE:
            thin.append(f"{pid}（仅 {len(shortened)} 字）")
        elif not LOCATABLE_RE.search(evidence):
            thin.append(f"{pid}（未见文件/行号/引用/计数）")
        prompt = by_id.get(pid)
        if prompt is not None and _is_restatement(evidence, prompt):
            restated.append(pid)
    out.append(_res(RULES["REV-006"],
                    FAIL if thin else (WARN if restated else PASS),
                    _summarize([f"{label}: {t} 的证据过于单薄" for t in thin]
                               + [f"{label}: {r} 的证据疑似复述判据" for r in restated])
                    if (thin or restated) else f"{label}: 证据均可定位"))

    no_finding = [str(i.get("prompt_id")) for i in results
                  if isinstance(i, dict) and i.get("verdict") == FAIL
                  and not (isinstance(i.get("finding"), str)
                           and len(re.sub(r"\s+", "", i.get("finding") or "")) >= MIN_FINDING)]
    out.append(_res(RULES["REV-007"], FAIL if no_finding else PASS,
                    f"{label}: FAIL 未写清问题: {', '.join(no_finding[:5])}" if no_finding
                    else f"{label}: FAIL 均写了问题"))

    bad_na = [str(i.get("prompt_id")) for i in results
              if isinstance(i, dict) and i.get("verdict") == "NA"
              and len(re.sub(r"\s+", "", (i.get("evidence") or ""))) < MIN_FINDING]
    out.append(_res(RULES["REV-008"], FAIL if bad_na else PASS,
                    f"{label}: NA 未说明理由: {', '.join(bad_na[:5])}" if bad_na
                    else f"{label}: NA 均说明了理由"))

    normalized = {
        "schema": WRITEBACK_SCHEMA,
        "skill": data.get("skill") if isinstance(data.get("skill"), str) else "",
        "reviewer": data.get("reviewer") if isinstance(data.get("reviewer"), str) else "",
        "tier": data.get("tier") if isinstance(data.get("tier"), str) else "",
        "generated_at": data.get("generated_at") if isinstance(data.get("generated_at"), str) else "",
        "prompt_ids": [str(x) for x in (data.get("prompt_ids") or []) if isinstance(x, str)],
        "source": where,
        "results": [
            {
                "prompt_id": str(i.get("prompt_id")),
                "verdict": i.get("verdict"),
                "evidence": i.get("evidence") or "",
                "finding": i.get("finding") or "",
                "suggestion": i.get("suggestion") or "",
                "blocking": bool(by_id[str(i.get("prompt_id"))].blocking)
                if str(i.get("prompt_id")) in by_id else False,
            }
            for i in results if isinstance(i, dict)
        ],
    }
    return out, normalized


def _summarize(items: list[str], limit: int = 5) -> str:
    if not items:
        return ""
    head = "；".join(items[:limit])
    return head + (f"；等共 {len(items)} 处" if len(items) > limit else "")


# --------------------------------------------------------------------------- #
# 汇总
# --------------------------------------------------------------------------- #


def collect(
    paths: list[Path],
    catalog: list[Prompt],
    *,
    skill_dir: Path | None = None,
    expected_ids: list[str] | None = None,
) -> tuple[Report, dict]:
    """校验并汇总若干回写，返回 (报告, 记录)。记录由调用方落盘给交付门禁。"""
    report = Report(target=str(skill_dir) if skill_dir else ", ".join(str(p) for p in paths),
                    stage="review")
    claims: dict[str, list[tuple[str, str]]] = {}      # prompt_id -> [(verdict, source)]
    declared_by_source: list[tuple[str, set[str]]] = []  # 每份回写自述的 prompt_ids
    findings: list[dict] = []
    all_results: list[dict] = []
    blocking_fails: list[dict] = []
    warnings: list[str] = []
    skills: set[str] = set()
    reviewers: set[str] = set()
    tiers: set[str] = set()

    for path in paths:
        data, error = read_json(path)
        if error:
            report.add(_res(RULES["REV-001"], FAIL, f"{path.name}: {error}"))
            continue
        results, normalized = validate_writeback(data, catalog, where=path.name)
        for res in results:
            report.add(res)
        if not normalized:
            continue
        skills.add(normalized["skill"])
        reviewers.add(normalized["reviewer"])
        if normalized.get("tier"):
            tiers.add(str(normalized["tier"]))
        declared_by_source.append((normalized["source"],
                                   {str(x) for x in normalized["prompt_ids"]}))
        for item in normalized["results"]:
            claims.setdefault(item["prompt_id"], []).append((item["verdict"], path.name))
            all_results.append({**item, "source": path.name})
            if item["verdict"] == FAIL:
                record = {"prompt_id": item["prompt_id"], "blocking": item["blocking"],
                          "finding": item["finding"], "evidence": item["evidence"],
                          "source": path.name}
                findings.append(record)
                if item["blocking"]:
                    blocking_fails.append(record)

    conflicts: list[str] = []
    for pid, entries in sorted(claims.items()):
        verdicts = {v for v, _src in entries}
        if len(verdicts - {"NA"}) > 1:
            conflicts.append(f"{pid}: " + "、".join(f"{v}（{src}）" for v, src in entries))

    declared = {str(x) for x in (expected_ids or [])}
    # 回写自己声明的 prompt_ids 也算声明：任务包模板里就带着这一行，
    # 因此即便任务包被 --out 放到别处（manifest 找不到），覆盖判定依然正确。
    for _src, ids in declared_by_source:
        declared |= ids
    covered = set(claims)
    missing = sorted((declared - covered) if declared else
                     ({p.id for p in catalog} - covered))
    report.add(_res(RULES["REV-009"],
                    WARN if missing else PASS,
                    f"未覆盖的提示词 {len(missing)} 条: {', '.join(missing[:8])}"
                    + ("（等）" if len(missing) > 8 else "") if missing
                    else f"覆盖完整（{len(covered)} 条）"))
    report.add(_res(RULES["REV-010"], WARN if conflicts else PASS,
                    _summarize(conflicts) if conflicts else "无冲突结论"))
    need_suggestion = [f["prompt_id"] for f in blocking_fails
                       if not any(x["prompt_id"] == f["prompt_id"] and x.get("suggestion")
                                  for x in all_results)]
    # 这里**不能**记 INFO：INFO 的语义是"不适用"，而"阻断项缺修复建议"是确实存在
    # 的缺口（只是不该阻断交付）→ 记 WARN（需人工判断），与规则标题/整改文案一致。
    report.add(_res(RULES["REV-011"], WARN if need_suggestion else PASS,
                    f"阻断项缺修复建议: {', '.join(need_suggestion)}" if need_suggestion
                    else "阻断项均有修复建议（或无阻断项）"))

    fingerprint = ""
    if skill_dir is not None:
        from .watch import fingerprint as fp

        fingerprint = fp(Path(skill_dir).resolve())

    record = {
        "schema": RECORD_SCHEMA,
        "skill": sorted(skills)[0] if len(skills) == 1 else (str(skill_dir.name) if skill_dir
                                                            else (sorted(skills)[0] if skills else "")),
        "skills": sorted(skills),
        "reviewers": sorted(reviewers),
        # 这批结论出自哪一档执行器（cli / pack / manual）——三档同 schema，来源要留痕
        "tiers": sorted(tiers),
        "fingerprint": fingerprint,
        "collected_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "tool_version": __version__,
        "sources": [str(p) for p in paths],
        "verdict": "fail" if blocking_fails else ("warn" if (findings or conflicts or missing)
                                                 else "pass"),
        "blocking_fails": blocking_fails,
        "findings": findings,
        "conflicts": conflicts,
        "uncovered_prompts": missing,
        "results": all_results,
        "counts": report.counts(),
    }
    return report, record


def write_record(store_dir: Path, record: dict) -> Path:
    """把汇总记录写进中央留痕：`<记录目录>/<技能名>.json` + 追加一行 history。"""
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\w.-]+", "-", record.get("skill") or "unknown") or "unknown"
    latest = store_dir / f"{name}.json"
    write_text(latest, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    line = {
        "collected_at": record["collected_at"],
        "skill": record["skill"],
        "verdict": record["verdict"],
        "reviewers": record["reviewers"],
        "blocking_fails": len(record["blocking_fails"]),
        "uncovered": len(record["uncovered_prompts"]),
        "fingerprint": (record.get("fingerprint") or "")[:12],
    }
    with (store_dir / "history.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return latest


def _record_name(skill_name: str) -> str:
    return re.sub(r"[^\w.-]+", "-", skill_name or "unknown") or "unknown"


def load_record(trace_dir: Path, skill_name: str) -> dict | None:
    path = Path(trace_dir) / "review" / f"{_record_name(skill_name)}.json"
    if not path.is_file():
        return None
    data, error = read_json(path)
    return data if isinstance(data, dict) and not error else None


def check_review(skill_dir: Path, trace_dir: Path, *, skipped: bool = False) -> list[Result]:
    """交付/检查流程里的 REV-000：记录是否存在、是否新鲜、结论是否可用。"""
    from .watch import fingerprint

    if skipped:
        return [Result("REV-000", RULES["REV-000"].title, SKIP, "HOUSE",
                       "未覆盖：调用方显式 --skip-review 跳过语义评审",
                       RULES["REV-000"].remediation, optional=True)]
    skill_dir = Path(skill_dir).resolve()
    record = load_record(Path(trace_dir), skill_dir.name)
    if record is None:
        return [Result("REV-000", RULES["REV-000"].title, SKIP, "HOUSE",
                       "未覆盖：尚无语义评审记录"
                       f"（`skillverify review pack {skill_dir.name}` 生成任务包，"
                       f"评审后 `review collect` 汇总）",
                       RULES["REV-000"].remediation, optional=True)]

    current = fingerprint(skill_dir)
    recorded = record.get("fingerprint") or ""
    if recorded and recorded != current:
        return [Result("REV-000", RULES["REV-000"].title, WARN, "HOUSE",
                       f"评审记录已过期：评审时的技能指纹 {recorded[:12]}… "
                       f"与当前 {current[:12]}… 不一致（技能在评审后改过），须重评",
                       RULES["REV-000"].remediation)]
    blocking = record.get("blocking_fails") or []
    if blocking:
        detail = "；".join(f"{b['prompt_id']}：{(b.get('finding') or '')[:60]}"
                          for b in blocking[:4])
        return [Result("REV-000", RULES["REV-000"].title, FAIL, "HOUSE",
                       f"语义评审有阻断项 FAIL（{len(blocking)} 条）：{detail}",
                       RULES["REV-000"].remediation)]
    uncovered = record.get("uncovered_prompts") or []
    if uncovered:
        return [Result("REV-000", RULES["REV-000"].title, WARN, "HOUSE",
                       f"语义评审覆盖不完整（{len(uncovered)} 条未评）："
                       f"{', '.join(uncovered[:8])}",
                       RULES["REV-000"].remediation)]
    if record.get("verdict") in ("warn",) or record.get("findings"):
        return [Result("REV-000", RULES["REV-000"].title, WARN, "HOUSE",
                       f"语义评审存在非阻断问题 {len(record.get('findings') or [])} 条"
                       f"（reviewer: {', '.join(record.get('reviewers') or []) or '未署'}）",
                       RULES["REV-000"].remediation)]
    return [Result("REV-000", RULES["REV-000"].title, PASS, "HOUSE",
                   f"语义评审通过（{len(record.get('results') or [])} 条结论；"
                   f"reviewer: {', '.join(record.get('reviewers') or []) or '未署'}；"
                   f"指纹 {current[:12]}…）")]


def status(trace_dir: Path, skills: list[tuple[str, Path]]) -> str:
    """打印各技能的评审记录状态（给人看的表）。"""
    lines = [
        "# 语义评审状态",
        "",
        f"- 记录目录: {Path(trace_dir) / 'review'}",
        "",
        "| 技能 | 结论 | 阻断项 | 未覆盖 | 结论数 | 记录新鲜 | reviewer |",
        "|---|---|---|---|---|---|---|",
    ]
    from .watch import fingerprint

    for name, path in skills:
        record = load_record(Path(trace_dir), name)
        if record is None:
            lines.append(f"| {name} | （无记录） | - | - | - | - | - |")
            continue
        fresh = "是"
        if record.get("fingerprint"):
            fresh = "是" if record["fingerprint"] == fingerprint(Path(path).resolve()) else "**否（已改）**"
        lines.append(
            f"| {name} | {record.get('verdict')} | {len(record.get('blocking_fails') or [])} "
            f"| {len(record.get('uncovered_prompts') or [])} "
            f"| {len(record.get('results') or [])} | {fresh} "
            f"| {', '.join(record.get('reviewers') or []) or '未署'} |"
        )
    lines += ["", "> 无记录或已过期都**不算通过**——`deliver` 会把它们记成未覆盖项。", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 独立可选技能（把语义评审做成任何宿主都能加载的技能包）
# --------------------------------------------------------------------------- #


def emit_skill(out_root: Path, catalog: list[Prompt], *, name: str = "skillverify-review"
               ) -> list[Path]:
    """生成"语义评审"技能包：SKILL.md + 参考文件 + 提示词目录资产。"""
    target = Path(out_root) / name
    (target / "references").mkdir(parents=True, exist_ok=True)
    (target / "assets").mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    blocking = [p.id for p in catalog if p.blocking]
    description = (
        "对 Agent Skill 做语义评审（提示词目录：旧体系 29 条 + 本项目新增，"
        "每条带 PASS/FAIL 判据与证据要求）："
        "检查描述触发质量、渐进式披露、取材真实性、破坏性操作防护、断言可验证性等"
        "机械检查覆盖不到的问题。当需要判断一个技能「写得好不好、会不会误导 Agent」时使用；"
        "当技能已通过 skillverify check 但仍需人工或模型复核时使用。"
    )
    skill_md = f"""---
name: {name}
description: {description}
license: 与本仓库一致
metadata:
  author: skillverify
  version: "1"
  prompts: "{len(catalog)}"
---

# 语义评审（{len(catalog)} 条提示词）

机械检查能证明"格式与结构没问题"，证明不了"写得对、好用、不会误导 Agent"。
本技能负责后者：按提示词逐条判断，**每条都要给可定位的证据**。

## 什么时候用

- 技能准备交付，且已经通过 `skillverify check`；
- 改了 description、结构、脚本或断言之后（这些改动最容易让评审结论作废）；
- 怀疑"照着它做会走偏"，但机械检查全绿的时候。

## 怎么用

1. 读 `references/prompts.md`，按家族（D 设计期 / W 编写期 / E 测试期 / R 运行期）选要评的条目；
2. 打开待评技能的 `SKILL.md`、`references/`、`scripts/`、`evals/`；
3. 逐条对照该条的 **PASS 判据 / FAIL 判据**判断；
4. 把结论写进 `references/writeback.md` 说明的 JSON 结构；
5. 用 `skillverify review collect <文件>` 汇总——它会校验证据是否可定位、覆盖是否完整。

## 铁律

- **不许只给结论**：证据必须能按图索骥核到（写清文件与位置，或直接引用原文）；
- **不许复述判据**：把判据换个说法抄一遍不算证据（机械校验会标出来）；
- **FAIL 必须写清哪一处、为什么不行**；判不了就记 NA 并说明缺什么材料；
- 阻断项（{', '.join(blocking) if blocking else '无'}）判 FAIL 时该技能不得交付。

## 参考文件

- `references/prompts.md` —— 全部 {len(catalog)} 条提示词与判据（评审时逐条对照）
- `references/writeback.md` —— 回写 JSON 结构与校验规则
- `assets/review-prompts.json` —— 机器可读的同一份目录（供工具消费）
"""
    path = target / "SKILL.md"
    write_text(path, skill_md)
    written.append(path)

    prompts_md = target / "references" / "prompts.md"
    write_text(prompts_md, render_prompts_md(catalog))
    written.append(prompts_md)

    writeback_md = target / "references" / "writeback.md"
    write_text(writeback_md, _writeback_reference())
    written.append(writeback_md)

    asset = target / "assets" / "review-prompts.json"
    write_text(asset, json.dumps({"version": 1,
                                  "note": "与 references/prompts.md 同源的机器可读目录",
                                  "prompts": [p.to_dict() for p in catalog]},
                                 ensure_ascii=False, indent=2) + "\n")
    written.append(asset)
    return written


def _writeback_reference() -> str:
    return """# 回写结构与校验规则

```json
{
  "schema": "skillverify.review/1",
  "skill": "<被评审的技能名>",
  "reviewer": "<你的人名或模型标识>",
  "tier": "pack",
  "generated_at": "<ISO 8601>",
  "prompt_ids": ["W-01", "W-02"],
  "results": [
    {"prompt_id": "W-01", "verdict": "PASS|FAIL|NA",
     "evidence": "可定位的证据", "finding": "FAIL 必填", "suggestion": "可选"}
  ]
}
```

`skillverify review collect` 会逐条校验：

| 检查 | 判定 |
|---|---|
| schema 不正确 / JSON 坏掉 | FAIL |
| `skill` 或 `reviewer` 为空 | FAIL（无签署的评审等于没有评审） |
| `results` 空、或缺字段 | FAIL |
| `prompt_id` 不在提示词目录里 | FAIL |
| `verdict` 不是 PASS/FAIL/NA | FAIL |
| 证据过短、或没有文件/行号/引用/计数 | FAIL |
| 证据与判据文本高度重合（复述判据） | WARN |
| FAIL 没写 `finding` | FAIL |
| NA 没写理由（在 `evidence` 里） | FAIL |
| 声明的提示词有没有结论的 | WARN（未覆盖） |
| 同一提示词出现两条互相冲突的结论 | WARN（须人工裁决） |

汇总结果落到中央留痕目录（`<项目>/.agents/skillverify/review/`），
`skillverify deliver` 会据此判断：有阻断项 FAIL → 不得交付；记录过期（技能改过）→ 需重评；
无记录 → 记"未覆盖项"（默认不阻断，`--strict` 时阻断）。
"""
