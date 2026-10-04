# 评测纪律三门报告（eval_discipline.py）

- 技能: agent-skill-llm-review（agent-skill-llm-review）
- 工具版本: v1.0.1
- 模式: check；未提供评测工作区（V21-2 相关行 SKIP）
- 口径: V21 断言时机（§7.1.5/§7.1.6，[M]，语义半归 H）/V28 写回一致性（§6.5.7，[S]）/V29 iteration 基线（§15.4，[S]）；SKIP 不计警告（须人工留痕佐证，不豁免上游条款）
- 总结论: PASS（SKIP 3 行）

| 项 | 检查内容 | 结论 | 证据 |
|---|---|---|---|
| V21-1 | 评测集在场（evals/evals.json）——用例数记录 | INFO | 形态 queries、当前 12 条。初始 2–3 条为流程纪律：终态数量无法机械验证初始值，是否由 2–3 条起步须经 run-log 留痕佐证（语义归 H） |
| V21-2 | 断言添加时机（晚于首轮产出，§7.1.6） | SKIP | evals.json 为 queries 形态（非 §7 断言评测集）——断言时机条款不适用；质量评估是否遵守断言时机由 runs.md/留痕人工佐证（H） |
| V28-1 | description 写回一致性（选定版本 vs 落盘，§6.5.7） | SKIP | 未提供 --description-final/--description-text——未做 description 优化轮属常态；若已做选定写回，须补依据文件复跑或人工核对留痕 |
| V29-1 | iteration 基线在场（.iteration-baseline，§15.4） | PASS | iteration 1 / version v1.3 / accepted_at 2026-10-02 |
| V29-2 | 防覆盖比对（基线 snapshot vs 现状） | SKIP | 旧式键值基线（无 snapshot 块，哈希外引）——无机械比对依据，建议 record 重落升级；历史防覆盖暂由人工留痕佐证 |
| COV | 扫描覆盖 | INFO | V21-1/2 评测产物、V28 写回依据、V29 基线 |

> 判定统计: 1/1 PASS。初始用例数与'未提前定义 PASS/FAIL'属流程语义（H）；本工具 FAIL 不得自动改写评测产物或基线。
