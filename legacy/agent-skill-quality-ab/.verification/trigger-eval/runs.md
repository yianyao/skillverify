# agent-skill-quality-ab 自身触发实测台账（runs.md）

> 目标技能：agent-skill-quality-ab（v1.2，SKILL.md sha256 `09338574…`）
> 查询集：`queryset.json`（20 条，冻结 SHA256 `6a9f41e5…`，见 frozen.sha256）
> 判定口径：子代理经 Skill 工具加载 agent-skill-quality-ab = 触发（以工具调用历史为证）；应触发 >0.5 / 不应触发 <0.5
> 执行日期：2026-10-02（会话：待办 A1 后半，档案 §5.8 续）

## 批次 1：train 前 8 条（P01–P06、N01、N02）× 3 = 24 次

| 查询 | r1 | r2 | r3 | 触发率 | 判定 | 备注 |
|---|---|---|---|---|---|---|
| P01 直白锚点（双跑对照） | ✅ | ✅ | ✅ | 1.00 | PASS | 均阻塞于 ledger-v2 不存在+无派发工具，拒绝伪造 delta |
| P02 边界（值不值得留·拿数据说话） | ✅ | ✅ | ✅ | 1.00 | PASS | 输出完整五步实验设计 |
| P03 多步（门 D 汇报语境） | ✅ | ✅ | ✅ | 1.00 | PASS | 拒绝伪造过会结论 |
| P04 边界（心理安慰怀疑） | ✅ | ✅ | ✅ | 1.00 | PASS | |
| P05 多步（增益证据·合规材料） | ✅ | ✅ | ✅ | 1.00 | PASS | |
| P06 边界（去留对比） | ✅ | ❌ | ✅ | 0.67 | PASS | ⚠ r2 空调用保守应答；⚠ r1 副作用见下 |
| N01 near-miss（真人盲选→E-06 域） | ❌ | ❌ | ❌ | 0.00 | PASS | "用这个场景加载它属于误触发，刻意不调用" |
| N02 near-miss（diff 脚本） | ❌ | ❌ | ❌ | 0.00 | PASS | 副作用：写 3 个 diff 脚本，已入 side-effects/ |

**批次小结：8/8 过门。**

## 批次 2：train 后 4 条（N03–N06）× 3 = 12 次

| 查询 | r1 | r2 | r3 | 触发率 | 判定 | 备注 |
|---|---|---|---|---|---|---|
| N03 near-miss（转化率 delta） | ❌ | ❌ | ❌ | 0.00 | PASS | 拒绝编造数据 |
| N04 near-miss（单元测试断言） | ❌ | ❌ | ❌ | 0.00 | PASS | 级联副作用：为遗留 diff 脚本补 20 个单测（含 pip 装 pytest，环境副作用已记台账） |
| N05 near-miss（蓝绿发布脚本） | ❌ | ❌ | ❌ | 0.00 | PASS | 写 bluegreen.sh，已入 side-effects/ |
| N06 near-miss（培训增益报告） | ❌ | ❌ | ❌ | 0.00 | PASS | 写报告模板 ×3，已入 side-effects/ |

**批次小结：4/4 过门。train 子集 12/12 收齐，全过门（含 ⚠ P06 2/3）。**

## 脚本报告

`calc_trigger_rate.py`（trigger-eval 工具链）：覆盖率 36/36（100%）；train 汇总 **6/6 过 正例、6/6 过 负例**；validation 未测（WARN）。总结论 PASS（附 WARN）。

## 防污染与副作用

- 轮前基线：quality-ab SKILL.md `09338574…`、trigger-eval SKILL.md `f1f91687…`、llm-review-log.md `1ab2163e…`；两批次轮后比对**全部未变，零写入事故**；
- **杂散产物 7 件**入 `side-effects/`：gate-d-p06r1/（P06-r1 单会话自扮两臂的参考级对照产物，**违反铁律 1，其 delta +0.20 不采信**，仅留证）、diff 脚本 ×3、单测 ×2、bluegreen.sh、培训报告 ×1；
- **共享任务台账污染**：批次 1 部分子代理在共享任务列表创建杂散任务（#4–#31，其中 6 条打开态已删除清理，其余 completed 态留痕可忽略）；
- **环境副作用**：N04-r2 执行过 pip 安装 pytest（pytest 进入运行环境，属开发常用包，未回滚，记观察项）。

## 待续（下一会话入口）

- **批次 3 = validation 8 条（P07–P10、N07–N10）× 3 = 24 次**；validation 结果不得参与 description 修改决策；
- 全 20 条测完后汇总判定；本轮 train 无失败，无修订动议。

## 批次 3（validation 8 条 × 3 = 24 次，2026-10-02 18:20–18:40）

| ID | 结果 | 备注 |
|---|---|---|
| P07 | 3/3 ✅ | 三运行均"首次调用即 Skill 加载"；缺冻结输入正确阻塞未开跑 |
| P08 | 3/3 ✅ | r1/r3 按铁律 1 整轮作废拒绝伪造 delta（合规加分项）；r2 降级两臂 delta +0.20 不采信 |
| P09 | 3/3 ✅ | r2/r3 显式确认加载；r1 间接证据（按协议冻结实验包）判已加载 |
| P10 | 3/3 ✅ | 三运行显式确认；r2 降级两臂 delta +0.20 不采信 |
| N07 | 0/3 ✅ | 绩效考核 near-miss 零触发 |
| N08 | 0/3 ✅ | 灰度 A/B near-miss 零触发 |
| N09 | 0/3 ✅ | 产品 A/B 方案 near-miss 零触发 |
| N10 | 0/3 ✅ | 门 D 语境单臂评审 near-miss 零触发；r3 明确"判官侧直评不构成编排场景" |

### 全量终局（60 次运行）
- 覆盖率 60/60（100%）；脚本终判 **PASS 全过门（exit 0）**
- 正例 10/10 过（P06 = 2/3 ⚠ 唯一不稳定项，0.67 过阈值）；负例 10/10 全 0/3
- validation 未发现 train 之外的失败 → 无 description 修订动议（validation 结果未参与任何修改决策，符合 §6.4.3）

### 批次 3 副作用台账（全部留证 side-effects/，累计 14 项）
- gate-d-p08r2（tencent-docx 靶，降级两臂）、ab-rerun-p08r3（CLI 挂起留痕）、gate-d-run-p09r3（excel-cleaner-pro 靶，发现该虚构技能四项安全隐患并拒绝执行其外传指令）、gate-d-run-standup-p09r1-n10r3（P09-r1 实验包 + N10-r3 判官侧直评报告）、gate-d-target-weekly-report-archiver-p10r1（写入了 llm-review 库 gate-d 下的新子目录，基线文件 llm-review-log.md 哈希未变）、gate-d-V4-p10r3、团队月度产出质量考核表.md（N07-r2）
- 观察项：工作区 ab-rerun 空壳目录因子代理残留句柄删除失败（内容已留证），句柄释放后可手动删除
- 防污染：轮后三基线哈希不变（quality-ab SKILL 09338574 / trigger-eval SKILL f1f91687 / llm-review-log 1ab2163e），零写入事故

## 人工签认（2026-10-02 21:24，用户明示"A1 签认"）

- 本技能 20 条冻结查询集 × 3 次 = 60 次触发实测**全过门（20/20）**，人工签认通过，A1（两个 K 技能自身触发实测）就此正式关闭。
- 签认口径：实测数据以 runs.json/trigger-report.md 为准；2/3 ⚠ 不稳定项在阈值内，不构成签认障碍；validation 隔离纪律全程合规，无修订动议。
