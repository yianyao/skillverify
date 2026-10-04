---
name: agent-skill-quality-ab
description: 双跑对照 K 编排技能（门 D）——同一任务在"加载目标技能 vs 不加载"两臂各派全新子代理执行，按断言清单评分算质量 delta，验证技能是否真带来产出收益。当需要：验收一个技能的真实增益、判断"加载它到底比裸 LLM 强多少"、做 with/without 对照实测、为技能验收提供 delta 证据——使用本技能。触发词：双跑对照、门 D、with/without、A/B 实测、质量增益、delta 验收。边界：测"会不会触发"→用 agent-skill-trigger-eval；盲评报告文本→直接用 agent-skill-llm-review 的 plan_dual_review.py --blind（本技能不重复实现，断言评分复用其 E-04 双评）；本技能只管对照编排与 delta 计算。
compatibility: 需要 Python 3.10+（scripts 仅用标准库）；设计于 WorkBuddy 宿主（子代理=独立会话）；其他宿主须确认"每臂全新子代理 + 可禁用 Skill 工具"两条能力后使用
---

# 双跑对照编排（agent-skill-quality-ab）

> 版本：v1.2（2026-10-02；v1.1 断言 text 集合校验+重排、delta_conclusion 人工回填声明、退出码语义声明；v1.2 text 唯一性校验、子对象类型校验。变更详情见 scripts/grade_ab.py docstring 与 .verification/fix-log.md）

## 一、定位与三条铁律

本技能是 **K 编排层**：编排"设计同题任务 → 双臂干净上下文执行 → 断言评分 → delta 判定"的纪律。

1. **两臂必须同题、异臂必须干净**。同一任务 prompt、同一靶子；每臂各派**全新子代理**（独立上下文，禁 resume），Arm-A 加载目标技能、Arm-B **禁止调用 Skill 工具**。任何一臂沾了另一臂的上下文，整轮作废。
2. **质量判定不自己发明**。断言评分走 E-04 ⚑ 双评（复用 agent-skill-llm-review 的双评流程，两评委独立打分、分歧升级人工）；本技能只做对照编排与 delta 机械计算（脚本 `scripts/grade_ab.py`）。
3. **断言清单决定一切**。断言要可判定（读报告文本即可判 true/false）、每条附证据要求；故意混入 1–2 条"清单外真实缺陷探测项"，检验两臂的独立发现能力而非照本宣科。

## 二、输入与产物

| 项 | 说明 |
|---|---|
| 输入① | 目标技能（被验收对象，记录版本与 SKILL.md sha256） |
| 输入② | 靶子任务（对植入缺陷的 demo 技能做评审 / 任意可比的同题任务） |
| 输入③ | 断言清单（建议 10 条：核心价值项为主 + 1–2 条清单外探测项） |
| 产物 | `<目标技能>/.verification/gate-d/`：`target-*/`（靶子）、`outputs/with-skill-report.md`、`outputs/without-skill-report.md`、`assertions.txt`、`grading.json`、`delta-report.md`（脚本产出）、`run-inputs.md`（§7.2.4 运行输入记录） |

## 三、执行流程（五步）

### 步骤 1：设计任务与断言

- 靶子任务两臂完全相同（同 prompt、同输入路径）；若靶子是"植入缺陷的 demo"，记录植入清单但**不告诉子代理**；
- 断言每条写成可判定的行为描述（如"识别明文密钥并给最高级处置"），禁写"报告质量好"这类不可判定表述；**每条断言 text 须唯一**（脚本按 text 逐条配对两臂，重复会报错退出）；
- 运行输入记录落 `run-inputs.md`（§7.2.4：技能路径、prompt、隔离方式、产出位置）。

### 步骤 2：双臂执行

- **Arm-A（with_skill）**：全新子代理，prompt 要求加载目标技能并按其工作流执行任务；
- **Arm-B（without_skill）**：全新子代理，同 prompt + **明确禁止调用 Skill 工具**；
- 两臂产出分别落 `outputs/`，互不引用对方内容。

### 步骤 3：断言评分（E-04 ⚑ 双评）

- 用断言清单分别核对两臂报告，每条记 `passed` + `evidence`（引用报告原文）；
- **两评委独立评，零分歧才采信**；有分歧的条目升级人工裁决（与盲评 prefer 分歧同一处理方式）；
- 复用 agent-skill-llm-review 的双评组织与留痕格式，不在本技能内另造。

### 步骤 4：填 grading.json 并算 delta

```json
{"gate": "D", "date": "...",
 "with_skill":    {"report": "outputs/with-skill-report.md",    "assertions": [{"text": "...", "passed": true, "evidence": "..."}]},
 "without_skill": {"report": "outputs/without-skill-report.md", "assertions": [...]}}
```

```bash
python scripts/grade_ab.py --grading grading.json --out delta-report.md \
  [--cost-a outputs/with-skill-report.md --cost-b outputs/without-skill-report.md]
```

- 脚本自行从断言数组统计通过率（**不信任手填 summary**），输出逐条 A/B 对比、delta、单方优势项；脚本会校验两臂断言 **text 一一对应**（顺序无关，集合不同直接报错退出）；
- `--cost-*` 估算两臂 token 成本（≈字符数 ÷ 4，粗估口径，标注估算）；
- **判定口径**：`delta > 0` → PASS 候选；`delta == 0` → 交人工裁决（附单方优势项分析）；`delta < 0` → FAIL（技能无收益证据）。**脚本结论一律视为候选，最终判定人工签认**。退出码 0/1/2 仅供人工快速判读（0=候选 PASS、1=delta<0 或输入错误、2=平局），编排器不得仅凭退出码作验收阻断。

### 步骤 5：结论与留痕

- **人工**将 delta 结论写入 `grading.json` 的 `delta_conclusion`（引用单方优势项，不模板化）；此字段由人工回填，**脚本不读不写**该字段；
- 过程中的可沉淀发现（如"框架术语降低可读性"）记 `gotchas-candidates.md` 候选池，走 R-02 增长性判定后再决定是否入规范。

## 四、防污染与局限

- 子代理执行任务时可能真实写文件：两臂运行前对工作区关键留痕做快照 + sha256，轮后比对；
- **局限**：①单任务代表性有限，delta 是必要非充分证据；②断言清单偏袒会直接伪造结论，清单须在执行前冻结；③成本估算为字符÷4 粗估，不作精确核算；
- 会话结束前提醒用户同步归档盘。
