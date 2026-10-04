# V23 fail-loud 注入测试报告（inject_test.py v1.0.3）

- 技能: agent-skill-trigger-eval
- 解析器: C:\Users\yianyao\.workbuddy\binaries\python\envs\default\Scripts\agentskills.EXE validate
- 汇总: 5 PASS / 0 FAIL / 0 WARN+SKIP

| 项 | 内容 | 级别 | 证据 |
|---|---|---|---|
| V23-0 | 对照组（未修改副本应通过） | PASS | 解析器对未修改副本零退出 |
| V23-1 | V23-1（注入后应报错） | PASS | 宿主 fail-loud：exit=1（Validation failed for C:\Users\yianyao\AppData\Local\Temp\v23_egmdmz4p\agent-skill-trigger-eval: ⏎  …） |
| V23-2 | V23-2（注入后应报错） | PASS | 宿主 fail-loud：exit=1（Validation failed for C:\Users\yianyao\AppData\Local\Temp\v23_2pisedai\agent-skill-trigger-eval: ⏎  …） |
| V23-3 | V23-3（注入后应报错） | PASS | 宿主 fail-loud：exit=1（Validation failed for C:\Users\yianyao\AppData\Local\Temp\v23_lyhcd77y\agent-skill-trigger-eval: ⏎  …） |
| V23-4 | 原目录未触碰（SHA256 全清单） | PASS | 38 文件执行前后哈希一致 |
