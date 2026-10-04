# 格式门 A 校验报告（check_skill.py）

- 技能: agent-skill-trigger-eval（D:\sData\specSkill\agent-skill-trigger-eval）
- 口径: §13 A1–A11，A6 <300（项目收紧）；附加 X1/X2 不计入判定
- 总结论: PASS；附 SKIP（仅记录）

| 项 | 检查内容 | 结论 | 证据 |
|---|---|---|---|
| A1 | skills-ref validate | SKIP | 官方 CLI 未安装；等效覆盖=A2–A11 机械项（安装 skills-ref 后本行自动实检） |
| A2 | SKILL.md 位于根目录 | PASS | D:\sData\specSkill\agent-skill-trigger-eval\SKILL.md |
| A3 | name 正则/长度/与目录一致 | PASS | name=agent-skill-trigger-eval，与目录一致 |
| A4 | description 长度 1-1024 非空 | PASS | 长度 347 |
| A5 | compatibility 长度 1-500（若存在） | PASS | 长度 84 |
| A6 | SKILL.md 行数 <300 | PASS | 109 行（项目收紧口径） |
| A7 | 换行符为 LF | PASS | LF only |
| A8 | 引用为相对路径且仅一层 | PASS | 3 个相对引用全部合规；存在性核对: 3/3 全部存在 |
| A9 | 脚本无交互式输入 | PASS | 1 个脚本检索 8 类模式零命中 |
| A10 | 脚本 --help 可运行 | PASS | 1 个脚本全部 exit=0 且有输出（内容正确性→W-14） |
| A11 | frontmatter 可解析且含 name/description | PASS | keys=['compatibility', 'description', 'name'] |
| X1 | UTF-8 无 BOM（附加） | INFO | 无 BOM |
| X2 | evals.json 可解析（附加） | INFO | queries=8 条 |

> 判定统计: 10/10 PASS；A8 触发条件为语义项留 H，--help 内容正确性留 W-14。
