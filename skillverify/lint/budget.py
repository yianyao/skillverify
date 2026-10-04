"""lint.budget —— 上下文预算检查（官方 progressive disclosure）。

官方条款（https://agentskills.io/specification#progressive-disclosure）：
- "Instructions (< 5000 tokens recommended)"：SKILL.md 正文建议 <5000 token。
- "Keep your main SKILL.md under 500 lines."
- "Keep individual reference files focused. Agents load these on demand, so smaller
  files mean less use of context."

强度分级说明（不得混淆）：
- 官方**不执法**这两条（官方校验器只查 frontmatter），故 500 行/5000 token 记 SHOULD。
- 本项目的硬线是**我们自己的纪律**，记 HOUSE——否则就是把项目收紧伪装成官方要求。
"""

from __future__ import annotations

from ..report import FAIL, INFO, PASS, WARN, Rule
from .shared import (
    LintContext,
    cjk_ratio,
    count_lines,
    estimate_tokens,
    res,
    summarize,
)

_SPEC = "https://agentskills.io/specification#progressive-disclosure"

#: 官方建议线
OFFICIAL_LINES = 500
OFFICIAL_TOKENS = 5000

#: 项目硬线（HOUSE）：超过即阻断，理由是"再长就该拆"
HOUSE_LINES = 800

#: 引用类文件（references/ + assets/ 文本）的项目告警线（HOUSE）
REFERENCE_LINES = 500

#: CJK 占比超过该值时，token 估算须附"低估"提示
CJK_CAVEAT_RATIO = 0.3

RULES: dict[str, Rule] = {
    "BUDGET-001": Rule(
        "BUDGET-001",
        f"SKILL.md 总行数 ≤{OFFICIAL_LINES}（官方建议）",
        "SHOULD",
        _SPEC,
        f"把细节外移到 references/ 或 assets/，正文留核心步骤（目标 <{OFFICIAL_LINES} 行）",
    ),
    "BUDGET-002": Rule(
        "BUDGET-002",
        f"SKILL.md 正文 token 估算 ≤{OFFICIAL_TOKENS}（官方建议）",
        "SHOULD",
        _SPEC,
        "精简正文；估算口径为 ceil(字符数/4)，仅作量级参考",
    ),
    "BUDGET-003": Rule(
        "BUDGET-003",
        f"SKILL.md 总行数 ≤{HOUSE_LINES}（本项目硬线）",
        "HOUSE",
        "本项目收紧（官方无此硬线）",
        "拆分：把成段内容移入 references/，并在 SKILL.md 写明何时加载哪个文件",
    ),
    "BUDGET-004": Rule(
        "BUDGET-004",
        f"references//assets/ 单个文本文件 ≤{REFERENCE_LINES} 行（本项目）",
        "HOUSE",
        "本项目收紧（官方只说“保持聚焦”，未给数字）",
        "按主题拆分引用文件；引用文件是按需加载的，拆分不会增加常态上下文成本",
    ),
}


def check(ctx: LintContext) -> list[Result]:
    out: list[Result] = []
    total_lines = count_lines(ctx.text)
    body = ctx.body or ""
    body_lines = count_lines(body)
    tokens = estimate_tokens(body)
    ratio = cjk_ratio(body)
    caveat = (
        f"（正文 CJK 占比 {ratio:.0%}，ceil(字符/4) 会**低估**真实 token，"
        "本项仅作量级参考）"
        if ratio > CJK_CAVEAT_RATIO
        else "（估算口径 ceil(字符数/4)，英文散文近似、CJK 偏低）"
    )
    detail = (
        f"总行数 {total_lines}（正文 {body_lines} 行）；"
        f"正文约 {tokens} token（{len(body)} 字符）"
    )

    if total_lines > OFFICIAL_LINES:
        out.append(res(RULES["BUDGET-001"], WARN, f"{detail}；超官方建议线 {OFFICIAL_LINES} 行"))
    else:
        out.append(res(RULES["BUDGET-001"], PASS, f"{detail}；在官方建议线 {OFFICIAL_LINES} 行内"))
    if tokens > OFFICIAL_TOKENS:
        out.append(res(RULES["BUDGET-002"], WARN, f"{detail}{caveat}；超官方建议线 {OFFICIAL_TOKENS}"))
    else:
        out.append(res(RULES["BUDGET-002"], PASS, f"{detail}{caveat}；在官方建议线内"))
    if total_lines > HOUSE_LINES:
        out.append(res(RULES["BUDGET-003"], FAIL, f"{detail}；超项目硬线 {HOUSE_LINES} 行"))
    else:
        # 未触发时把估算依据留在证据里，便于人工判断"离上限还有多远"
        out.append(res(RULES["BUDGET-003"], PASS, f"{detail}{caveat}"))

    # ---- BUDGET-004：引用类文件体量（无引用文件则记 INFO"不适用"）----
    long_files: list[str] = []
    candidates = 0
    for rec in ctx.inventory.texts:
        if not (rec.under("references", "assets") or rec.under("templates", "evals")):
            continue
        candidates += 1
        n = count_lines(rec.text or "")
        if n > REFERENCE_LINES:
            long_files.append(f"{rec.rp}: {n} 行")
    if not candidates:
        out.append(res(RULES["BUDGET-004"], INFO, "不适用：包内无 references//assets/ 文本文件"))
    elif long_files:
        out.append(res(RULES["BUDGET-004"], WARN, summarize(long_files)))
    else:
        out.append(res(RULES["BUDGET-004"], PASS, f"{candidates} 个引用类文件均 ≤{REFERENCE_LINES} 行"))

    return out
