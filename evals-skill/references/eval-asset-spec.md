# 评测资产规格：evals.json 与 trigger-queryset.json

本文件是 `evals-skill` 的字段级规格参考。两份文件都由**人/模型**编写，`skillverify evals`
`skillverify evals` 只读它们并校验形状与口径（触发资产 `TRIG-*` 也在 `evals` 里）；工具从不生成这两份 JSON。

## 1. evals/evals.json（输出质量评测，官方格式）

```json
{
  "skill_name": "csv-report",
  "evals": [
    {
      "id": 1,
      "prompt": "我有一份月度销售 CSV 在 evals/files/input.csv，帮我找出收入最高的 3 个月。",
      "expected_output": "一份列出前 3 个高收入月份的汇总。",
      "files": ["evals/files/input.csv"],
      "assertions": ["输出列出了 3 个月份", "每个月后面跟着收入数值"]
    }
  ]
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `skill_name` | 是 | 必须与目标技能 frontmatter 的 `name` 一致 |
| `evals[].id` | 是 | 用例编号 |
| `evals[].prompt` | 是 | 像真人说的话；不得照抄技能 description |
| `evals[].expected_output` | 是 | 期望输出的形态描述 |
| `evals[].files` | 否 | 用例输入素材路径（相对技能目录），必须真实存在 |
| `evals[].assertions` | 是 | **可判定**的条件列表；"输出是好的"这类空洞断言会被工具判错 |

质量要求：

- 至少 3 个用例；覆盖主干场景 + 至少 1 个易错点；
- `files` 引用的素材放进 `evals/files/`；写文件前逐一核对存在性；
- 断言要能被第三方照着判对错，不含"尽量""合理"这类不可判定词。

## 2. evals/trigger-queryset.json（触发评测查询集）

```json
{
  "skill_name": "csv-report",
  "queries": [
    {
      "id": "P01",
      "query": "帮我算一下这份销售数据的月度趋势",
      "should_trigger": true,
      "subset": "train",
      "category": "positive-direct",
      "rationale": "直接命中技能场景"
    },
    {
      "id": "N01",
      "query": "帮我算一下这道积分题",
      "should_trigger": false,
      "subset": "train",
      "category": "negative-near-miss",
      "rationale": "有『算一下』但对象是数学题"
    }
  ]
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 查询编号，同文件内不许重复 |
| `query` | 是 | 一句像真人说的话（用户会怎么问） |
| `should_trigger` | 是 | 严格布尔 `true`/`false`；写成字符串会被判错 |
| `subset` | 是 | 只能是 `train` 或 `validation`；train 约 60%（**按条数**判，容差 ±1 条） |
| `category` | 建议 | 场景分类（positive-direct / negative-near-miss 等）；工具不校验取值 |
| `rationale` | 建议 | 一句话说明「为什么该/不该触发」；负例的价值所在 |

口径（工具照此检查，不得自行放宽）：

- 约 **20 条**查询；
- 正例 8–10 条、负例 8–10 条；
- 负例以 **near-miss** 为主（共享表面词、意图不同）；
- `train` 占 **约 60%**——**按条数判**：train 条数与「60% × 总数」的期望值相差 ≤1 条即合格
  （比例容差在小样本上会误报：12 条里差一条就是 ~8%–14%）；train 用来调描述，validation 留作验收；
- 切分要**分层**：两个子集里正负例都要有，各自条数与「全集正负比 × 子集条数」相差 ≤1 条。
  把正例全堆进 `train`（validation 只剩负例）时，验收那一侧测不出漏触发；
- `should_trigger` 与运行记录中的 `loaded` 必须是严格布尔。

起步阶段可先写 4–6 条跑通流程，但必须在交付说明中标注「过渡规模」，之后按提示补齐。

## 3. trigger-runs.json（本 skill 不生成——执行层产物）

运行记录由真实执行产生：每条查询至少跑 3 次，记录 `loaded`（是否被触发）与
`evidence`（凭什么这么判断）。没有它，工具的 TRIG-* 会提示「还没跑过」，而不是替你猜。

产生方式（任选其一）：

- 官方 skill-creator 的 eval/benchmark 模式；
- 宿主的触发评测能力；
- `skillverify evals --run-with <命令>`：委托执行 + 限时 + 跑完重新校验产物。

**任何情况下不得让模型凭空编写运行记录**：伪造的记录能通过全部机械校验
（次数、阈值全对），比缺失危险得多——缺失时工具会如实说"没跑过"，
伪造时整个评测结论都是假的。

## 4. 评测工作区

评测工作区是技能目录的**兄弟目录**（`<技能名>-workspace/`），不是它的子目录。
grading.json / timing.json / benchmark.json 等执行产物落在工作区，由工具校验。
