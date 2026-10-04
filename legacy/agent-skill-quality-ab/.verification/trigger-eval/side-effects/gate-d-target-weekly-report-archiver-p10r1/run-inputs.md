# run-inputs.md — 运行输入记录（§7.2.4）

- 编排技能：agent-skill-quality-ab v1.2（本会话经 Skill 工具加载，未以其他方式读取其目录）
- 目标技能（被验收对象）：weekly-report-archiver（demo，V4-r1r2）
  - SKILL.md sha256: 505cdfc3a703ccd5f8b295d5e8eb0ff234e632252026fe6874de840fd00ced23
  - 位置: C:\Users\yianyao\.workbuddy\skills\agent-skill-llm-review\.verification\trigger-gate-c\side-effects\V4-r1r2-weekly-report-archiver-skill\SKILL.md
- 靶子任务：整理 inputs/weekly-reports.md 原始周报（6 条提交、5 人），产出索引/统计/去重/摘要表
  - 植入问题（不告知两臂）：提交1与提交2内容重复（张三）；提交3无署名；提交1/2 与其余条目日期格式不一致
- 断言清单：assertions.txt 共 8 条（A1–A6 核心价值项 + X1–X2 清单外探测项），执行前冻结，text 均唯一
- 隔离方式：两臂各为一个全新 `codebuddy -p` 进程（独立上下文，禁 resume）；Arm-B prompt 显式禁止 Skill 工具；评委双盲（甲乙顺序对调）
- 产出位置：outputs/with-skill-report.md、outputs/without-skill-report.md、judge1.json、judge2.json、grading.json、delta-report.md
- 防污染：run-arms.ps1 运行前后对 inputs/prompts/assertions.txt 做 sha256 快照比对，不一致即作废
- 执行状态：**未执行** —— 本会话无 codebuddy CLI、无子代理工具，双臂无法干净隔离，按铁律不以单上下文代跑
