# 生命周期验证报告（deliver 阶段）

- 执行者: agent-skill-validation-suite v1.0（validate_suite.py）
- 时间: 2026-10-03 14:44:29 ｜ 对象: D:\sData\specSkill\agent-skill-validation-suite
- 阶段判定: 显式指定；官方 CLI: PATH 命中 agentskills
- 口径: 本报告为工具判定汇总,供人工复核;验收阻断须结合人工终审(仓库纪律:编排器不得仅凭退出码作验收阻断)。

| # | 步骤 | 退出码 | 判定 |
|---|---|---|---|
| 1 | 编写期·格式门 A（check_skill：frontmatter/目录/预算预警等 11 组） | 0 | PASS |
| 2 | 编写期·安全扫描（V8：密钥/端点/交互/危险操作六项） | 0 | PASS |
| 3 | 编写期·上下文预算门（V11/V17：token/行数预算） | 0 | PASS |
| 4 | 编写期·依赖检测（DEP-1~5：钉版本/内联声明） | 0 | PASS |
| 5 | 编写期·官方校验（agentskills validate，Anthropic 官方解析器） | 0 | PASS |
| 6 | 测试期·脚本冒烟（V6：--help/缺参/版本/退出码/限量） | 0 | PASS |
| 7 | 测试期·加载注入（V23：坏 frontmatter 须 fail-loud） | 0 | PASS |
| 8 | 测试期·评测纪律 check（V21 先写后测 / V28 写回一致 / V29 基线） | 2 | WARN/SKIP |
| 9 | 交付期·命名预检复扫（V2） | 0 | PASS |
| 10 | 交付期·交付物检查（EX-1~7：验收报告/license/留痕在场） | 2 | WARN/SKIP |
| 11 | 交付期·危险关键词定位（B3-1，信息供给非门禁） | 0 | PASS |

## 各步输出尾部

### 编写期·格式门 A（check_skill：frontmatter/目录/预算预警等 11 组）

```
| A3 | name 正则/长度/与目录一致 | PASS | name=agent-skill-validation-suite，与目录一致 |
| A4 | description 长度 1-1024 非空 | PASS | 长度 272 |
| A5 | compatibility 长度 1-500（若存在） | PASS | 未声明（允许缺省） |
| A6 | SKILL.md 行数 <300 | PASS | 69 行（项目收紧口径） |
| A7 | 换行符为 LF | PASS | LF only |
| A8 | 引用为相对路径且仅一层 | PASS | 3 个相对引用全部合规；存在性核对: 3/3 全部存在 |
| A9 | 脚本无交互式输入 | PASS | 1 个脚本检索 8 类模式零命中 |
| A10 | 脚本 --help 可运行 | PASS | 1 个脚本全部 exit=0 且有输出（内容正确性→W-14） |
| A11 | frontmatter 可解析且含 name/description | PASS | keys=['description', 'name'] |
| X1 | UTF-8 无 BOM（附加） | INFO | 无 BOM |
| X2 | evals.json 可解析（附加） | INFO | queries=8 条 |
> 判定统计: 11/11 PASS；A8 触发条件为语义项留 H，--help 内容正确性留 W-14。
```

### 编写期·安全扫描（V8：密钥/端点/交互/危险操作六项）

```
- 扫描覆盖: 4 文件（跳过二进制 0、超限 0、符号链接 0；排除 .git, .venv, .verification, __pycache__, node_modules, venv）
- 总结论: PASS
| 项 | 检查内容 | 结论 | 证据 |
|---|---|---|---|
| V8-1 | secret 正则库零命中（§9.6） | PASS | （8 类格式 × 4 文件） |
| V8-2 | 熵检测零命中（§9.6 启发式） | PASS | 阈值: 长度>=20 且熵>= 4.5（hex 哈希天然低于阈值） |
| V8-3 | 外部端点与声明比对（§9.2 静态） | PASS | 未发现外部 URL |
| V8-4 | 多语言交互调用零命中（§8.3.1） | PASS | 8 类模式 × 4 文件零命中（扫描面含全包，补强 A9 的 scripts/*.py 限界） |
| V8-5 | 破坏性关键词有确认防护（§8.3.10） | PASS | 代码文件零命中破坏性关键词（或均有防护） |
| V8-6 | 危险指令关键词零命中（§9.8 关键词部分） | PASS | 全文件零命中 |
| COV | 扫描覆盖 | INFO | 扫描 4 个文本文件; 跳过二进制扩展名 0、超 2MB 0、符号链接 0; 排除目录 .git, .venv, .verification, __pycache__, node_modules, venv |
> 判定统计: 6/6 PASS。语义审计（§9.1 恶意逻辑、§9.2 用途一致性、§9.8 完整语义）仍由 W-L 评审 + H 终审承担，本工具零命中不豁免语义审计。
```

