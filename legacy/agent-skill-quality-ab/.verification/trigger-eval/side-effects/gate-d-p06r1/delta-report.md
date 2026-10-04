# 双跑对照 delta 报告（grade_ab.py）

- with_skill: 10/10 = 1.00（outputs/with-skill-report.md）
- without_skill: 8/10 = 0.80（outputs/without-skill-report.md）
- delta: +0.20
- 成本估算: Arm-A ≈365 token（1462 字符 ÷4 粗估）；Arm-B ≈208 token（833 字符 ÷4 粗估）

## 单方优势断言

- 仅 with_skill 通过（2 条）: 对问题做了严重程度分级（如阻断/警告/建议）（A 证据: P1–P3 标注【阻断】，P4–P6 标注【警告】，结论按阻断/警告汇总）; （清单外探测）发现示例命令中输入文件名 repot.md 的拼写错误（A 证据: P6：`repot.md` 疑为 `report.md` 之误，照抄即错）
- 仅 without_skill 通过（0 条）: 无

## 判定: PASS 候选——with_skill 通过率更高

> 本结论为脚本候选，最终判定人工签认（E-04 断言评分须双评零分歧在先）。
