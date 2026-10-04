# V6 脚本冒烟报告（smoke_runner.py）

- 待测脚本: 1 个（check_skill.py）
- 口径: 机械项脚本判定；--help 内容正确性（语义）留待 W-14；执行形态记 S，验证目标记 K（V6）
- 总结论: PASS

| 脚本 | 检查项 | 结论 | 证据 |
|---|---|---|---|
| check_skill.py | C1 --help 可运行 | PASS | exit=0, stdout=有｜usage: check_skill.py [-h] [--out OUT] [--lines LINES] skill_dir ⏎  ⏎ Agent Skill 格式门 A 权威校验器（A1–A11 + 附加机械检） ⏎  ⏎ posit… |
| check_skill.py | C3 非 TTY 不挂起 | PASS | --help 于 15s 内完成 |
| check_skill.py | C5 --help 幂等 | PASS | 两次 stdout 一致 |
| check_skill.py | C2 无参调用报错带用法 | PASS | exit=2, 报错含用法提示｜usage: check_skill.py [-h] [--out OUT] [--lines LINES] skill_dir ⏎ check_skill.py: error: the following arguments are re… |
| check_skill.py | C4 dry-run 适用性 | PASS | 无 dry-run 标志（不适用，如技能约定适用则人工复核） |

> 本报告为机械门结果；放行与否由人工签认，[M] 级 FAIL 不得自动放行。
