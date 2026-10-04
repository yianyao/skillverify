---
name: agent-skill-validation-suite
description: 对 Agent Skill（AI 技能包）执行生命周期验证编排：按设计、编写、测试、交付四个阶段自动选择并调用本地验证工具链（格式门、安全扫描、命名预检、上下文预算、依赖检测、交付物检查、脚本冒烟、fail-loud 注入等），并集成官方校验器 agentskills validate。当用户开始编写新技能、要求验证技能、要求跑验收门、要求全门复扫，或在新技能生命周期各阶段需要一键验证时使用。仅面向 Agent Skill 质量验证编排：一般内容评审、文章盲评不适用；不替代人工终审、触发评测子代理实测与双跑对照现场编排，也不替代门禁裁决。
---

# Agent-Skill 生命周期验证套件（validation-suite）

**一句话定位**：把 specSkill 工具链的全部验证动作按生命周期阶段编排成一键入口——你告诉它技能在哪个阶段（或让它自动判断），它负责调齐工具、汇总判定、指明下一步。

**边界（何时不该用我）**：
- 触发评测的子代理实测、双跑对照的现场编排 → 分别用 `agent-skill-trigger-eval`、`agent-skill-quality-ab`
- 语义评审、双评、盲评 → 用 `agent-skill-llm-review`
- 人工终审与门禁裁决 → 永远归人，本套件只供给证据

## 工作流程（四步）

1. **判阶段**：向用户确认技能处于哪个阶段；用户不确定时用 `--stage auto` 自动判断：
   - 目录里还没有 SKILL.md → 只能做设计期命名预检（需要 `--name` + `--description`）
   - 没有 `evals/evals.json` → 编写期（写完每改一轮都应重跑）
   - 已有编写期产物 → 交付期全门复扫
2. **运行调度器**（唯一入口脚本，见下方清单）：
   - 设计期：`python scripts/validate_suite.py --stage design --name <技能名> --description "<一句话>"`
   - 编写期：`python scripts/validate_suite.py --stage write --skill-dir <技能目录>`
   - 测试期：`python scripts/validate_suite.py --stage test --skill-dir <技能目录>`
   - 交付期：`python scripts/validate_suite.py --stage deliver --skill-dir <技能目录>`
   - 建议加 `--out <报告路径>.md` 落盘留痕
3. **判读结果**：报告列出每步的退出码与判定（PASS / WARN-SKIP / FAIL）+ 各步输出尾部。整体退出码：0=全过、1=有 FAIL、2=有 WARN/SKIP。**注意：退出码只是快速判读入口，验收阻断必须结合报告证据与人工终审**（仓库纪律：编排器不得仅凭退出码作验收阻断）。
4. **指明下一步**：FAIL 步按报告证据修复后重跑；WARN 步逐条人工甄别；交付阶段全过后，引导用户按《验证操作总说明书》§4 落验收报告（规范位：技能目录下 `.verification/acceptance-report.md`）并做人工终审。

## 阶段 × 工具映射（摘要）

| 阶段 | 调用的工具（检查项） |
|---|---|
| 设计 | 命名冲突预检（V2：同名/描述相似度） |
| 编写 | 格式门 A（11 组静态检查）+ 安全扫描（V8）+ 上下文预算门（V11/V17）+ 依赖检测（DEP-1~5）+ **官方校验 agentskills validate** |
| 测试 | 脚本冒烟（V6）+ 加载注入（V23 fail-loud）+ 评测纪律 check（V21/V28/V29） |
| 交付 | 上列全部 + 命名预检复扫 + 交付物检查（EX-1~7）+ 危险关键词定位（B3-1） |

当需要完整映射、各工具职责与判定口径细节时，读取 references/lifecycle-map.md。

## 工具链定位（部署环境差异）

调度器按以下顺序自动定位工具链目录（须含 check_skill.py）：
1. `--tools-dir` 显式指定；
2. 环境变量 `SPEC_SKILL_TOOLS`；
3. 与本技能同库的相对位置（设计库内部署时自动命中）；
4. 默认设计库安装路径（宿主部署副本场景兜底）。
四处都找不到时报错退出（fail-loud），并提示用 `--tools-dir` 指定——不静默降级、不假跑。

官方校验器探测顺序：PATH 中的 `agentskills` → 托管 venv Scripts 目录。都找不到时该步 SKIP（不计警告），报告会提示安装口径。

## Gotchas

- **`--snapshot-dir` 类路径参数必须绝对路径**：工具链历史踩坑——相对路径会被解析到错误位置（解析到设计库根而非技能目录），导致快照抓错文件。本套件内部已规避，但直接调用 eval_discipline record 模式时务必注意。
- **design 阶段不要传 `--skill-dir`**：设计期技能目录尚不存在；反之其余阶段必须传目录、不要传 name/description。参数给错会 fail-loud（exit 1）并回显用法。
- **SKIP 不是 PASS**：官方 CLI 缺位时官方校验步 SKIP 不计警告，但交付前应补装并复跑——交付期报告出现 SKIP 应主动提醒用户。
- **auto 判阶段偏保守**：auto 只区分"编写期/交付期"，测试期动作（冒烟/注入）默认包含在交付复扫里；若用户只要快速回路，显式传 `--stage test`。
- **验收报告规范位**：`.verification/acceptance-report.md`（deliver_check 的 EX-1 期望此路径）；落错位置会导致闭环复跑不通过。
- **双盘同步**：对本技能或工具链的任何改动，收尾时同步设计库与宿主部署副本并做哈希抽验。

## 脚本清单（scripts/ 全部文件）

| 脚本 | 职责 |
|---|---|
| `scripts/validate_suite.py` | 分阶段调度器（本文全部命令的唯一实现；官方校验集成于此） |

## 评测查询集（草案，未冻结）

`evals/evals.json` 收录 8 条触发评测草案查询。**注意：未冻结、未经正式实测**，正式过门前须按查询集构造规范扩至 20 条并冻结切分（用 `agent-skill-trigger-eval` 技能执行）。
