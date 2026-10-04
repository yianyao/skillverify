# 命名冲突预检（V2）

日期：2026-10-01    方法：技能库枚举 + 相邻技能 description 人工比对（precheck_name_conflict.py 未实现，人工兜底）

## 1. 同名检测（[M] 阻断项）
- 技能库（~/.workbuddy/skills/）：base、skill-authoring、agent-skill-llm-review
- 同名命中：**无**（仅目标自身）→ PASS

## 2. description 关键词重叠检测（WARN 项）
- vs skill-authoring（"新建/优化/重构/排障 skill、固化教训"）：重叠关键词 ≈ "skill/评审"；
  skill-authoring 管"编写期规范"，本技能管"对既有技能执行 L 类评审"，用途不重叠 → 低于 0.6 阈值，无告警
- vs base（业务流程工厂）：无实质重叠 → 无告警

## 3. 处置结论
无同名 [M] 命中；无 ≥0.6 重叠 WARN → 通过，允许立项。
