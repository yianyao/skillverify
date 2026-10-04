# 运行输入记录（§7.2.4）

- 日期：2026-10-02
- 编排技能（本流程执行依据）：agent-skill-quality-ab（经主会话 Skill 工具加载，调用记录见会话工具历史）
- 被验收目标技能（输入①）：agent-skill-llm-review（位于 C:\Users\yianyao\.workbuddy\skills\agent-skill-llm-review）
  - 说明：本次对照的问题是"装载该技能是否让同题工作更有收益"；quality-ab 作为编排层无法自证（其工作流即本对照本身），故靶定为同为用户自装工作技能的 llm-review
- 靶子任务（输入②）：评审一份植入 6 处缺陷的演示 SKILL.md（daily-standup-helper），输出结构化评审报告
  - 靶子文本：./target-demo-daily-standup-helper.SKILL.md（全文内联进两臂 prompt，两臂完全同题同文本）
  - 植入底稿：./ground-truth-planted-flaws.md（判官专用，未暴露给两臂）
- 断言清单（输入③）：./assertions.txt，10 条（含 1 条清单外探测项 A9），于双臂启动前冻结
- 隔离方式：
  - 每臂各派一个全新 `codebuddy -p` 子进程（v2.147.0，--output-format text），独立上下文，无 resume/continue
  - Arm-A（with_skill）：prompt 要求先经 Skill 工具加载 agent-skill-llm-review 并按其工作流评审
  - Arm-B（without_skill）：同 prompt + 明确禁止调用 Skill 工具，并加 --disallowedTools Skill 双重保险
  - 两臂互不知晓对方存在，产物分别落 outputs/with-skill-report.md 与 outputs/without-skill-report.md
- 产物位置（偏离说明）：技能默认要求落在 <目标技能>/.verification/gate-d/，但该目录下已存在既往运行产物，为避免覆盖，本轮全部产物落本独立目录 gate-d-run-standup/，此为已声明的偏离
- 防污染：双臂启动前对运行目录与用户技能目录做 sha256 快照（snapshot-before.sha256），轮后比对
- 评分：评委1=主会话，评委2=全新 codebuddy -p 进程（盲评：仅给断言清单+报告原文，不给臂标签、不给底稿中"对应断言"列），双评零分歧采信，分歧升级人工
