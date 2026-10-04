# agent-skill-trigger-eval 修复记录（fix-log.md）

## v1.1（2026-10-02 第七轮评审，12 条主张：11 属实采纳 + 1 部分采纳）

| # | 核实 | 处置 |
|---|---|---|
| S-1 [S] load_json 无类型校验 | 属实——非 dict 根时 `.get` 抛 AttributeError 不在 except 列表；与 grade_ab.py P-7 同类 | `isinstance(data, dict)` 校验抛 ValueError，ValueError 加入 except（与工具族对齐） |
| S-2 [S] 汇总把 WARN 计作"过" | 属实 | 采纳方案一：PASS 与 WARN 分开统计，`N/M 过（另 K WARN）` |
| S-3 [S] 示例文件含个人绝对路径 | **方向属实、处置分化**：①`sample-queryset.json` 是 llm-review 冻结集的字节级副本（sha256 752f7c38 已入冻结记录与 spec），**不可修改**——改动即破坏留证链；且个人真实路径正是 §6.2.3"注入真实语境"的示范要求 → 在 queryset-spec.md 头部加注"字节级冻结不可改、跨用户复用须按自己环境重构" ②`evals.json` 是自有未冻结草案 → `D:/skills/quote-gen` 改为通用相对路径 `my-skills/quote-gen` |
| P-1 提前终止默认空操作 | 属实——默认每条恰好 3 次时无剩余可跳 | SKILL.md 步骤 2 澄清"仅当计划运行次数 >3 时适用；默认 3 次为空操作" |
| P-2 三处条数口径不一 | 属实（严格 20 / 约 20 / 20±2 并存） | 统一为"总量 20（±2），正负各 8–10，train:validation=12:8（60/40）"；spec §一与 §五自检对齐 |
| P-3 触发词 6 个串扰风险 | 属实——"触发率""触发实测"与 llm-review 触发域语义重叠 | 合并为"触发率实测"（6→5 词），边界改为双向区分（实测触发率→本技能；评 description 文本质量→llm-review）。注：description 已改，正式触发实测前属草案态 |
| P-4 loaded 非 bool 静默丢弃 | 属实——`"loaded": 1` 被当作未触发且无警告 | 非 bool 非 None 记入 bad_loaded 告警（stderr），覆盖率中计为丢弃 |
| P-5 退出码 1 语义混同 | 属实 | docstring 改"1=任一 FAIL 或输入错误"+ 显式声明"仅供人工快速判读，编排器不得仅凭退出码阻断"（与 grade_ab S-3 方案二同口径）；SKILL.md 步骤 5 同步 |
| P-6 "126 次实测"无留痕 | 属实（证据在 llm-review 侧，本技能内无指针） | §二 加证据指针：runs.md 与 run-log.md 路径，供核对 |
| P-7 SKILL.md 无版本行 | 属实 | 加版本指针 v1.1（含 v1.0 首版说明） |
| P-8 unknown 只 WARN 不阻断 | 属实 | 采纳较轻方案：报告新增**统计覆盖率行**（covered/total + 丢弃明细），覆盖率 <80% 升 WARN 进总结论；未采 FAIL 阈值（避免阻断合法工作流，覆盖率可见已足以防误信） |
| P-9 near-miss 口径出入 | 属实（"为主" vs "100%"） | 统一并注明："§6.2.4 原文'为主'系最低要求，本技能执行收紧为 100%" |

## 验证

- 新建 `tests/test_calc_trigger_rate.py` 固化回归 **9 组断言全 PASS**（含 S-1 双断言、S-2 汇总分列、P-4 告警、P-8 覆盖率 50%/100% 双态）；测试侧自查修正 4 处断言笔误（脚本行为自始正确）
- V6 冒烟 5/5；check_skill.py 权威格式门 exit 0（本技能与 quality-ab 双测均过）
- description 变更已同步宿主库；正式触发实测（自身 evals 扩至 20 条冻结后）仍为待办
