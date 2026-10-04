# V2 命名冲突预检报告（naming_precheck.py）

- 目标: agent-skill-quality-ab
- 工具版本: v1.0.3
- 口径: V2（[M] 设计期）——同名 name 检索（§1 第 2 条）/description 相似度（余弦 >0.85 或关键词重叠 >0.6 告警，阈值可调）
- 库: .
- 总结论: PASS

| 项 | 检查内容 | 结论 | 证据 |
|---|---|---|---|
| V2-1 | 同名 name / 目录名冲突（§1 第 2 条） | PASS | 库内 2 个已解析技能 + 目录名检索零冲突 |
| V2-2 | description 余弦相似度 ≤0.85（V2 阈值，可调） | PASS | top-1 **agent-skill-trigger-eval=0.328**（判定取第 1，超阈值即告警）；前 3 名: agent-skill-trigger-eval=0.328; agent-skill-llm-review=0.284 |
| V2-3 | description 关键词重叠(Jaccard) ≤0.6（V2 阈值，可调） | PASS | top-1 **agent-skill-trigger-eval=0.108**（判定取第 1，超阈值即告警）；前 3 名: agent-skill-trigger-eval=0.108; agent-skill-llm-review=0.070 |
| COV | 扫描覆盖 | INFO | 库 1 个（不可达 0）、可比技能 2 个; 跳过非技能子目录 1、name 不可解析 0、排除目录 ['.git', '.venv', '.verification', '__pycache__', 'node_modules', 'venv'] |

> 判定统计: 3/3 PASS。相似度告警=人工复核入口；范围定位的实质重叠判断由 V1 设计评审（H）承担，本工具零命中不豁免 V1。
