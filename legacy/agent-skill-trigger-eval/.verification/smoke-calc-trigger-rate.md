# V6 脚本冒烟报告（smoke_runner.py）

- 待测脚本: 1 个（calc_trigger_rate.py）
- 口径: 机械项脚本判定；--help 内容正确性（语义）留待 W-14；执行形态记 S，验证目标记 K（V6）
- 总结论: PASS

| 脚本 | 检查项 | 结论 | 证据 |
|---|---|---|---|
| calc_trigger_rate.py | C1 --help 可运行 | PASS | exit=0, stdout=有｜usage: calc_trigger_rate.py [-h] --runs RUNS --queryset QUERYSET [--out OUT] ⏎                             [--min-runs M… |
| calc_trigger_rate.py | C3 非 TTY 不挂起 | PASS | --help 于 15s 内完成 |
| calc_trigger_rate.py | C5 --help 幂等 | PASS | 两次 stdout 一致 |
| calc_trigger_rate.py | C2 无参调用报错带用法 | PASS | exit=2, 报错含用法提示｜usage: calc_trigger_rate.py [-h] --runs RUNS --queryset QUERYSET [--out OUT] ⏎                             [--min-runs M… |
| calc_trigger_rate.py | C4 dry-run 适用性 | PASS | 无 dry-run 标志（不适用，如技能约定适用则人工复核） |

> 本报告为机械门结果；放行与否由人工签认，[M] 级 FAIL 不得自动放行。
