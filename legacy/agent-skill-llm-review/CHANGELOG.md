# CHANGELOG — agent-skill-llm-review

> 本文件承载版本变更历史。SKILL.md 正文仅保留单行版本指针（防膨胀纪律：SKILL.md 只留执行必需内容，历史细节不入运行时上下文）。

## v1.4（2026-10-03）

- **description 可读性自足化**（frontmatter，人工采纳 iteration-1/description-revision-proposal.md）：能力自述去代号依赖——"（L 类）"删除、"D/W/E/R 生命周期阶段"改四阶段中文全称、"记录 V12 留痕"改"评审过程与结论全程落盘留痕"、"跑 W 组语义检查"改"跑语义评审（即 W 组/L 类评审）"（代号降为括注触发关键词）、"版本 A/B 对比"改"新旧版本 A/B 对比"；触发词区与负向边界声明原样保留（代号在触发区有召回正贡献）。
- 动机：发布后外部读者第一眼可懂；体系内用户触发不受影响（GLOSSARY.md 术语总表同日落库）。
- 验证：check_skill A 门复跑 PASS；V28-1 写回一致性 PASS（--description-text 选定版本）；门 C 实测见 .verification/trigger-gate-c/ 本轮留痕。

## v1.3（2026-10-02）

- **触发子句修订**（frontmatter description）：依据 train 失败 T-P14 0/3（过触发诊断域未声明，互证 C4 G-P03 0/3、validation P09 0/3）与人工授权（N09"做盲评"泛词 3/3 误触发）：
  - 触发词全面加域锚定："评审技能"→"评审 Agent Skill"、"做盲评"→"对技能产物做盲评（版本 A/B 对比）"、"诊断轨迹"→"诊断技能执行轨迹"、"归纳 Gotchas"→"归纳技能评审 Gotchas"；
  - 新增声明："诊断技能过触发或漏触发、裁决技能 description 用词与触发边界"；
  - 新增负向边界："仅面向 Agent Skill 质量验证场景：文章、文案、简历、合同、标书等一般内容评审与盲评不适用"。
- 门 C 回归（10 条 × 3 轮）：7/10 PASS；负例 5/5 全过（N09 修复生效），P01/F-P01 仍 3/3 未受抑制。
- 已知局限（人工裁决 2026-10-02）：对"抽象咨询口吻的触发调优问题"召回偏低（P09 1/3、T-P14 0/3、G-P03 0/3），以具体化措辞补偿；v1.4 不再迭代。

## v1.2（2026-10-01）

- 第二轮评审修复：detect_stage 补 M 键修 KeyError、SKILL.md §7 退出码描述同步、盲评标签改为"版本 A/B"与 E-06 对齐、留痕转义半角竖线、模板补双评记录示例。
- 第三轮起历轮同步修复：dual-review-rules/docstring 盲评标签对齐、detect_stage M 行 pid 改"（无）"、evals.json 版本同步、plan_dual_review 加 --skill-dir 校验与盲评同文件判重（realpath）、record_review HEADER 冒号对齐与换行防护、prompt-id 格式校验。

## v1.1（2026-10-01）

- 采纳技能自查评审：双评缺口须 ≥2 条记录、留痕带包编号、detect_stage 退出码区分误用。
