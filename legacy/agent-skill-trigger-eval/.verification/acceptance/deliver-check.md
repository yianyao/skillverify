# 存在性/schema 门报告（deliver_check.py）

- 技能: agent-skill-trigger-eval（agent-skill-trigger-eval）
- 工具版本: v1.0.2
- 口径: §15.7/M1-7 交付物（[M]）/§7.7.4+E3-2 feedback.json（[M]）/§7.2.6 grading.json（[M]）/§2.4.1–2.4.2+V15 license（[S]）/§5.1.3+§5.1.6+§5.1.9 B1 留档（[S]）；SKIP 不计警告（须人工留痕佐证）
- 总结论: WARN（需人工复核）（SKIP 3 行）

| 项 | 检查内容 | 结论 | 证据 |
|---|---|---|---|
| EX-1 | 交付物存在性（SKILL.md + evals.json + 验收报告，§15.7/M1-7） | PASS | SKILL.md + evals/evals.json + .verification/acceptance-report.md 齐备 |
| EX-2 | feedback.json 落盘与结构（text/passed/evidence，§7.7.4/E3-2） | SKIP | 技能树内未产出 feedback.json——E3 人工复核运行产物（W 阶段预期缺失，SKIP 不计警告；进入 E3 后须落盘并复检） |
| EX-3 | grading.json schema（text/passed/evidence + summary 四键，§7.2.6） | SKIP | 技能树内未产出 grading.json——测试期运行产物（未进入测试工作区属预期，SKIP 不计警告） |
| EX-4 | license 许可合规初筛（§2.4.1–2.4.2/V15） | SKIP | frontmatter 无 license 字段且无随包 LICENSE 文件——内部使用不适用（对外交付时 V15 升 [M]：须声明许可、完整条款随包、第三方素材许可留档） |
| EX-5 | 反向测试记录存在性（§5.1.3/B1-1） | PASS | .verification/ 内 2 个文件含"反向测试"留痕（如 .verification/acceptance/deliver-check.md）——记录内容质量归 L/H（B1-4） |
| EX-6 | 执行→修订闭环记录（§5.1.6/B1-2） | WARN | .verification/ 下未见 iteration-N 目录（含文件）——真实执行→修订闭环留痕人工确认（K 流程可能在案他处） |
| EX-7 | 执行轨迹分析记录（§5.1.9/B1-3） | PASS | .verification/ 内 2 个文件含"轨迹"留痕（如 .verification/acceptance/deliver-check.md）——轨迹三类缺陷归因质量归 L/H |
| COV | 扫描覆盖 | INFO | EX-1~7 SKILL.md+evals.json+验收报告+feedback/grading schema+license+B1 留档（.verification/ 全树） |

> 判定统计: 3/3 PASS。B1 三类记录的关键词初筛局限（留档可能在技能树外素材档案）与 feedback/grading 为测试期运行产物（未产出属预期）均已写入证据；记录内容质量（B1-4 终审、E3-1 逐用例复核、反馈具体性、V15 第三方素材合规）归 L/H，不在本工具范围。
