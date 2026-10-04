# specSkill 操作手册（仓库级）

> 何时执行 / 执行目的 / **执行者（工具或 skill）** / 执行影响。脚本级细节见 [tools/OPERATIONS.md](tools/OPERATIONS.md)；本手册回答"整个仓库日常怎么用"。
> 代号含义见 [GLOSSARY.md](GLOSSARY.md)。

---

## 场景 0：一键生命周期验证（推荐入口）

**执行者**：`agent-skill-validation-suite` 技能（K 编排，v1.0）——会话里直接说"用 validation-suite 验证 xxx"；或命令行 `python agent-skill-validation-suite/scripts/validate_suite.py --stage <design|write|test|deliver|auto> ...`。

**何时**：不想逐个记工具命令时；新技能从设计到交付各阶段；交付前全门复扫。

**执行影响**：按阶段自动调用下述各工具并汇总判定报告（可 `--out` 落盘）。调度器只负责"调齐+汇总"，触发评测子代理实测、双跑对照、语义评审仍由对应编排技能现场执行；验收阻断须结合人工终审。新手全流程说明见 [验证操作总说明书.md](验证操作总说明书.md)。

---

## 场景 1：给某个技能做格式体检（格式门 A——静态格式检查）

**执行者**：`tools/check_skill.py`（S 工具，v1.1.4；A1 实检依赖官方 `agentskills` CLI）

**何时**：SKILL.md 或 scripts 修订后；W/E/M 阶段每轮收尾；交付前终检。

```bash
cd /d/sData/specSkill/tools
python check_skill.py <skill_dir> --out <skill_dir>/.verification/m1-s/format-gate.md
python check_skill.py <skill_dir> --lines 500      # 需官方 500 行口径时
```

- **影响**：只读（A10 会以 `--help` 无害调用各脚本）；退出码 0=全 PASS / 1=有 FAIL / 2=仅 WARN-SKIP。
- **判定**：[M]/[S] 级 FAIL 阻断交付；A6 项目收紧 <300，240–299 触发 V27 预警（WARN，提示拆分评估）。

## 场景 2：触发评测（验证技能"该触发的会不会触发"——触发门 C）

**执行者**：`agent-skill-trigger-eval` skill（K 编排，派子代理实测）+ `scripts/calc_trigger_rate.py`（S 工具算触发率）

**何时**：新技能交付前（门 C）；description 修订后的整集回归；换新宿主时（先过场景 5 在环试点闸门）。

```bash
# ① 防污染快照（人工）：目标技能关键留痕双盘快照 + SHA256 记录
# ② 分批派全新子代理执行查询（每批 6–8 条，每条 ≥3 次），按 SKILL.md 步骤 3 提示词模板
# ③ 记台账 runs.json（格式见 SKILL.md 步骤 4）
python agent-skill-trigger-eval/scripts/calc_trigger_rate.py \
    --runs runs.json --queryset queryset.json --out trigger-report.md
```

- **判定口径**：应触发 >0.5、不应触发 <0.5；报告含 train/validation 分列汇总与统计覆盖率。
- **影响**：子代理会真实执行查询（可能写文件）——快照与轮后哈希比对是强制步骤；杂散产物移 `side-effects/`。
- **纪律**：validation 结果不得驱动 description 修改；负例误触发归纳类别写负向边界，禁关键词照抄。

## 场景 3：双跑对照（验证技能"带来多少质量增益"——质量门 D）

**执行者**：`agent-skill-quality-ab` skill（K 编排，双臂派子代理）+ `scripts/grade_ab.py`（S 工具算 delta）

**何时**：技能验收（门 D）；重大修订后增益复核。

```bash
# ① 同题任务两臂各派全新子代理（Arm-A 加载技能 / Arm-B 禁 Skill 工具，禁 resume）
# ② 断言清单（E-04 双评）评分后填 grading.json（格式见 SKILL.md 步骤 4）
python agent-skill-quality-ab/scripts/grade_ab.py \
    --grading grading.json --out delta-report.md \
    [--cost-a outputs/with-skill-report.md --cost-b outputs/without-skill-report.md]
```

- **判定**：delta >0 = PASS 候选 / =0 交人工 / <0 = FAIL；**脚本结论一律候选，最终判定人工签认**；delta_conclusion 由人工回填（脚本不读不写）。
- **硬约束**：两臂断言 text 须唯一且同源（脚本校验，不同源/重复直接报错）；任何一臂沾另一臂上下文整轮作废。

## 场景 4：脚本改动后的回归闭环（冻结流程）

**执行者**：`tools/local_gate.py`（S 门禁，v1.2 一键入口）；底层=`tests/` 13 套单测 + `tools/smoke_runner.py`（V6 冒烟）

**何时**：任何 `tools/` 或技能 `scripts/` 的 .py 变更后（强制）；先过门再同步双盘。

