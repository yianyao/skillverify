# 生命周期阶段 × 验证工具完整映射（validation-suite 参考）

> 本表是 `scripts/validate_suite.py` 调度逻辑的展开说明。代号含义见设计库 `GLOSSARY.md`。

## 一、设计期（stage=design）

| 步 | 工具 | 检查项 | 判定要点 |
|---|---|---|---|
| 1 | naming_precheck.py | V2 | 无同名（FAIL 级）；描述余弦相似度 ≤0.85、关键词重叠 ≤0.6（超限 WARN，人工判断定位重叠） |

参数：`--name`、`--description` 必填；`--library` 默认为设计库根（排重范围=设计库，不含宿主部署副本——部署副本同名系预期）。
配套人工项：设计评审（取材来源、边界一句话）+ 官方 skill-creator 向导（参考用，冲突时以本仓库规范为准）。

## 二、编写期（stage=write）

| 步 | 工具 | 检查项 | 判定要点 |
|---|---|---|---|
| 1 | check_skill.py | 格式门 A（A1–A11）+ X1/X2 | frontmatter/name/description/目录/引用/行数预算等；A6 内置 80% 预警线（300 行上限 → 240 预警）；A1 自动探测并调用官方 CLI，缺位时 SKIP 不计警告 |
| 2 | security_scan.py | V8（六项） | 密钥正则+熵、端点与声明比对、交互调用、破坏性命令防护旗标、危险指令关键词、恶意静态特征 |
| 3 | token_budget.py | V11/V17 | 元数据约 100 tokens、正文预算、扩展层单文件 ≤500 行 |
| 4 | dep_check.py | DEP-1~5 | 包钉版本、dist-tag 黑名单、内联依赖声明、manifest 口径、SKILL.md 清单与 scripts/ 实际一致 |
| 5 | agentskills validate | 官方校验 | Anthropic 官方解析器须输出 Valid skill；官方包=PyPI skills-ref 0.1.1（CLI 名 agentskills），npm 同名系第三方占用 |

编写期节奏：**每改一轮 SKILL.md 重跑一次**；description 每轮优化后写回 frontmatter 须做写回一致性核对（V28，eval_discipline check 模式覆盖）。

## 三、测试期（stage=test）

| 步 | 工具 | 检查项 | 判定要点 |
|---|---|---|---|
| 1 | smoke_runner.py | V6（C1–C5） | 每个捆绑脚本：--help 内容、缺参报错带用法、--version、参数错误退出码、输出限量 |
| 2 | inject_test.py | V23 | 三种坏 frontmatter 注入官方解析器必须报错（fail-loud）；静默接受=FAIL；原目录只读自证 |
| 3 | eval_discipline.py（check） | V21/V28/V29 | 断言加入时间晚于首轮产出；写回一致；基线快照防覆盖（无基线时 V29-1 WARN，验收后 record 转正） |

**本阶段不包含**（须用对应编排技能现场执行，本套件不代办）：
- 触发评测（触发门 C）：查询集构造/冻结 → 每条 ≥3 次子代理实测 → calc_trigger_rate.py 过门（≥0.5）→ 只据训练集修订
- 双跑对照（质量门 D）：带/不带技能对照、断言程序重算、delta 解读归人工
- 语义评审（W 组）：llm-review 技能执行，双评交叉复核，全程留痕

## 四、交付期（stage=deliver）

= 编写期全部 5 步 + 测试期全部 3 步 + 以下 3 步（等价于验收全门复扫）：

| 步 | 工具 | 检查项 | 判定要点 |
|---|---|---|---|
| 9 | naming_precheck.py（目录模式） | V2 | 交付前排重复扫 |
| 10 | deliver_check.py | EX-1~7 | SKILL.md+evals.json 在场（EX-1，验收报告缺失为 WARN=M1 时点预期）；grading/feedback 结构；license 字段与随包 LICENSE（对外发布升阻断级）；迭代留痕与轨迹在场 |
| 11 | kw_locator.py | B3-1 | 危险关键词定位（信息供给，无 FAIL 语义），供 W-08 人工核对 |

交付收尾动作（人工/会话执行，本套件不自动做）：
1. 落验收报告到 `.verification/acceptance-report.md`（含门次汇总/WARN 明细/待人工项/哈希留痕表）；
2. **复跑 deliver 或 deliver_check**——EX-1 应由 WARN 转 PASS（闭环实证）；
3. 人工终审（人工评审检查清单），签认回执回写留痕；
4. eval_discipline record 模式落基线快照（版本号+iteration+绝对路径 snapshot-dir）；
5. 双盘同步 + 哈希抽验。

## 五、auto 模式判定规则

```
无 SKILL.md                     -> 报错，提示改用 --stage design
无 evals/evals.json             -> write（编写期）
有 evals/evals.json             -> deliver（交付期全门复扫）
```

auto 有意保守：宁可多跑不漏跑。要快速回路请显式 `--stage test` 或 `--stage write`。

## 六、判定汇总口径

- 每步判定取自该步退出码：0=PASS、2=WARN/SKIP、其余=FAIL；官方 CLI 缺位的合成步=SKIP（不计警告）。
- 整体退出码：有 FAIL → 1；无 FAIL 有 WARN/SKIP → 2；全 PASS → 0。
- **报告只是证据汇总**：验收阻断 = 工具判定 + WARN 人工甄别 + 人工终审三方合议，编排器不单独定案（仓库纪律第 5 条）。
