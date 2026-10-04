# 依赖检测五项报告（dep_check.py）

- 技能: agent-skill-quality-ab（C:\Users\yianyao\.workbuddy\skills\agent-skill-quality-ab）
- 工具版本: v1.0.1
- 口径: §8.1.2 版本固定（[M]）/§8.2.1 内联声明（[M]）/§8.2.2 禁 manifest（[M]）/§8.2.3+§8.2.5 版本说明符（[S]/[P]）/§8.2.4 脚本清单完备（[M]）；SKIP 不计警告（须人工留痕佐证，不豁免上游条款）
- 总结论: PASS（SKIP 2 行）

| 项 | 检查内容 | 结论 | 证据 |
|---|---|---|---|
| DEP-1 | 外部工具调用版本固定（pkg@1.2.3，§8.1.2） | SKIP | 未发现运行器/包管理调用（npx/bunx/uvx/pipx/pip/uv/deno/go run）——条款不适用 |
| DEP-2 | 捆绑脚本内联依赖声明（§8.2.1） | PASS | 1 个代码文件第三方依赖均已内联声明或无第三方依赖 |
| DEP-3 | 禁独立 manifest / 安装步骤（§8.2.2） | PASS | 技能树内未发现独立依赖 manifest |
| DEP-4 | 依赖版本说明符固定（§8.2.3/§8.2.5） | SKIP | 无内联依赖声明可核（无 PEP 723 块/Deno-Bun 版本化导入/gem 声明）——条款不适用 |
| DEP-5 | 脚本清单完备（scripts/ 实际文件 ⊆ SKILL.md 清单，§8.2.4） | PASS | scripts/ 1 个文件全部在 SKILL.md 列出；'用途与调用方式'语义归 H |
| COV | 扫描覆盖 | INFO | DEP-1/2/3/4/5 SKILL.md+scripts/+技能树 manifest |

> 判定统计: 3/3 PASS。运行器与环境匹配（§8.1.5–§8.1.6/V22）与依赖实际可解析属 O 实测域（M1-9），不在本工具范围；§8.2.6 环境干扰（Gemfile/node_modules 在场时自包含机制可能失效）须真实挂载环境复测。
