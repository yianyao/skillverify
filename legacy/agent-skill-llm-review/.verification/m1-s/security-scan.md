# V8 安全扫描报告（security_scan.py）

- 技能: agent-skill-llm-review（C:\Users\yianyao\.workbuddy\skills\agent-skill-llm-review）
- 工具版本: v1.0.2
- 口径: V8（[M] 机械门）——secret 正则+熵（§9.6）/端点比对（§9.2 静态）/多语言交互（§8.3.1）/破坏性关键词防护（§8.3.10）/危险指令关键词（§9.8 关键词部分）
- 白名单: 无
- 扫描覆盖: 13 文件（跳过二进制 0、超限 0、符号链接 0；排除 .git, .venv, .verification, __pycache__, node_modules, venv）
- 总结论: WARN（需人工书面评估）

| 项 | 检查内容 | 结论 | 证据 |
|---|---|---|---|
| V8-1 | secret 正则库零命中（§9.6） | PASS | （8 类格式 × 13 文件） |
| V8-2 | 熵检测零命中（§9.6 启发式） | PASS | 阈值: 长度>=20 且熵>= 4.5（hex 哈希天然低于阈值） |
| V8-3 | 外部端点与声明比对（§9.2 静态） | PASS | 未发现外部 URL |
| V8-4 | 多语言交互调用零命中（§8.3.1） | PASS | 8 类模式 × 13 文件零命中（扫描面含全包，补强 A9 的 scripts/*.py 限界） |
| V8-5 | 破坏性关键词有确认防护（§8.3.10） | PASS | 代码文件零命中破坏性关键词（或均有防护） |
| V8-6 | 危险指令关键词零命中（§9.8 关键词部分） | WARN | 代码文件零命中；文档文件提及 3 处（如'不得绕过确认'类合规表述，人工复核）: references\w-prompts.md:187 绕过确认; references\w-prompts.md:187 静默上传; references\w-prompts.md:187 扩大权限 |
| COV | 扫描覆盖 | INFO | 扫描 13 个文本文件; 跳过二进制扩展名 0、超 2MB 0、符号链接 0; 排除目录 .git, .venv, .verification, __pycache__, node_modules, venv |

> 判定统计: 5/5 PASS。语义审计（§9.1 恶意逻辑、§9.2 用途一致性、§9.8 完整语义）仍由 W-L 评审 + H 终审承担，本工具零命中不豁免语义审计。
