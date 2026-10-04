# V6 脚本冒烟报告（smoke_runner.py）

- 待测脚本: 5 个（host_compat.py, detect_stage.py, plan_dual_review.py, record_review.py, summarize_reviews.py）
- 口径: 机械项脚本判定；--help 内容正确性（语义）留待 W-14；执行形态记 S，验证目标记 K（V6）
- 总结论: WARN（有告警，人工书面评估）

| 脚本 | 检查项 | 结论 | 证据 |
|---|---|---|---|
| host_compat.py | C1 --help 可运行 | PASS | exit=0, stdout=有｜usage: host_compat.py [-h] [--skill-dir SKILL_DIR] [--json] ⏎  ⏎ K 类在环试点跨宿主兼容性检查入口 ⏎  ⏎ options: ⏎   -h, --help         … |
| host_compat.py | C3 非 TTY 不挂起 | PASS | --help 于 15s 内完成 |
| host_compat.py | C5 --help 幂等 | PASS | 两次 stdout 一致 |
| host_compat.py | C2 无参调用报错带用法 | WARN | exit=2, 报错未含用法提示｜# host_compat 兼容性检查报告 ⏎ 宿主: WorkBuddy ⏎  ⏎   [PASS] Python 3.13.14 >= 3.10 ⏎   [PASS] 宿主识别: WorkBuddy ⏎   [PASS] WorkBud… |
| host_compat.py | C4 dry-run 适用性 | PASS | 无 dry-run 标志（不适用，如技能约定适用则人工复核） |
| detect_stage.py | C1 --help 可运行 | PASS | exit=0, stdout=有｜detect_stage.py — 检测目标技能的生命周期产物，推荐应跑的 LLM 评审提示词组（advisory，不阻断）。 ⏎  ⏎ 用法: python detect_stage.py <skill_dir> ⏎ 标志: 无（仅一个位… |
| detect_stage.py | C3 非 TTY 不挂起 | PASS | --help 于 15s 内完成 |
| detect_stage.py | C5 --help 幂等 | PASS | 两次 stdout 一致 |
| detect_stage.py | C2 无参调用报错带用法 | PASS | exit=1, 报错含用法提示｜错误: 缺少参数。 ⏎ 用法: detect_stage.py <skill_dir> ⏎ 下一步: 传入目标技能目录后重试。 |
| detect_stage.py | C4 dry-run 适用性 | PASS | 无 dry-run 标志（不适用，如技能约定适用则人工复核） |
| plan_dual_review.py | C1 --help 可运行 | PASS | exit=0, stdout=有｜usage: plan_dual_review.py [-h] --skill-dir SKILL_DIR --prompt-id PROMPT_ID ⏎                            [--inputs [INPU… |
| plan_dual_review.py | C3 非 TTY 不挂起 | PASS | --help 于 15s 内完成 |
| plan_dual_review.py | C5 --help 幂等 | PASS | 两次 stdout 一致 |
| plan_dual_review.py | C2 无参调用报错带用法 | PASS | exit=2, 报错含用法提示｜usage: plan_dual_review.py [-h] --skill-dir SKILL_DIR --prompt-id PROMPT_ID ⏎                            [--inputs [INPU… |
| plan_dual_review.py | C4 dry-run 适用性 | PASS | 无 dry-run 标志（不适用，如技能约定适用则人工复核） |
| record_review.py | C1 --help 可运行 | PASS | exit=0, stdout=有｜usage: record_review.py [-h] --skill-dir SKILL_DIR --prompt-id PROMPT_ID ⏎                         --model MODEL --verdi… |
| record_review.py | C3 非 TTY 不挂起 | PASS | --help 于 15s 内完成 |
| record_review.py | C5 --help 幂等 | PASS | 两次 stdout 一致 |
| record_review.py | C2 无参调用报错带用法 | PASS | exit=2, 报错含用法提示｜usage: record_review.py [-h] --skill-dir SKILL_DIR --prompt-id PROMPT_ID ⏎                         --model MODEL --verdi… |
| record_review.py | C4 dry-run 适用性 | PASS | 无 dry-run 标志（不适用，如技能约定适用则人工复核） |
| summarize_reviews.py | C1 --help 可运行 | PASS | exit=0, stdout=有｜summarize_reviews.py — 汇总 llm-review-log.md：判定统计、双评缺口、分歧项。 ⏎  ⏎ 用法: python summarize_reviews.py <skill_dir> ⏎ 标志: 无（仅一个位… |
| summarize_reviews.py | C3 非 TTY 不挂起 | PASS | --help 于 15s 内完成 |
| summarize_reviews.py | C5 --help 幂等 | PASS | 两次 stdout 一致 |
| summarize_reviews.py | C2 无参调用报错带用法 | PASS | exit=1, 报错含用法提示｜错误: 缺少参数。 ⏎ 用法: summarize_reviews.py <skill_dir> ⏎ 下一步: 传入目标技能目录后重试。 |
| summarize_reviews.py | C4 dry-run 适用性 | PASS | 无 dry-run 标志（不适用，如技能约定适用则人工复核） |

> 本报告为机械门结果；放行与否由人工签认，[M] 级 FAIL 不得自动放行。
