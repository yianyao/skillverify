---
name: evals-skill
description: 为新建或已有的 Agent Skill 生成评测资产——官方格式的 evals.json（输出质量用例与可判定断言）和 trigger-queryset.json（触发查询集，约20条、正负各8到10条、near-miss 负例为主、train 占55%-65%），内置口径硬约束、空洞断言拦截、防自我应验查重与 skillverify 校验闭环；绝不生成 trigger-runs.json（那是执行层的产物，凭空伪造即假证据）。当用户要为某个技能补评测、写 evals、建触发查询集时使用。
license: MIT
---

# evals-skill —— 为目标技能生成评测资产

## 职责边界（先读，不可协商）

1. **只生成两份文件**：`evals/evals.json` 与 `evals/trigger-queryset.json`，落在目标技能目录的 `evals/` 下。
2. **绝不生成 `evals/trigger-runs.json`**。它是执行层（真跑查询的模型、官方 skill-creator、宿主）留下的运行记录。没有运行记录就明确告知用户「尚未跑过，工具的 TRIG-* 会提示」——**任何情况下不得凭空编写运行记录**：伪造的记录能通过全部机械校验（次数、阈值全对），比缺失危险得多。
3. **不自研执行器**：with/without 对比、benchmark、A/B、按结果调优描述，用官方 skill-creator 或宿主；也可以把执行入口交给 `skillverify evals --run-with <命令>`（执行 + 限时 + 跑完重新校验产物）。
4. 目标技能已存在 evals 资产时：先读旧文件，默认**增量补充**并向用户确认，不得静默覆盖。

## 工作流程

### 第 1 步：确定目标并理解技能（本 skill 自含此能力，调用方无需预整合）

- 用户给了**已有技能目录** → 读该目录 `SKILL.md`（frontmatter 的 name/description + 正文），列出 `references/` 与 `scripts/` 清单；
- 用户要为**尚未创建的技能**备料 → 请用户提供：功能描述、目标用户、典型使用场景、期望输出形态；
- 调用方（会话）若能提供**真实用户话术样例**，优先级最高——真实语料是最好的查询来源，胜过任何凭空编造。

第 1 步的产出是一张「能力-场景图」，后续所有生成物都从它派生：

- 这个技能做什么 / 明确不做什么；
- 何时**该**触发；何时**绝不该**触发（边界即负例来源）；
- 正确输出长什么样（断言来源）。

### 第 2 步：生成 evals.json（官方格式）

骨架见 `references/eval-asset-spec.md` 第 1 节；`skill_name` 必须与目标技能的 name 一致。规则：

- `prompt` 像真人说的话；
- `files` 里的文件必须真实存在（写前逐一核对；素材不存在的先创建到 `evals/files/` 或删除引用）；
- `assertions` 必须是**可判定的条件**——"输出列出了 3 个月份" ✔；"输出是好的" ✘（空洞断言会被工具直接判错）；
- 至少 3 个用例：覆盖主干场景 + 至少 1 个易错点。

### 第 3 步：生成 trigger-queryset.json

字段与口径（工具会照此检查，数值不得自行放宽）：

- 约 **20 条**查询（起步可 4–6 条先跑通流程，交付说明里标注"过渡规模"）；
- 正例 8–10 条、负例 8–10 条，**负例以 near-miss 为主**（共享表面词、意图不同）；
- `subset`：train 占 **55%–65%**——train 用来调描述，validation 留作验收，调描述时只准看 train；
- `id` 同文件内唯一；`should_trigger` 严格布尔 `true`/`false`（写成字符串会被判错）；
- `category` 建议写（如 positive-direct / negative-near-miss，工具不校验取值，供人读与统计）；
- `rationale` **必写**——负例的价值全在这句话里（例：「有『算一下』但对象是数学题」）。

### 第 4 步：防自我应验查重（必做）

同一个模型既写描述又写查询集时，查询容易不自觉复用描述词句 → 触发率被测得虚高、评测集失去代表性。跑：

```
python scripts/check_overlap.py <技能目录>
```

对每条 WARN：改写到"用户会怎么说"的口吻，禁止照抄描述。负例允许与领域共享表面词（这正是 near-miss 的本义），但不得整句改写自描述。

### 第 5 步：校验闭环（必做）

环境里有 skillverify 时（pip 已安装，或 PYTHONPATH 指向其仓库）：

```
python -m skillverify evals <技能目录>
python -m skillverify trigger <技能目录>
```

按报错逐条修复并重跑，直到无 FAIL。不可用时做形状自查（JSON 可解析 / 布尔严格小写 / id 唯一 / files 存在 / 口径数值逐项核对），并在交付说明中写明「未过 skillverify」。

## 交付说明（收尾必写）

- 生成了什么、各多少条、是否过渡规模；
- 校验结果（skillverify 结论，或自查声明）；
- 剩下的事只有执行层能做：如何产生 trigger-runs.json（每条查询至少跑 3 次、记录 loaded 与 evidence）、用官方 skill-creator 或 `evals --run-with` 委托执行；
- 评测工作区位置约定：技能目录的**兄弟目录**（`<技能名>-workspace/`），不是子目录。

## 参考

- `references/eval-asset-spec.md`：两份 JSON 的完整字段说明与可抄写的示例。
