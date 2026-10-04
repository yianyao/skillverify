# specSkill — Agent-Skill 生命周期验证产物仓库（说明文档）

> **[归档冻结说明](归档冻结说明.md)（新系统新增，非旧体系内容）**：本目录是**旧体系的归档**，
> 现行不维护：不修、不迁、不跟进；仅作对照与回归语料（`tests.run_all --dogfood`）。
> 新系统的用法见仓库根目录《技能编写指南.md》与《验证流程指南.md》。

> **新读者入口**：推荐先读 [验证操作总说明书.md](验证操作总说明书.md)（面向新手的全流程操作说明，中文为主）。本仓库使用一套内部代号（设计/编写/测试/运行四阶段、各检查项编号等），含义见 [GLOSSARY.md](GLOSSARY.md) 术语总表。
> 操作方法见 [OPERATIONS.md](OPERATIONS.md)；脚本级说明见 [tools/README.md](tools/README.md)。
> 权威依据：`D:\sData\standardSkill\`（规范条目总表 / 生命周期验证方案 / 操作手册 / SOP 等 8 份文档）。

## 一、本仓库是什么

本仓库沉淀"**Agent-Skill 生命周期验证**"体系在 WorkBuddy 宿主上的全部落地产物：1 个 LLM 语义评审技能（手段代号 L）+ 3 个实测编排技能（手段代号 K，含新建的验证编排套件）+ 1 套脚本工具链（手段代号 S）。三层分立架构（详见跨会话续接档案 §一）：

| 层 | 职责 | 形态 | 本仓库对应 |
|---|---|---|---|
| **脚本工具链（S 类）** | 子进程 + 断言可判定的确定性计算 | 本地 Python 裸脚本（标准库，3.10+） | `tools/` |
| **实测编排（K 类）** | 须干净上下文/多会话纪律的编排 | 技能（SKILL.md + references + scripts + evals） | `agent-skill-trigger-eval/`（触发评测）、`agent-skill-quality-ab/`（双跑对照）、`agent-skill-validation-suite/`（生命周期验证一键编排） |
| **LLM 语义评审（L 类）** | Agent-Skill 的语义评审、双评、盲评 | 技能 | `agent-skill-llm-review/` |

## 二、目录清单

```
specSkill/
├── README.md / OPERATIONS.md / GLOSSARY.md  ← 本文档、仓库级操作手册、代号术语总表
├── 验证操作总说明书.md                      ← 面向新手的全流程验证操作说明（总入口）
├── agent-skill-llm-review/            ← LLM 语义评审技能（v1.4，验收 PASS + 触发门 36/36 已签认放行）
│   ├── SKILL.md / CHANGELOG.md        ← 主文件 + 版本历史（v1.1–v1.4）
│   ├── references/ scripts/ evals/
│   └── .verification/                 ← 全部验证留痕（触发实测、双评、挂载、验收报告、
│                                         WARN 评估、修订记录、runs.md 等）
├── agent-skill-trigger-eval/          ← 实测编排：触发评测（触发门 C）（v1.1，验收 10 门全 PASS）
│   ├── SKILL.md
│   ├── references/queryset-spec.md    ← 查询集构造规范泛化 + 自检清单
│   ├── references/sample-queryset.json ← llm-review 实测冻结集副本（sha256 752f7c38，字节级留证不可改）
│   ├── scripts/calc_trigger_rate.py   ← 触发率计算与过门判定
│   ├── tests/test_calc_trigger_rate.py ← 固化回归 9 组断言
│   ├── evals/evals.json               ← 自身触发评测查询集草案（8 条，未冻结）
│   └── .verification/（acceptance-report.md、iteration-1 基线等）
├── agent-skill-quality-ab/            ← 实测编排：双跑对照（质量门 D）（v1.2，验收 9P+1W）
│   ├── SKILL.md
│   ├── scripts/grade_ab.py            ← delta 计算（断言重算、不信手填 summary）
│   ├── tests/test_grade_ab.py         ← 固化回归 14 组断言
│   ├── evals/evals.json               ← 自身评测查询集草案（8 条，未冻结）
│   └── .verification/（acceptance-report.md、warn-assessment.md、iteration-1 基线等）
├── agent-skill-validation-suite/      ← 实测编排：生命周期验证一键套件（v1.0，新建）
│   ├── SKILL.md                       ← 按设计/编写/测试/交付四阶段自动调用工具链
│   ├── scripts/validate_suite.py      ← 分阶段调度器（含官方校验 agentskills validate）
│   └── references/lifecycle-map.md    ← 生命周期阶段 × 工具映射表
├── tools/                             ← 脚本工具链（裸脚本，豁免设计期/编写期条款管辖；12+2 工具 + 1 门禁）
│   ├── check_skill.py v1.1.4          ← 格式门 A 权威校验器（静态格式检查 A1–A11 + X1/X2）
│   ├── w_static_lint.py v1.1          ← 编写期静态补检器（检查项 L-1~L-18，验证补全工程甲档工具一）
│   ├── security_scan.py v1.0.3        ← 安全扫描器（检查项 V8，六项：密钥/端点/交互/危险操作等）
│   ├── naming_precheck.py v1.0.3      ← 命名冲突预检器（检查项 V2：同名/相似度）
│   ├── token_budget.py v1.0.1         ← 上下文预算门（检查项 V11 口径 + V17 阻断）
│   ├── host_compat.py v1.0            ← 跨宿主兼容性检查 / 在环试点路径裁决
│   ├── eval_discipline.py v1.0.1      ← 评测纪律三门（V21 先写后测 / V28 写回一致 / V29 基线防覆盖）
│   ├── eval_artifacts_check.py v1.1   ← 评测期产物校验器（检查项 Q-1~Q-9，验证补全工程甲档工具二）
│   ├── dep_check.py v1.0.1            ← 依赖检测器（DEP-1~5 五项）
│   ├── deliver_check.py v1.0.2        ← 交付物检查器（EX-1~7：存在性/结构/license 等）
│   ├── inject_test.py v1.0.3          ← 跨宿主加载注入测试（检查项 V23，fail-loud 验证）
│   ├── kw_locator.py v1.0.1           ← 关键词定位器（B3-1，危险操作定位供给）
│   ├── smoke_runner.py v1.1           ← 脚本冒烟套件（检查项 V6，C1–C5）
│   ├── local_gate.py v1.2             ← 一键本地门禁（全套单测 + 全工具冒烟）
│   ├── tests/                         ← 固化回归 13 套 233 组断言（2026-10-03 实测）
│   └── README.md / OPERATIONS.md      ← 脚本级说明与操作
└── .verification/                     ← 工具链自身留痕（iteration-1、m1-s）
```

## 三、版本状态总览（2026-10-03 验收实操后）

| 产物 | 版本 | 状态 | 评审/验证闭环 |
|---|---|---|---|
| agent-skill-llm-review | **v1.4** | **验收 PASS + 终审通过 + v1.4 放行签认（2026-10-03）**；触发门训练集 36/36 零偏差；基线 v1.4；运行期观测中（周体检自动化） | 全门无阻断 FAIL；126+36 次子代理运行；30 门次零 FAIL |
| agent-skill-trigger-eval | v1.1 | **验收 PASS（10 门全 PASS）**；自身正式触发实测待办（B 区条件项） | 七轮评审 12 条闭环；基线 v1.1 已落盘 |
| agent-skill-quality-ab | v1.2 | **验收 PASS（9P+1W，EX-3 已评估接受）**；自身正式触发实测待办（B 区条件项） | 六轮评审闭环；基线 v1.2 已落盘 |
| agent-skill-validation-suite | v1.1 | 新建（2026-10-03）；生命周期验证一键编排（v1.1：write 阶段挂 w_static_lint、test 阶段挂 eval_artifacts_check） | 设计期命名预检 3/3 PASS；四目标 dogfood（write+test ×4）留痕在案；自检详见其 .verification/ |
| tools/（12+2 工具 + 1 门禁） | 见目录树 | **12 原工具 + 门禁全员冻结**（2026-10-03 起，改动走冻结流程）；甲档两新工具 w_static_lint/eval_artifacts_check v1.1（新增文件，验证补全工程交付） | 历轮评审全闭环；13 套单测 233 组断言全 PASS；全量门禁 78 项 PASS |
| 验证补全工程甲档两新工具 | v1.1 | w_static_lint（L-1~L-18）+ eval_artifacts_check（Q-1~Q-9）建成挂载，dogfood + 独立自查轮完成，文档批已同步 | 各过一轮外部评审（→v1.0.1）+ 独立自查轮（→v1.1）；待第 7 步双盘同步后入冻结清单 |
| 验收留痕 | — | acceptance-report ×3（llm-review `808bca3d`/trigger-eval `6d861dd1`/quality-ab `cbbcde9b`）+ warn-assessment ×3（2026-10-03 终效确认） | 7 处 WARN：4 整改/连带闭环、3 评估接受 |

## 四、关键纪律（摘要）

1. **双盘同步**：`D:\sData\specSkill` 为归档基线，宿主库 `~/.workbuddy/skills/` 为运行副本；每次产出后命令行复制并 SHA256 成对抽验（`.verification/` 是隐藏目录，资源管理器复制易漏）。
2. **冻结流程**：冻结工具改动必须走 `test_regression → 脚本冒烟 → tools-fix-log 追加 → 双盘同步`；一键自证 = `python tools/local_gate.py --run`。
3. **验证隔离**：验证集（validation）结果不得参与 description 修改决策；修订只依据训练集（train）失败。
4. **冻结集不可变**：`sample-queryset.json` 等冻结留证字节级保存，改动即视为重新构造。
5. **退出码约定**：脚本工具族统一 0/1/2（全过/FAIL 或输入错误/WARN），仅供人工快速判读，编排器不得仅凭退出码作验收阻断。
6. **side-effects 收纳**：子代理杂散产物一律移入当轮 `side-effects/` 留证。

## 五、文档索引

| 想了解 | 去哪 |
|---|---|
| **从零开始怎么验证一个技能（新手全流程）** | [验证操作总说明书.md](验证操作总说明书.md) |
| 生命周期一键验证怎么触发 | `agent-skill-validation-suite/SKILL.md` 及其 `references/lifecycle-map.md` |
| 内部代号什么意思（四阶段、检查项编号等） | [GLOSSARY.md](GLOSSARY.md) |
| 某个脚本何时跑/怎么跑/有何影响 | [tools/OPERATIONS.md](tools/OPERATIONS.md) |
| 触发评测怎么做（五步流程/提示词模板/修订回路） | `agent-skill-trigger-eval/SKILL.md` |
| 双跑对照怎么做（三铁律/断言设计/delta 判定） | `agent-skill-quality-ab/SKILL.md` |
| 查询集怎么构造 | `agent-skill-trigger-eval/references/queryset-spec.md` |
| llm-review 的完整验证史与裁决记录 | `agent-skill-llm-review/.verification/runs.md`、跨会话续接档案 |
| 三技能验收结论与 WARN 处置 | 各技能 `.verification/acceptance-report.md`、`warn-assessment.md` |
| 待办事项与新会话入口 | `D:\sData\standardSkill\K类实现-状态卡.md`（蒸馏版；完整史在《K类实现-跨会话续接档案.md》） |
