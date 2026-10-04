# 触发率过门报告（calc_trigger_rate.py）

- 口径: §6.3.4（应触发 >0.5，不应触发 <0.5）；每条 ≥3 次
- 统计覆盖率: 60/60 条记录（100%；丢弃: query_id 不在集内 0、格式异常 0）
- train 汇总: 6/6 过 正例、6/6 过 负例
- validation 汇总: 4/4 过 正例、4/4 过 负例

| 查询 | 子集 | 应触发 | 运行 | 触发 | 触发率 | 结论 |
|---|---|---|---|---|---|---|
| N01 | train | 否 | 3 | 0 | 0.00 | PASS |
| N02 | train | 否 | 3 | 0 | 0.00 | PASS |
| N03 | train | 否 | 3 | 0 | 0.00 | PASS |
| N04 | train | 否 | 3 | 0 | 0.00 | PASS |
| N05 | train | 否 | 3 | 0 | 0.00 | PASS |
| N06 | train | 否 | 3 | 0 | 0.00 | PASS |
| N07 | validation | 否 | 3 | 0 | 0.00 | PASS |
| N08 | validation | 否 | 3 | 0 | 0.00 | PASS |
| N09 | validation | 否 | 3 | 0 | 0.00 | PASS |
| N10 | validation | 否 | 3 | 0 | 0.00 | PASS |
| P01 | train | 是 | 3 | 3 | 1.00 | PASS |
| P02 | train | 是 | 3 | 3 | 1.00 | PASS |
| P03 | train | 是 | 3 | 3 | 1.00 | PASS |
| P04 | train | 是 | 3 | 3 | 1.00 | PASS |
| P05 | train | 是 | 3 | 3 | 1.00 | PASS |
| P06 | train | 是 | 3 | 2 | 0.67 | PASS |
| P07 | validation | 是 | 3 | 3 | 1.00 | PASS |
| P08 | validation | 是 | 3 | 3 | 1.00 | PASS |
| P09 | validation | 是 | 3 | 3 | 1.00 | PASS |
| P10 | validation | 是 | 3 | 3 | 1.00 | PASS |

- 总结论: PASS 全过门

> validation 子集结果不得参与 description 修改决策（§6.4.3 隔离纪律）；修订只依据 train 失败。