### 编写期·上下文预算门（V11/V17：token/行数预算）

```
- 技能: agent-skill-validation-suite（D:\sData\specSkill\agent-skill-validation-suite）
- 工具版本: v1.0.1
- 口径: V11 token 计数（chars/4 保守兜底，宿主 tokenizer 缺席时的固定实现）；V17 预算门——正文 <5000 tokens（官方 [M]）/元数据 ≤100 tokens（项目收紧）/扩展层单文件 ≤500 行（项目收紧）
- 总结论: PASS
| 项 | 检查内容 | 结论 | 证据 |
|---|---|---|---|
| V11-1 | SKILL.md 正文 token <5000（官方 [M]，V11 chars/4 口径） | PASS | 正文 2628 字符 ≈ 657 tokens〔CJK 占比 39%，chars/4 口径可能低估实际 token，建议人工关注〕 |
| V17-1 | 元数据 token ≤100（项目级收紧，官方 [S]） | PASS | name+description 301 字符 ≈ 76 tokens〔CJK 占比 68%，chars/4 口径可能低估实际 token，建议人工关注〕 |
| V17-2 | 扩展层单文件 ≤500 行（项目级收紧，官方 [P]） | PASS | 扩展层 1 个文件全部达标 |
| V17-3 | SKILL.md 行数（<300 行判定归 check_skill.py A6） | INFO | 当前 69 行（≥240 触发 V27 预警线，≥300 由 A6 阻断） |
| COV | 扫描覆盖 | INFO | 扩展层文件 1 个 |
> 判定统计: 3/3 PASS。SKILL.md <300 行由 check_skill.py A6 承载；预算超限的处置（拆分/外移）由 V26/V27 与人工裁决承担，本工具不自动改写。
```

### 编写期·依赖检测（DEP-1~5：钉版本/内联声明）

```
- 工具版本: v1.0.1
- 口径: §8.1.2 版本固定（[M]）/§8.2.1 内联声明（[M]）/§8.2.2 禁 manifest（[M]）/§8.2.3+§8.2.5 版本说明符（[S]/[P]）/§8.2.4 脚本清单完备（[M]）；SKIP 不计警告（须人工留痕佐证，不豁免上游条款）
- 总结论: PASS（SKIP 2 行）
| 项 | 检查内容 | 结论 | 证据 |
|---|---|---|---|
| DEP-1 | 外部工具调用版本固定（pkg@1.2.3，§8.1.2） | SKIP | 未发现运行器/包管理调用（npx/bunx/uvx/pipx/pip/uv/deno/go run）——条款不适用 |
| DEP-2 | 捆绑脚本内联依赖声明（§8.2.1） | PASS | 1 个代码文件第三方依赖均已内联声明或无第三方依赖 |
| DEP-3 | 禁独立 manifest / 安装步骤（§8.2.2） | PASS | 技能树内未发现独立依赖 manifest |
| DEP-4 | 依赖版本说明符固定（§8.2.3/§8.2.5） | SKIP | 无内联依赖声明可核（无 PEP 723 块/Deno-Bun 版本化导入/gem 声明）——条款不适用 |
| DEP-5 | 脚本清单完备（scripts/ 实际文件 ⊆ SKILL.md 清单，§8.2.4） | PASS | scripts/ 1 个文件全部在 SKILL.md 列出；'用途与调用方式'语义归 H |
| COV | 扫描覆盖 | INFO | DEP-1/2/3/4/5 SKILL.md+scripts/+技能树 manifest |
> 判定统计: 3/3 PASS。运行器与环境匹配（§8.1.5–§8.1.6/V22）与依赖实际可解析属 O 实测域（M1-9），不在本工具范围；§8.2.6 环境干扰（Gemfile/node_modules 在场时自包含机制可能失效）须真实挂载环境复测。
```

### 编写期·官方校验（agentskills validate，Anthropic 官方解析器）

```
Valid skill: D:\sData\specSkill\agent-skill-validation-suite
```

### 测试期·脚本冒烟（V6：--help/缺参/版本/退出码/限量）