```bash
cd /d/sData/specSkill/tools
python local_gate.py --run                          # 全量门禁（LG-1 单测 13 套 233 组 + LG-2 全工具冒烟）
python local_gate.py --run --tests-only             # 快速回路（仅单测）
python local_gate.py --run --out .verification/iteration-1/local-gate.md   # 落盘留痕

# 底层细粒度（门禁定位到问题后按需单跑）：
python tests/test_regression.py                     # 工具链回归（9 组）
python tests/test_check_skill.py                    # check_skill 回归（26 组）
python smoke_runner.py --scripts <变更脚本> --out <skill>/.verification/smoke-xxx.md
# 之后：tools-fix-log.md（或技能 .verification/fix-log.md）追加轮次记录 → 双盘同步
```

- **影响**：LG-1 子进程隔离跑单测；LG-2 冒烟会以子进程实际运行被测脚本（约 4 次/脚本，均为无参报错路径）；冒烟报告禁止覆盖历史（旧报告保留 runN）。

## 场景 5：换新宿主使用本体系

**执行者**：`tools/host_compat.py`（S 工具，v1.0）

```bash
python tools/host_compat.py --skill-dir <被试点技能> [--json]
```

- **何时**：任何在环试点启动之前（第一步，流程违规点）。
- **路径裁决**：A 全自动 / B 半自动（"待确认"须核实是否真在宿主会话内）/ C 降级 runbook。
- **试点闸门**：构造金丝雀技能（名字含随机串）+ 3–5 个全新子代理观察加载；通过才可用 K 技能，否则降级人工逐条新会话。
- **影响**：只读零破坏，可随意运行。

## 场景 6：双盘同步与哈希抽验（每次产出后）

**执行者**：人工（命令行 cp + sha256sum；无专用工具）

```bash
cp -r <产物> /c/Users/yianyao/.workbuddy/skills/<技能>/     # D 盘 → 宿主库
cp <留痕> /d/sData/specSkill/<路径>                          # 宿主侧留痕 → D 盘归档
sha256sum <D盘文件> <C盘文件> | awk '{print substr($1,1,8), $2}'   # 成对核验
```

- **要求**：SKILL.md 与关键脚本哈希必须成对一致；`.verification/` 用命令行复制（隐藏目录易漏）。

## 场景 7：运行期观测（R 轮常态维护）

**执行者**：自动化周体检（每周一 09:00 定时任务）；检测逻辑=V9/V24/V27 只读检测

- **周体检**：追加 `.verification/run-log.md` 台账；**安全告警即提示停用 + 回流水审计**。
- **收口条件**：连续 4 周全绿且无迭代回流 → 降频每月。
- 基线：`.verification/r-phase/baseline-hashes.sha256`（12 文件）。

## 场景 8：验收全门复扫与验收报告落盘（挂载/交付期 M1 终检口径）

**执行者**：`tools/` 12 门工具组合（check_skill / security_scan / naming_precheck / token_budget / eval_discipline / dep_check / deliver_check / smoke_runner / inject_test / host_compat / **w_static_lint（L-1~L-18 编写期静态补检）** / **eval_artifacts_check（Q-1~Q-9 评测产物校验，有 .verification 时）**——以 `--skill-dir` 传目标技能逐一执行）

**何时**：技能交付验收时；重大修订后的复扫。

```bash
cd /d/sData/specSkill
python tools/check_skill.py   <skill_dir> --out <skill_dir>/.verification/m1-s/format-gate.md
python tools/w_static_lint.py <skill_dir> --out <skill_dir>/.verification/m1-s/static-lint.md
python tools/security_scan.py <skill_dir> --out <skill_dir>/.verification/m1-s/security-scan.md
python tools/naming_precheck.py <skill_dir> --library /d/sData/specSkill --out <skill_dir>/.verification/m1-s/naming-precheck.md
python tools/token_budget.py  <skill_dir> --out <skill_dir>/.verification/m1-s/token-budget.md
python tools/eval_discipline.py <skill_dir> --out <skill_dir>/.verification/m1-s/eval-discipline.md
python tools/eval_artifacts_check.py <skill_dir>/.verification --out <skill_dir>/.verification/m1-s/eval-artifacts.md
python tools/dep_check.py     <skill_dir> --out <skill_dir>/.verification/m1-s/dep-check.md
python tools/deliver_check.py <skill_dir> --out <skill_dir>/.verification/m1-s/deliver-check.md
python tools/inject_test.py   <skill_dir> --out <skill_dir>/.verification/m0-s/inject-test.md
python tools/kw_locator.py    <skill_dir> --out <skill_dir>/.verification/b3-s/kw-locate.md
python tools/host_compat.py --skill-dir <skill_dir>
```

