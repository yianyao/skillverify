# 格式门 A 校验报告（check_skill.py）

- 技能: agent-skill-quality-ab（C:\Users\yianyao\.workbuddy\skills\agent-skill-quality-ab）
- 口径: §13 A1–A11，A6 <300（项目收紧）；附加 X1/X2 不计入判定
- 总结论: PASS

| 项 | 检查内容 | 结论 | 证据 |
|---|---|---|---|
| A1 | skills-ref validate | PASS | 官方 CLI validate 通过（exit=0）: Valid skill: C:\Users\yianyao\.workbuddy\skills\agent-skill-quality-ab |
| A2 | SKILL.md 位于根目录 | PASS | C:\Users\yianyao\.workbuddy\skills\agent-skill-quality-ab\SKILL.md |
| A3 | name 正则/长度/与目录一致 | PASS | name=agent-skill-quality-ab，与目录一致 |
| A4 | description 长度 1-1024 非空 | PASS | 长度 357 |
| A5 | compatibility 长度 1-500（若存在） | PASS | 长度 96 |
| A6 | SKILL.md 行数 <300 | PASS | 74 行（项目收紧口径） |
| A7 | 换行符为 LF | PASS | LF only |
| A8 | 引用为相对路径且仅一层 | PASS | 1 个相对引用全部合规；存在性核对: 1/1 全部存在 |
| A9 | 脚本无交互式输入 | PASS | 1 个脚本检索 8 类模式零命中 |
| A10 | 脚本 --help 可运行 | PASS | 1 个脚本全部 exit=0 且有输出（内容正确性→W-14） |
| A11 | frontmatter 可解析且含 name/description | PASS | keys=['compatibility', 'description', 'name'] |
| X1 | UTF-8 无 BOM（附加） | INFO | 无 BOM |
| X2 | evals.json 可解析（附加） | INFO | queries=8 条 |

> 判定统计: 11/11 PASS；A8 触发条件为语义项留 H，--help 内容正确性留 W-14。
