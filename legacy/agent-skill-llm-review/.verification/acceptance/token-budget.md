# V11/V17 上下文预算报告（token_budget.py）

- 技能: agent-skill-llm-review（agent-skill-llm-review）
- 工具版本: v1.0.1
- 口径: V11 token 计数（chars/4 保守兜底，宿主 tokenizer 缺席时的固定实现）；V17 预算门——正文 <5000 tokens（官方 [M]）/元数据 ≤100 tokens（项目收紧）/扩展层单文件 ≤500 行（项目收紧）
- 总结论: PASS

| 项 | 检查内容 | 结论 | 证据 |
|---|---|---|---|
| V11-1 | SKILL.md 正文 token <5000（官方 [M]，V11 chars/4 口径） | PASS | 正文 3375 字符 ≈ 844 tokens |
| V17-1 | 元数据 token ≤100（项目级收紧，官方 [S]） | PASS | name+description 346 字符 ≈ 87 tokens〔CJK 占比 54%，chars/4 口径可能低估实际 token，建议人工关注〕 |
| V17-2 | 扩展层单文件 ≤500 行（项目级收紧，官方 [P]） | PASS | 扩展层 6 个文件全部达标 |
| V17-3 | SKILL.md 行数（<300 行判定归 check_skill.py A6） | INFO | 当前 80 行（≥240 触发 V27 预警线，≥300 由 A6 阻断） |
| COV | 扫描覆盖 | INFO | 扩展层文件 6 个 |

> 判定统计: 3/3 PASS。SKILL.md <300 行由 check_skill.py A6 承载；预算超限的处置（拆分/外移）由 V26/V27 与人工裁决承担，本工具不自动改写。
