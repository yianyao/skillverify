# 双评任务包 B（包编号：B）· W-02

**本包编号: B**（留痕时 record_review.py --package B）

**独立判定声明**: 本包由独立会话独立判定，不得参考另一份包的结论；同一会话内跑两遍不构成双评。判定不一致将升级人工裁决。

## 提示词（来自 w-prompts.md）

```text
你是 Agent Skill 触发评审员。以下是一个技能的 name 与 description（宿主加载时只读这两项）：
<name + description>
逐条判定并给证据：
1. 是否同时回答"做什么"和"何时用"，缺一即 FAIL；
2. 是否为第三人称祈使句/意图导向写法，无第一人称"我会/我将"；
3. 覆盖范围是否不窄不宽：具体功能 + 合适的触发关键词，既不漏触发场景也不泛滥；
4. "何时使用"的信息是否全部落在 description 内（用户只能靠它决定是否触发，不得寄望正文）；
5. 是否存在跨行 plain scalar 等写法风险（语义上是否一段连贯描述）。
输出：每条 PASS/FAIL + 证据。FAIL 时给出重写建议。
```

## 待评审材料

### 输入: SKILL.md

```
---
name: agent-skill-llm-review
description: 对 Agent Skill（AI 技能包）执行 LLM 语义评审：按技能生命周期的设计、编写、测试、运行四个阶段选用对应评审提示词，对关键判定组织双评交叉复核，评审过程与结论全程落盘留痕，并汇总需人工最终裁决的事项。当用户要求评审 Agent Skill、跑语义评审（即 W 组/L 类评审）、对评测断言评分、对技能产物做盲评（新旧版本 A/B 对比）、诊断技能执行轨迹、诊断技能过触发或漏触发、裁决技能 description 用词与触发边界、归纳技能评审 Gotchas，或需按《Agent-Skill 生命周期验证方案》执行 LLM 评审时使用。仅面向 Agent Skill 质量验证场景：文章、文案、简历、合同、标书等一般内容评审与盲评不适用；不替代机械检查（check_skill.py）、人工终审与门禁裁决。
compatibility: 需要 Python 3.10+（scripts 仅用标准库）；运行于支持 Agent Skill 的宿主。
---

# Agent Skill LLM 评审执行助手

> 版本：v1.4（2026-10-03；变更历史见同目录 CHANGELOG.md——v1.4 description 可读性自足化，v1.3 触发子句域锚定+负向边界，v1.2 历轮评审修复）

## 1. 定位与边界

- **能做**：阶段产物检测（仅建议）、提示词调度、双评任务包生成、V12 留痕、评审结果汇总与人工裁决点提示。
- **不能做（硬边界，违反即本技能自身评审 FAIL）**：
  1. 不替代 S 类机械检查（`check_skill.py`）、H 类人工终审（内容门 B / M1 审计）、K 类动态实测；
  2. 不在同一会话内完成双评（单会话跑两遍无效，见 §5）；
  3. 不自动放行任何 [M] 级失败（安全门 E4、V8、V13 仍须人工/隔日复审）；
  4. 阶段判定只是建议，不得作为"阶段已完成"的依据；
  5. 不写回/修改被评审技能的任何文件（description 写回归主流程并受 V28 约束）。

## 2. 工作流

1. 确定目标技能目录（应含 `.verification/` 留痕目录）。
2. 运行 `python scripts/detect_stage.py <skill_dir>` 获取阶段产物状态与应跑提示词组**建议**。
3. 按下表读取对应 references 文件，逐条投喂执行，PASS/FAIL 必须附证据引用。
4. ⚑ 提示词先运行 `python scripts/plan_dual_review.py` 生成双评任务包（规则见 §5 与 references/dual-review-rules.md）。
5. 每条评审完成**立即**运行 `python scripts/record_review.py` 留痕（勿攒批；双评记录分别带 `--package A` / `--package B`）。
6. 收尾运行 `python scripts/summarize_reviews.py` 汇总，向用户输出"人工裁决点"清单。

## 3. 阶段 → 提示词映射（权威口径，与清单 v1.2 一致）

| 阶段 | 必跑 | 双评 ⚑ |
| --- | --- | --- |
| D 设计期 | D-01（**可选辅助**：仅提炼材料；V1/V2 由人工设计评审与脚本预检完成，不属 L 类） | — |
| W 编写期 | W-01~W-16（全跑） | W-02、W-04、W-05、W-08、W-15 |
| E 测试期 | E-01~E-10（按实际测试项） | E-04、E-06 |
| R 运行期 | R-01、R-02 | R-02 |

## 4. 提示词加载时机

- 当需要提炼设计期取材材料时，读取 references/d-prompts.md（D-01）。
- 当进入编写期语义评审时，读取 references/w-prompts.md（W-01~W-16），按目标条目选用。
- 当测试期需要查询集评审、断言评分、盲评、模式归因或轨迹诊断时，读取 references/e-prompts.md（E-01~E-10）。
- 当运行期做纠错归纳或增长性内容隔离判定时，读取 references/r-prompts.md（R-01/R-02）。
- 当组织双评或盲评时，读取 references/dual-review-rules.md。

Read references/d-prompts.md when distilling design-stage source material. Read references/w-prompts.md when running writing-phase semantic review. Read references/e-prompts.md when scoring assertions, blind-reviewing, or diagnosing trajectories. Read references/r-prompts.md when consolidating corrections or judging growth content isolation. Read references/dual-review-rules.md when organizing dual review or blind evaluation.

## 5. 双评硬性规则（V12）

1. ⚑ 八项**必须双评**：W-02、W-04、W-05、W-08、W-15、E-04、E-06、R-02。
2. 双评 = **两个独立会话或两个不同模型**分别判定；本技能所在会话至多承担其中一份。
3. 同一会话内跑两遍**不构成双评**，留痕时不得标"双评=是"。
4. 任务包由 `plan_dual_review.py` 生成后，由**人工**分别开两个会话投喂；结果分别留痕。
5. 双评分歧 → 升级人工裁决并记录理由；不得自动取其一，不得只留胜出方。

## 6. 留痕（V12）

每条评审一行，字段：日期 | 提示词编号 | 模型名+版本 | 输出证据（结论摘要/引用） | 判定 | 是否双评。模板见 assets/llm-review-log-template.md；`record_review.py` 缺日志文件时自动按模板初始化。

## 7. Scripts 用法

```
python scripts/detect_stage.py <skill_dir>            # 阶段产物检测 + 提示词建议（advisory；退出 0=检测完成，1=用法错误/目录不存在，供编排器区分误用）
python scripts/record_review.py --skill-dir <dir> --prompt-id W-02 \
    --model "glm-4.7" --verdict FAIL --evidence "引用摘要" --dual 是 --package A