**执行方式**（口径=standardSkill/操作手册 §1.4 个人版 + §5.1.1 对照表）：

| 检查 | 执行方式 |
|---|---|
| 门 A、V8、V2、V11/V17、V21/V28/V29、DEP、EX、V6、V23、L-1~L-18、Q-1~Q-9 | 脚本（上列命令） |
| V3/V4 注册与共存冒烟、V5/V22 依赖与环境实测、V13 安装审计单、V15 许可判断 | 人工兜底（环境事实/价值裁决，个人版人工执行） |
| V7 CI、V9/V24 运行期遥测 | 个人版降级（pre-commit/单文件 workflow 二选一；run-log 周体检） |

- **验收报告规范位**：`<skill_dir>/.verification/acceptance-report.md`（deliver_check EX-1 期望路径；分报告放 `.verification/acceptance/`）。
- **WARN 处置**：FAIL 零容忍；WARN 逐条书面评估落 `<skill_dir>/.verification/warn-assessment.md`（评估接受/整改闭环均须留痕，终效人工签认）。
- **口径**：naming_precheck 排重范围=设计库（`--library /d/sData/specSkill`；宿主部署副本同名系预期非冲突）。

## 场景 9：验收基线落盘与防覆盖比对（检查项 V29，record 模式）

**执行者**：`tools/eval_discipline.py`（S 工具，v1.0.1，check/record 双模式）

**何时**：每轮验收通过时（record 落基线）；其后任何时点复检（check 模式 V29-2 防覆盖比对）。

```bash
# 验收通过时落基线（--snapshot-dir 必须传绝对路径，相对路径会解析到设计库根——实测踩坑）
python tools/eval_discipline.py <skill_dir> --mode record --version v1.4 --iteration 1 \
    --accepted-at 2026-10-03T12:25:09 \
    --acceptance-report ".verification/acceptance-report.md" \
    --snapshot-dir "D:/sData/specSkill/<skill_dir>/.verification/iteration-1"

# 之后任何时点防覆盖比对（篡改/删除/基线外新增均 FAIL）
python tools/eval_discipline.py <skill_dir>
```

- **留痕变更后**（iteration-1 内文件有增改）：须 re-record 刷新快照，否则 V29-2 FAIL。
- **影响**：record 仅写 `.verification/.iteration-baseline`（不触碰评测产物与 SKILL.md）。

## 场景 10：技能 description 修订轮（vN → vN+1）

**执行者**：修订提案（人工裁决）→ 改 SKILL.md/CHANGELOG/evals.json → `tools/check_skill.py`（A 门）+ `tools/eval_discipline.py --description-text`（V28-1 写回一致性）+ `agent-skill-trigger-eval` skill（门 C 触发回归）→ `tools/eval_discipline.py --mode record`（基线升级）

**闭环步骤**（先例：llm-review v1.3→v1.4，见 `agent-skill-llm-review/.verification/iteration-1/v1.4-revision-closure.md`）：

1. 提案落 iteration-N/ 供人工裁决；采纳后改 SKILL.md description + 版本行、CHANGELOG 续记、evals.json 版本同步
2. 同步宿主部署副本（三文件，SHA256 成对一致）
3. A 门复跑 PASS；V28-1 传 `--description-text` 逐字符核对 PASS
4. 门 C 触发回归：train 查询 ×3 轮全新子代理实测（协议 C2；validation 可选缓跑）
5. re-record 基线（版本号更新）→ 档案续记 → 双盘同步

## 异常处置速查

| 症状 | 处置 |
|---|---|
| check_skill 实弹 exit 2 但无 FAIL | A1 SKIP 或 WARN/SKIP 并存——看报告"总结论"后缀，SKIP=官方 CLI 未装（等效覆盖；装齐法见 tools/OPERATIONS.md A1 节） |
| eval_discipline record 后 V29-2 FAIL | iteration-N 快照域文件有增改——re-record 刷新基线（场景 9） |
| eval_discipline --snapshot-dir 相对路径误抓 | 快照解析到设计库根同名目录——**必须传绝对路径**（实测踩坑已留痕） |
| 触发评测"未运行 WARN" | 查询集有条目没跑过；补跑或人工确认豁免 |
| grade_ab 报"text 不同源/重复" | 两臂不是评自同一份冻结断言清单，或清单有重复 text——回到断言设计步骤 |
| inject_test V23-0 FAIL | 对照组失败=解析器/环境问题（非技能缺陷），先排查 agentskills CLI 再复测 |
| 子代理产物散落 | 全部移入当轮 `side-effects/`，轮后哈希比对找意外写入 |
| 双盘哈希不一致 | 以最近一次验证通过的副本为准恢复另一侧，重跑受影响回归 |
| GBK 终端长行乱码 | 多为终端显示问题，用 Python 按行核验文件完好后再判断 |
