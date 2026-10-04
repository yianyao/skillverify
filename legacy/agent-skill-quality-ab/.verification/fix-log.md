# agent-skill-quality-ab 修复记录（fix-log.md）

## v1.2（2026-10-02 第六轮评审，7 条全属实全采纳）

| # | 核实 | 处置 |
|---|---|---|
| 2.1 [S] ab_map 重复 text 静默错配 | 属实——sorted 集合校验对重复项失效，ab_map 后写覆盖前写；S-1 修复引入的新缺口 | 重排前加 text 唯一性校验（两臂各查 `len(set)`，重复报错 exit 1）；SKILL.md 步骤 1 同步写明"每条断言 text 须唯一" |
| 2.2 [S] 子对象非 dict 崩溃 | 属实——`"with_skill": "foo"`/null 时 arm_stats 内 `arm.get` 抛 AttributeError 不在 except 列表；P-7 只防了根类型 | arm_stats 开头 `isinstance(arm, dict)` 校验，非 dict 抛 ValueError 走统一错误通道 |
| 2.3 [P] SKILL.md 缺版本行 | 属实 | frontmatter 下方加版本指针（v1.2 汇总 v1.1/v1.2 变更，详情指向 docstring 与 fix-log） |
| 2.4 [P] 两类防线无用例 | 属实——assertions 缺失 / passed 非 bool 是 arm_stats 防线所在 | 补 case11/case12（合计新增 4 组：另含 2.1 重复 text、2.2 非 dict 子对象回归） |
| 2.5 [P] 临时目录未清理 | 属实 | `__main__` finally 块 `shutil.rmtree(TMP, ignore_errors=True)` |
| 2.6 [P] compatibility 缺 Python 版本 | 属实（与 agent-skill-llm-review 口径不一致） | 补"需要 Python 3.10+（scripts 仅用标准库）"，A5 长度仍合规 |
| 2.7 [P] _ev 对 evidence=None 显示 "None" | 属实（可选，采纳） | `e is not None` 显式判空，缺失显示为空 |

## v1.1（2026-10-02 第五轮评审，7 条主张：5 属实采纳 + 1 撤回 + 1 记录不改）

| # | 核实 | 处置 |
|---|---|---|
| S-1 [S] zip 仅校验数量不校验 text 对应 | 属实——顺序不同/条目不同源时 zip 错配，单方优势项失真 | 数量校验后增加 text 集合一致性校验（`sorted` 比对，不同源报错 exit 1），再按 Arm-A 顺序重排 Arm-B（`ab_map`）后逐条配对 |
| S-2 [S] delta_conclusion 字段文档与脚本脱节 | 属实——SKILL.md 未写明由谁回填，脚本确实不读不写 | 采纳方案一：SKILL.md 步骤 5 明确"**人工**回填，脚本不读不写该字段" |
| S-3 [S] 退出码 1 与"候选"语义冲突 | 方向属实，**修法选方案二**（评审建议方案一被否）——0/1/2 是工具族约定（check_skill/host_compat/smoke_runner 一致），delta<0 是"实测结果为负"的强信号，编排器据此阻断并非误判；"候选"语义约束的是 delta>0 不等于验收通过。恒返 0 反而丢掉族约定与信号强度 | docstring 与 SKILL.md 显式声明：退出码仅供人工快速判读，编排器不得仅凭退出码作验收阻断，最终判定人工签认 |
| P-1 cost_estimate label 死参数 | 属实 | label 入错误消息：`文件不存在（{label}: …）`/`读取失败（{label}: …）` |
| P-3 evals.json 8 条偏少、validation 仅 1 正例 | 属实，note 已声明草案性质并指向 queryset-spec 扩充路径 | **不改**（草案即设计意图，正式评测前扩至 20 条 validation ≥4 正 4 负——评审建议已记入本行备查） |
| P-4 arm_stats report 字段未 str 归一 | 属实 | `str(arm.get("report") or "(未记录)")` |
| P-5 单方优势项无证据摘录 | 属实（可选建议，采纳） | 每项附通过臂 evidence 前 48 字符摘录 |
| P-6 --cost-a/--cost-b 示例 | 评审自查撤回 | 无 |
| P-7 load_grading 未校验顶层结构 | 属实——根为 list/number 时 `data.get` 抛 AttributeError 未捕获 | `isinstance(data, dict)` 校验，非 dict 抛 ValueError（进既有 except → exit 1） |

## 验证

- v1.2：`tests/test_grade_ab.py` 扩至 **14 组断言全 PASS**（新增 2.1 重复 text / 2.2 非 dict 子对象 / 2.4 两类防线用例）；V6 冒烟 5/5；check_skill.py 权威格式门 exit 0
- v1.1：固化回归 10 组断言全 PASS；V6 冒烟 5/5；格式门 exit 0。测试侧自查修正 3 处断言笔误（字符串比较把 "a10" 排除、证据摘录查错条目、label 实为 "A"）——脚本行为自始正确

## 遗留

- P-3 扩充事项转正式评测前置条件；grade_ab.py 版本号 v1.1 已入 docstring。
