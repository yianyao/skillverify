# agent-skill-llm-review 版本变更日志（Changelog）

> 依据：技能包 SKILL.md 版本行（D 盘归档基线 `D:\sData\specSkill\agent-skill-llm-review\SKILL.md`）与 `.verification/design.md` 纠正记录整理。
> 当前版本：v1.2（2026-10-01）。本文件为整理稿，落盘后如需纳入技能包/归档，请按同步纪律 sha256 校验后同步 D 盘。

## [v1.2] — 2026-10-01

### 第二轮评审修复

- `detect_stage.py` 补 M 键，修复 KeyError
- `SKILL.md` §7 退出码描述与脚本行为同步
- 盲评标签改为「版本 A/B」，与提示词清单 E-06 口径对齐
- 留痕输出转义半角竖线，防止破坏 V12 六列表格式
- `assets/llm-review-log-template.md` 补双评记录示例

### 第三轮起历轮同步修复

- `references/dual-review-rules.md` 与脚本 docstring 的盲评标签对齐
- `detect_stage.py` M 行 pid 空值显示改为「（无）」
- `evals.json` 版本号与正文同步
- `plan_dual_review.py` 增加 `--skill-dir` 存在性校验；盲评模式增加同文件判重（realpath）
- `record_review.py` HEADER 冒号对齐与换行防护
- 各脚本增加 prompt-id 格式校验

## [v1.1] — 2026-10-01

### 采纳技能自查评审结论

- 双评缺口判定收紧：须 ≥2 条记录才构成缺口
- 留痕记录携带任务包编号（`--package A/B`）
- `detect_stage.py` 退出码区分「检测完成」与「用法错误/目录不存在」，供编排器识别误用

## [v1.0] — 2026-10-01

- 首版：按《Agent-Skill 生命周期验证方案》v1.3 的 L 类条目与 V12 双评/留痕规则建成，含 29 条冻结提示词（D/W/E/R 四组）、4 个 scripts、双评任务包与盲评能力。

---

## 附：v1.2 之后的验证活动（非技能改动，未触发版本号变化）

- 2026-10-02 触发门 C 全量实测：20 条 × 3 轮 = 60 次子代理运行，18/20 过门；train 12/12 全过 → description 维持不动，v1.2 即定稿候选。
- 已知局限（留 v2 裁决）：触发子句「列举式触发词 + 无域限定」——P09 该触发不触发（调优咨询场景未声明），N09 不该触发误触发（"盲评"泛词裸命中）。
- 遗留非缺陷建议：`record_review.py` 可补 `--skill-dir` isdir 校验（工具冻结期不处理，解冻时做）。