```
# V6 脚本冒烟报告（smoke_runner.py v1.1）
- 待测脚本: 1 个（validate_suite.py）
- 口径: 机械项脚本判定；--help 内容正确性（语义）留待 W-14；执行形态记 S，验证目标记 K（V6）
- 总结论: PASS
| 脚本 | 检查项 | 结论 | 证据 |
|---|---|---|---|
| validate_suite.py | C1 --help 可运行 | PASS | exit=0, stdout=有｜usage: validate_suite.py [-h] --stage {design,write,test,deliver,auto} ⏎                          [--skill-dir SKILL_DIR… |
| validate_suite.py | C3 非 TTY 不挂起 | PASS | --help 于 15s 内完成 |
| validate_suite.py | C5 --help 幂等 | PASS | 两次 stdout 一致 |
| validate_suite.py | C2 无参调用报错带用法 | PASS | exit=1, 报错含用法提示｜FAIL: 参数错误: the following arguments are required: --stage ⏎ 用法: python validate_suite.py --stage <design｜write｜test｜deli… |
| validate_suite.py | C4 dry-run 适用性 | PASS | 无 dry-run 标志（不适用，如技能约定适用则人工复核） |
> 本报告为机械门结果；放行与否由人工签认，[M] 级 FAIL 不得自动放行。
```

### 测试期·加载注入（V23：坏 frontmatter 须 fail-loud）

```
# V23 fail-loud 注入测试报告（inject_test.py v1.0.3）
- 技能: D:\sData\specSkill\agent-skill-validation-suite
- 解析器: C:\Users\yianyao\.workbuddy\binaries\python\envs\default\Scripts\agentskills.EXE validate
- 汇总: 5 PASS / 0 FAIL / 0 WARN+SKIP
| 项 | 内容 | 级别 | 证据 |
|---|---|---|---|
| V23-0 | 对照组（未修改副本应通过） | PASS | 解析器对未修改副本零退出 |
| V23-1 | V23-1（注入后应报错） | PASS | 宿主 fail-loud：exit=1（Validation failed for C:\Users\yianyao\AppData\Local\Temp\v23_xpwq_wr3\agent-skill-validation-suite:…） |
| V23-2 | V23-2（注入后应报错） | PASS | 宿主 fail-loud：exit=1（Validation failed for C:\Users\yianyao\AppData\Local\Temp\v23_reaoro53\agent-skill-validation-suite:…） |
| V23-3 | V23-3（注入后应报错） | PASS | 宿主 fail-loud：exit=1（Validation failed for C:\Users\yianyao\AppData\Local\Temp\v23_qdy98uo5\agent-skill-validation-suite:…） |
| V23-4 | 原目录未触碰（SHA256 全清单） | PASS | 5 文件执行前后哈希一致 |
```

### 测试期·评测纪律 check（V21 先写后测 / V28 写回一致 / V29 基线）

```
- 模式: check；未提供评测工作区（V21-2 相关行 SKIP）
- 口径: V21 断言时机（§7.1.5/§7.1.6，[M]，语义半归 H）/V28 写回一致性（§6.5.7，[S]）/V29 iteration 基线（§15.4，[S]）；SKIP 不计警告（须人工留痕佐证，不豁免上游条款）
- 总结论: WARN（需人工复核）（SKIP 3 行）
| 项 | 检查内容 | 结论 | 证据 |
|---|---|---|---|
| V21-1 | 评测集在场（evals/evals.json）——用例数记录 | INFO | 形态 queries、当前 8 条。初始 2–3 条为流程纪律：终态数量无法机械验证初始值，是否由 2–3 条起步须经 run-log 留痕佐证（语义归 H） |
| V21-2 | 断言添加时机（晚于首轮产出，§7.1.6） | SKIP | evals.json 为 queries 形态（非 §7 断言评测集）——断言时机条款不适用；质量评估是否遵守断言时机由 runs.md/留痕人工佐证（H） |
| V28-1 | description 写回一致性（选定版本 vs 落盘，§6.5.7） | SKIP | 未提供 --description-final/--description-text——未做 description 优化轮属常态；若已做选定写回，须补依据文件复跑或人工核对留痕 |
| V29-1 | iteration 基线在场（.iteration-baseline，§15.4） | WARN | 基线文件缺失——已经过 E 阶段验收的技能须 record 补落；从未进入验收属常态（人工判断本技能所处阶段，不假 PASS 亦不误阻断） |
| V29-2 | 防覆盖比对（基线 snapshot vs 现状） | SKIP | 无基线可比对 |
| COV | 扫描覆盖 | INFO | V21-1/2 评测产物、V28 写回依据、V29 基线 |
> 判定统计: 0/0 PASS。初始用例数与'未提前定义 PASS/FAIL'属流程语义（H）；本工具 FAIL 不得自动改写评测产物或基线。
```

### 交付期·命名预检复扫（V2）