python scripts/plan_dual_review.py --skill-dir <dir> --prompt-id W-15 \
    --inputs SKILL.md scripts/foo.py                   # 生成 .verification/dual-review/<id>-<ts>/{A,B}-task.md
python scripts/plan_dual_review.py --skill-dir <dir> --prompt-id E-06 \
    --blind out_new.md out_old.md                      # 盲评：随机匿名化两份输出
python scripts/summarize_reviews.py <skill_dir>       # 汇总判定、双评缺口、分歧项
```

## 8. Gotchas

- **detect_stage 的建议 ≠ 阶段完成**：产物存在只说明"到过该阶段"，出口判据 + 人工签认才算完成。勿据脚本建议跳过人工终审或门禁。
- **双评分歧高发于 W-02**（触发质量主观性强）：把两个会话的原始输出都贴进留痕证据列，人工裁决必须写明采纳哪份及理由。
- **盲评映射文件**（plan_dual_review 生成的 mapping.json）只在汇总还原时打开，投喂评委前勿让其接触。
- **数据安全**：评审对象全文与脚本先过 `check_skill.py` 的 secret 扫描（V8）再投喂外部 LLM；命中敏感信息即停止投喂并上报。
- **本技能自身的修改**也须走 D/W/E/M/R 验证：description 改动过 W-02 双评、结构改动过 W-04 双评、全文改动过 W-15 双评。

```
