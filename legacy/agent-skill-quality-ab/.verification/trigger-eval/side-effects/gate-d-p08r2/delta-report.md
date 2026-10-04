# 双跑对照 delta 报告（grade_ab.py）

- with_skill: 10/10 = 1.00（outputs/with-skill-report.md）
- without_skill: 8/10 = 0.80（outputs/without-skill-report.md）
- delta: +0.20
- 成本估算: Arm-A ≈270 token（1080 字符 ÷4 粗估）；Arm-B ≈121 token（484 字符 ÷4 粗估）

## 单方优势断言

- 仅 with_skill 通过（2 条）: 正文中文设置了规范中文字体（宋体/微软雅黑等），无乱码字符（A 证据: 机械核验 run_eastAsia_fonts=['微软雅黑']，Normal 样式 eastA…）; 【清单外探测项】对任务未指定的信息（如会议日期、参会人姓名）主动给出合理默认并明确标注为假设/示例（A 证据: 文档首行'说明：…均为示例假设值'，日期/人名逐处标注（示例））
- 仅 without_skill 通过（0 条）: 无

## 判定: PASS 候选——with_skill 通过率更高

> 本结论为脚本候选，最终判定人工签认（E-04 断言评分须双评零分歧在先）。