```
- 目标: agent-skill-validation-suite
- 工具版本: v1.0.3
- 口径: V2（[M] 设计期）——同名 name 检索（§1 第 2 条）/description 相似度（余弦 >0.85 或关键词重叠 >0.6 告警，阈值可调）
- 库: D:\sData\specSkill
- 总结论: PASS
| 项 | 检查内容 | 结论 | 证据 |
|---|---|---|---|
| V2-1 | 同名 name / 目录名冲突（§1 第 2 条） | PASS | 库内 3 个已解析技能 + 目录名检索零冲突 |
| V2-2 | description 余弦相似度 ≤0.85（V2 阈值，可调） | PASS | top-1 **agent-skill-llm-review=0.415**（判定取第 1，超阈值即告警）；前 3 名: agent-skill-llm-review=0.415; agent-skill-quality-ab=0.262; agent-skill-trigger-eval=0.204 |
| V2-3 | description 关键词重叠(Jaccard) ≤0.6（V2 阈值，可调） | PASS | top-1 **agent-skill-llm-review=0.177**（判定取第 1，超阈值即告警）；前 3 名: agent-skill-llm-review=0.177; agent-skill-quality-ab=0.069; agent-skill-trigger-eval=0.053 |
| COV | 扫描覆盖 | INFO | 库 1 个（不可达 0）、可比技能 3 个; 跳过非技能子目录 1、name 不可解析 0、排除目录 ['.git', '.venv', '.verification', '__pycache__', 'node_modules', 'venv'] |
> 判定统计: 3/3 PASS。相似度告警=人工复核入口；范围定位的实质重叠判断由 V1 设计评审（H）承担，本工具零命中不豁免 V1。
```

### 交付期·交付物检查（EX-1~7：验收报告/license/留痕在场）

```
- 总结论: WARN（需人工复核）（SKIP 3 行）
| 项 | 检查内容 | 结论 | 证据 |
|---|---|---|---|
| EX-1 | 交付物存在性（SKILL.md + evals.json + 验收报告，§15.7/M1-7） | WARN | .verification/acceptance-report.md 未出——M1 终检时点项（W/E 阶段预期缺失，进入 M1 前须补齐；SKILL.md+evals.json 已在场） |
| EX-2 | feedback.json 落盘与结构（text/passed/evidence，§7.7.4/E3-2） | SKIP | 技能树内未产出 feedback.json——E3 人工复核运行产物（W 阶段预期缺失，SKIP 不计警告；进入 E3 后须落盘并复检） |
| EX-3 | grading.json schema（text/passed/evidence + summary 四键，§7.2.6） | SKIP | 技能树内未产出 grading.json——测试期运行产物（未进入测试工作区属预期，SKIP 不计警告） |
| EX-4 | license 许可合规初筛（§2.4.1–2.4.2/V15） | SKIP | frontmatter 无 license 字段且无随包 LICENSE 文件——内部使用不适用（对外交付时 V15 升 [M]：须声明许可、完整条款随包、第三方素材许可留档） |
| EX-5 | 反向测试记录存在性（§5.1.3/B1-1） | PASS | .verification/ 内 1 个文件含"反向测试"留痕（如 .verification/deliver-precheck.md）——记录内容质量归 L/H（B1-4） |
| EX-6 | 执行→修订闭环记录（§5.1.6/B1-2） | WARN | .verification/ 下未见 iteration-N 目录（含文件）——真实执行→修订闭环留痕人工确认（K 流程可能在案他处） |
| EX-7 | 执行轨迹分析记录（§5.1.9/B1-3） | PASS | .verification/ 内 1 个文件含"轨迹"留痕（如 .verification/deliver-precheck.md）——轨迹三类缺陷归因质量归 L/H |
| COV | 扫描覆盖 | INFO | EX-1~7 SKILL.md+evals.json+验收报告+feedback/grading schema+license+B1 留档（.verification/ 全树） |
> 判定统计: 2/2 PASS。B1 三类记录的关键词初筛局限（留档可能在技能树外素材档案）与 feedback/grading 为测试期运行产物（未产出属预期）均已写入证据；记录内容质量（B1-4 终审、E3-1 逐用例复核、反馈具体性、V15 第三方素材合规）归 L/H，不在本工具范围。
```

### 交付期·危险关键词定位（B3-1，信息供给非门禁）

```
# B3-1 关键词定位报告（kw_locator.py v1.0.1）
- 技能: D:\sData\specSkill\agent-skill-validation-suite
- 定位方式: S 定位器（kw_locator v1.0.1，词表复用 security_scan V8-5 / §8.3.10 示例清单）
- 扫描: 4 文本文件（代码 1）
## 定位段落
**定位段落为空**——全域零命中破坏性关键词。
W-08 无需降级（无目标），或按降级句口径声明"定位方式：S 定位器（零命中）"。
## 结论
命中 0 处。
```

## 判定统计

- FAIL 步: 0 ｜ WARN/SKIP 步: 2 ｜ 总步: 11
- 下一步: FAIL 步按报告证据修复后重跑;WARN 步逐条人工甄别;交付阶段全过后按 验证操作总说明书.md §4 落验收报告并人工终审。
