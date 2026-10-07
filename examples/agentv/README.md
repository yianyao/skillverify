# 把「执行层」交给 AgentV（样例 + 实操）

> 本目录是**可直接照抄**的样例，不是工具的一部分。它演示本项目的既定立场：
> **执行层不自研**——机械层只校验资产与产物，真要"跑起来评测"就委托外部 runner。
> AgentV（<https://agentv.dev>，`EntityProcess/agentv`）是其中一个合适的 runner，
> 因为它**原生识别官方 `evals.json`**。

## 一、什么时候用、用在哪一步

| 你想知道的 | 用什么 | 说明 |
|---|---|---|
| 评测**资产**写得对不对（字段、夹具、断言、切分） | `skillverify evals <技能>` | 纯机械校验，**不执行任何东西**，离线、零依赖 |
| 技能**实际输出质量**如何 | **AgentV**（或其它 runner） | 这一步要联网、要 provider、要花钱——所以只在你真要证据时做 |
| **会不会被触发**（负例不误触） | `skillverify evals`（资产）+ 你选的 runner 跑 queryset | 我们只管 queryset/运行记录的**形状与新鲜度** |
| 结论能不能交付 | `skillverify deliver` | 汇总机械结论 + 评审记录，出判定与留痕 |

在本项目流程里的位置：

```
skillverify evals <技能>            ← ① 资产合规（我们，离线）
        ↓
AgentV 执行 + 评分                   ← ② 真跑（外部，联网/密钥由你负责）
        ↓
产物落回工作区（<技能名>-workspace/）  ← ③ AgentV 的输出
        ↓
skillverify evals <技能>            ← ④ 复校产物形状与断言时机（WS-* / EVAL-011）
skillverify deliver                 ← ⑤ 门禁与留痕（含评审记录新鲜度）
```

## 二、我们给它什么 / 它给我们什么

| 方向 | 具体是什么 | 备注 |
|---|---|---|
| **我们 → AgentV** | `evals/evals.json`（官方格式；AgentV 的识别条件是**顶层有 `skill_name` 字符串 + `evals` 数组**，缺一个它会当成普通 JSON 拒收） | 这正是 `skillverify evals` 校验的那个文件，两边不打架 |
| | `evals/files/` 里的夹具（AgentV 按 `files[]` 映射成 `input_files`，路径相对 `evals.json`） | 夹具必须随技能分发，否则 runner 拿不到 |
| | 技能目录本身（provider 通过正常运行时加载技能） | 别把技能改造成"专供评测"的样子 |
| | 一次运行的自证：隔离方式 / 执行器 / 输入哈希 → `run-inputs.json`（模板 `examples/run-inputs.json`） | 我们用这份自证判 `WS-008` 双跑与 `EVAL-011` 断言时机 |
| **AgentV → 我们** | 运行结果产物（`--output .agentv/results/<技能名>` 下的结果与逐条评分） | 落回工作区后由我们的 `evals` 复校；**不要**指望我们解析它的私有 schema |
| | provenance：run id / provider / 模型 / AgentV 版本 | 记进交付记录，回答"这条结论是哪次跑出来的" |

**字段映射**（AgentV 官方转换规则，照抄备查）：`prompt→input`、`expected_output→criteria + llm-rubric`、
`assertions[] / expectations[]→llm-rubric criteria`、`files[]→input_files`、`skill_name→tags.skill`、`id→字符串`。

## 三、照抄命令

```bash
# ① 先过我们这关（资产合规；离线，失败就别往下走）
skillverify evals ./my-skill

# ② 直接用 AgentV 跑官方 evals.json（推荐：不引入第二份真源）
#    版本要 pin：页面当前是 4.42.4，别用 latest
npx --yes agentv@4.42.4 eval ./my-skill/evals/evals.json \
  --provider claude \
  --output ./my-skill-workspace/.agentv/results/my-skill

# ②' 或者先转成可编辑的 EVAL.yaml，再加确定性判据（contains / regex / is-json 是免费的）
npx --yes agentv@4.42.4 convert ./my-skill/evals/evals.json --out EVAL.yaml
npx --yes agentv@4.42.4 eval EVAL.yaml --provider claude --output ./my-skill-workspace/.agentv/results/my-skill

# ③ 已有会话记录时，离线评分（不重跑、不花钱）
npx --yes agentv@4.42.4 import claude --session-id <uuid>
npx --yes agentv@4.42.4 eval ./my-skill/evals/evals.json \
  --transcript .agentv/transcripts/claude-<id>.jsonl

# ④ 交给我们复校 + 门禁
skillverify evals ./my-skill
skillverify deliver --stages all
```

**也可以整条委托给我们**（我们只负责"起进程 + 限时 + 跑完校验产物"）：

```bash
skillverify evals ./my-skill \
  --run-with "npx --yes agentv@4.42.4 eval ./my-skill/evals/evals.json --provider claude --output ./my-skill-workspace/.agentv/results/my-skill"
```

## 四、常见失败

| 现象 | 原因 |
|---|---|
| AgentV 说这不是 eval 文件 | `evals.json` 缺顶层 `skill_name`，或 `evals` 不是数组 |
| 跑完我们复校说"产物不全" | `--output` 指到了别处；约定是技能目录的**兄弟目录** `<技能名>-workspace/` 下 |
| provider 报缺密钥 / 超时 | 密钥由你配（CI 里用 secrets）；`--run-timeout` 可调（我们默认 1800s） |
| 结果不可复现 | 用了 `latest`；pin 版本，并把 provider/模型记进交付记录 |
| 想让结论更硬 | 加确定性判据（`contains`/`regex`/`is-json`）——LLM-rubric 只回答"像不像" |

## 五、边界（别越）

- **不进依赖、不进代码**：本项目运行时零第三方依赖；AgentV 只能通过 `--run-with` 的**命令字符串**接入，
  这样换 runner（promptfoo、自研脚本…）不用改我们一行代码。
- **机械层不解析它的私有 schema**：我们只认"结构化自证 + 产物形状 + 断言时机"三样事实；
  把第三方结果格式写成我们的判据，等于把他们的版本升级变成我们的误报。
- **联网与密钥不是我们的责任**：`evals` 不执行、不联网；要不要跑、跑几次、花多少钱，由你决定。
- **触发质量那一半**：AgentV 有 "Execution Quality vs Trigger Quality" 的分野，但它的 queryset 支持形态
  尚未在本项目验证过——**用之前先自己确认一次**，别默认它能吃我们的 `trigger-queryset.json`。
