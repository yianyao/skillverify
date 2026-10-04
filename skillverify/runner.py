"""runner —— 语义评审的**档 1 执行器**：把提示词喂给任意命令，收回同一 schema 的回写。

三档执行器（M0 约定）都要产出同一份 `skillverify.review/1`，本模块负责档 1：

- **档 1 · CLI 自动**（本模块）：`review run --runner "<命令>"`，逐条把提示词送上 stdin，
  从 stdout 取回结论，组装成与档 2/档 3 **完全相同**的回写，再走同一条 `review collect`。
- 档 2 · 会话任务包：`review pack` → 人或 LLM 填写。
- 档 3 · 人工兜底：手写同一 JSON。

**为什么不内置 LLM 客户端**：一旦内置，就得维护各家的 API、密钥与重试，
而"用哪个模型、怎么提示"是使用者的事。这里只做机械部分：喂进去、收回来、校验、汇总。

**判定纪律**：
- runner 失败（非零退出、超时、输出无法解析）**不写成 NA**——那会把"工具坏了"伪装成
  "本项不适用"。失败条目直接不产出，并以非零退出码大声报出来（`--allow-partial` 可放行）。
- runner 的命令行会写进回写的 `reviewer` 字段：**评审必须有签署**，签的就是实际跑的命令。
- 命令由使用者提供、以你的权限执行（与 `lint --scripts` 同类，均需显式开启）。
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .report import FAIL, PASS, WARN, Report, Result, Rule
from .review import (
    RECORD_SCHEMA,
    WRITEBACK_SCHEMA,
    Prompt,
    load_catalog,
    select_prompts,
    validate_writeback,
)

RULES: dict[str, Rule] = {
    "RUN-001": Rule(
        "RUN-001",
        "档 1 执行器：每条提示词都由 runner 产出可解析的结论",
        "HOUSE",
        "本项目流程约定：三档执行器产出同一 schema，档 1 由命令自动跑",
        "检查 runner 命令本身（能否读到 stdin、是否把结论打到 stdout）；"
        "或改用档 2 任务包人工填写",
    ),
}

#: 默认单条超时（秒）——留足冷启动与长推理，但不至于让整批悬挂
DEFAULT_TIMEOUT_S = 180.0

#: 要求 runner 输出的单条结论字段
ENTRY_FIELDS = ("prompt_id", "verdict", "evidence", "finding", "suggestion")

_INSTRUCTION = """你是技能评审者。请**只**输出一个 JSON 对象（不要解释、不要围栏）：

{{"prompt_id": "{pid}", "verdict": "PASS|FAIL|NA|WARN", "evidence": "可定位的证据（文件:行 / 原文片段 / 具体计数）", "finding": "判 FAIL 时写清问题，否则空串", "suggestion": "可选建议"}}

硬性要求：
- 必须看技能目录里的真实文件再下结论；推测、复述判据、空话一律无效；
- `evidence` 必须能被人复核（指出文件名与行号，或引用原文片段）；
- 判 FAIL 必须写 `finding`；判 NA 必须说明缺什么材料。

