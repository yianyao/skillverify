# 质量门 D 运行输入记录（§7.2.4）

- 日期：2026-10-02
- 被测技能：agent-skill-llm-review v1.3（C:/Users/yianyao/.workbuddy/skills/agent-skill-llm-review，SKILL.md sha256 f368295e…）
- 评审靶子：gate-d/target-skill-demo/（scratch demo，植入 5 处缺陷：F1 泛化 description、F2 悬空 scripts/run.py 引用、F3 缺 compatibility、F4 明文假密钥、F5 虚构 logs/history.json 留痕声明；另含未植入真实缺陷 name 与目录名不一致）
- 任务 prompt（两臂相同）：对靶子技能做质量评审，指出所有不规范/风险问题，每条附证据引用并给修改建议
- 隔离方式（§7.2.3）：每臂一个全新子代理会话（路径 B 在环机制）；Arm-A 要求加载 agent-skill-llm-review 并按其工作流执行；Arm-B 禁止调用 Skill 工具
- 运行输入：
  - Arm-A（with_skill）：靶子路径；产出 outputs/with-skill-report.md + 靶子 .verification/ 留痕 14 条 + 双评包 5 套
  - Arm-B（without_skill）：靶子路径；产出 outputs/without-skill-report.md
- 断言评分（E-04）：assertions.txt（10 条）× with-skill-report，双评委（E-04-20261002-135904 A/B），零分歧 7/10
- 盲评（E-06）：--blind with-skill-report.md without-skill-report.md → blind-A/B（mapping.json 未向评委展示），双评委（E-06-20261002-135904 A/B），prefer 分歧（tie vs prefer A）→ 人工裁决点
- 增长性隔离判定（R-02）：gotchas-candidates.md（4 条沉淀候选）× SKILL.md，双评委（R-02-20261002-135905 A/B），零分歧（C/B/B/A-零操作）
- 判定：grading.json（with 7/10=0.7 vs without 6/10=0.6，delta +0.10，PASS）