===== 提示词 {pid}：{title} =====
适用条件：{when}
所需材料：{inputs}
判据（PASS）：{pass_criteria}
判据（FAIL）：{fail_criteria}
证据要求：{evidence_required}
"""


@dataclass
class RunnerOutcome:
    """档 1 单次执行的结果。"""

    entries: list[dict] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    produced: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def _extract_json(text: str) -> dict | None:
    """从 runner 输出里取一个 JSON 对象。

    现实里的 LLM CLI 常在结论外带点寒暄或围栏，所以依次尝试：
    围栏内 → 整段 → 首个 `{` 到末个 `}`。取不到返回 None（绝不猜）。
    """
    candidates: list[str] = []
    fenced = re.findall(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    candidates.extend(block.strip() for block in fenced)
    candidates.append(text.strip())
    first, last = text.find("{"), text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first:last + 1])
    for candidate in candidates:
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _render_instruction(prompt: Prompt) -> str:
    return _INSTRUCTION.format(
        pid=prompt.id,
        title=prompt.title,
        when=prompt.when,
        inputs="、".join(prompt.inputs) or "（技能目录本身）",
        pass_criteria="\n".join(f"- {c}" for c in prompt.pass_criteria),
        fail_criteria="\n".join(f"- {c}" for c in prompt.fail_criteria),
        evidence_required=prompt.evidence_required,
    )


def run_runner(
    skill_dir: Path,
    runner: str,
    *,
    prompt_ids: list[str] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    allow_partial: bool = False,
    extra_context: str = "",
) -> tuple[Report, dict]:
    """逐条把提示词喂给 runner，返回 (报告, 回写字典)。

    回写字典与档 2/档 3 完全同构，可直接交给 `review collect`。
    """
    skill_dir = Path(skill_dir).resolve()
    catalog = load_catalog()
    prompts = (select_prompts(catalog, ",".join(prompt_ids)) if prompt_ids
               else list(catalog))
    report = Report(target=str(skill_dir), stage="review-run")
    outcome = RunnerOutcome()

    for prompt in prompts:
        payload = _render_instruction(prompt)
        if extra_context:
            payload += f"\n===== 附加上下文 =====\n{extra_context}\n"
        payload += f"\n===== 技能目录 =====\n{skill_dir}\n"
        try:
            proc = subprocess.run(runner, shell=True, input=payload, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=timeout_s, cwd=str(skill_dir))
        except subprocess.TimeoutExpired:
            outcome.failures.append(f"{prompt.id}: runner 超时（>{timeout_s:g}s）")
            outcome.failed.append(prompt.id)
            continue
        except OSError as exc:
            outcome.failures.append(f"{prompt.id}: 无法执行 runner（{exc}）")
            outcome.failed.append(prompt.id)
            continue

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            outcome.failures.append(
                f"{prompt.id}: runner 退出码 {proc.returncode}"
                + (f"（{detail[-1][:160]}）" if detail else ""))
            outcome.failed.append(prompt.id)
            continue

        data = _extract_json(proc.stdout or "")
        if data is None:
            outcome.failures.append(f"{prompt.id}: runner 输出里找不到 JSON 对象")
            outcome.failed.append(prompt.id)
            continue

        entry = {key: data.get(key, "") for key in ENTRY_FIELDS}
        entry["prompt_id"] = prompt.id  # 以我们的 id 为准，不让 runner 改归属
        for key in ("verdict", "evidence", "finding", "suggestion"):
            entry[key] = str(entry.get(key) or "").strip()
        entry["verdict"] = entry["verdict"].upper() or "NA"
        outcome.entries.append(entry)
        outcome.produced.append(prompt.id)

    if outcome.failed:
        report.add(Result(rid=RULES["RUN-001"].rid, title=RULES["RUN-001"].title,
                          status=WARN if allow_partial else FAIL,
                          level=RULES["RUN-001"].level,
                          evidence=f"{len(outcome.produced)}/{len(prompts)} 条产出；"
                                   f"失败 {len(outcome.failed)} 条："
                                   + "；".join(outcome.failures[:5]),
                          remediation=RULES["RUN-001"].remediation))
    else:
        report.add(Result(rid=RULES["RUN-001"].rid, title=RULES["RUN-001"].title,
                          status=PASS, level=RULES["RUN-001"].level,
                          evidence=f"{len(outcome.entries)}/{len(prompts)} 条由 runner 产出"))

    writeback = {
        "schema": WRITEBACK_SCHEMA,
        "skill": skill_dir.name,
        "reviewer": f"档 1 CLI：{runner}",
        "tier": "cli",
        "generated_at": __import__("datetime").datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "prompt_ids": outcome.produced,
        "results": outcome.entries,
        "tool": f"skillverify {__version__}",
    }
    report.meta["runner"] = runner
    report.meta["产出条数"] = f"{len(outcome.entries)}/{len(prompts)}"
    report.meta["回写 schema"] = WRITEBACK_SCHEMA
    report.meta["记录 schema"] = RECORD_SCHEMA
    return report, writeback


def validate(writeback: object, catalog: list[Prompt] | None = None) -> list[Result]:
    """复用档 2/档 3 的**同一条**校验（三档共用，档 1 不走捷径）。"""
    results, _record = validate_writeback(writeback, catalog or load_catalog(),
                                          where="runner 回写")
    return results
