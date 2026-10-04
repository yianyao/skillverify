# tools 操作手册

> 说明文档见 [README.md](README.md)。本文档回答三个问题：**何时执行、执行目的、执行影响**。

---

## host_compat.py

### 何时执行

1. **任何 K 类在环试点启动之前（第一步）**——路径裁决（A/B/C）决定试点怎么做，不先跑它就动手属于流程违规
2. **首次在新宿主环境使用时**（含接入 DeepSeek Harness / Pi / ZCode / TRAE 等真实宿主）——HOSTS 表多数约定未经实测，必须以实际运行结果回填
3. **排查路径裁决疑问时**——"为什么走了 C""为什么提示待确认"，用 `--json` 看结构化依据

### 执行目的

输出当前环境的试点能力结论：

- **A（全自动）**：PATH 上发现 agent CLI，可用子进程逐条新会话跑查询
- **B（半自动）**：宿主会话内派发子代理（每个子代理 = 独立新会话）；标注"待确认"时见下文"结果解读"
- **C（降级 runbook）**：人工逐条新开会话投喂查询

同时体检：Python >= 3.10、已知技能库目录、agent CLI 可达性、被试点技能 SKILL.md frontmatter。

### 执行影响

- **只读操作**：不写任何文件、不联网、不运行被试点技能的任何业务功能，唯一输出是 stdout
- **安全等级：可在任何环境随意运行**，无破坏性
- 退出码：`0`=全 PASS；`1`=有 FAIL；`2`=仅 WARN（WARN 不阻断，但人工需书面知悉）

### 命令示例

```bash
# 标准用法：试点前检查（含被试点技能体检）
python host_compat.py --skill-dir <被试点技能目录>

# 未被自动识别的宿主：显式覆盖（注意：任意字符串都会触发 B，须确认该宿主真支持子代理编排）
python host_compat.py --host "DeepSeek Harness"

# 供编排器消费
python host_compat.py --skill-dir <目录> --json
```

### 结果解读

- **`B（半自动，待确认）`**：磁盘上检测到宿主技能库但宿主名未识别——证据可能是历史安装残留。若你确实在该宿主会话内 → 按 B 执行；若只是普通终端 → 改走 C
- **`[WARN] ... 技能库（推测）`**：该宿主技能库路径是启发式约定，请人工确认实际路径并回填 `skill_dirs_for()`；若该宿主不是交付目标可忽略
- **frontmatter FAIL**：按提示修复 SKILL.md 后重跑；启发式检测不替代 check_skill.py

### 留痕要求

试点留痕文件（`pilot.md`）必须记录本次裁决结论（宿主名、路径、总结论）。

---

## smoke_runner.py

### 何时执行

1. **任何脚本改动之后（强制）**——工具或技能 `scripts/` 下的 .py 有变更，即触发 X-C 回归，这是豁免口径的核心补偿控制
2. **技能进入 E/M 阶段验证之前**
3. **人工签认之前**——冒烟报告是签认的输入材料之一

### 执行目的

对被测脚本批量执行 5 项**机械可判定**检查：

| 项 | 内容 | 判定 |
|---|---|---|
| C1 | `--help` 可运行 | exit 0 且 stdout 非空 |
| C2 | 无参调用 | 非零退出且报错含用法提示=PASS；exit 0=WARN（确认是否全可选参数） |
| C3 | 非 TTY 不挂起 | 各调用均在超时内完成 |
| C4 | dry-run 适用性 | 只认参数定义形态（argparse/click）；**仅标注，恒 PASS** |
| C5 | `--help` 幂等 | 两次 stdout 一致 |

`--help` **内容**正确性属语义项，不在本套件（交 W-14）。

### 执行影响 ⚠️

- **会以子进程实际运行被测脚本**（各跑 `--help`、无参、二次 `--help`，共约 4 次/脚本）：
  - 技能脚本按约定"无参必须报错"，因此无参调用只会触发参数错误路径，**不执行业务功能**
  - 但若某脚本违反约定（无参也有副作用），本套件会**真实触发**该副作用——这正是 C2 要暴露的问题
  - 超时 15 秒（`--timeout` 可调）防止挂起脚本拖死流程
- **`--out` 会写报告文件**（自动创建父目录）；落盘失败报 FAIL 并退出 1
- **不联网、不读写被测脚本自身**；跳过 smoke_runner.py 自身并打印提示
- 退出码：`0`=全 PASS；`1`=任一 FAIL；`2`=仅 WARN

### 命令示例

```bash
# 标准用法：目录批量冒烟 + 落盘（先保留旧报告，不覆盖历史）
cp .verification/iteration-1/smoke.md .verification/iteration-1/smoke-runN.md
python smoke_runner.py --scripts <工具目录> <技能scripts目录> \
    --out .verification/iteration-1/smoke.md

# 单个脚本快速检查
python smoke_runner.py --scripts path/to/script.py
```

### 结果解读

- **FAIL**：存在阻断项，不得自动放行；按报告"证据"列定位后修复，修复后复跑直至全绿
- **WARN**：不阻断但需**人工书面评估**（如 C2 的"全可选参数确认"），评估结论记入当轮留痕
- **假 WARN 排查**：若报告中出现意料之外的脚本，检查 `--scripts` 目录里是否混入了临时 .py 文件（教训：临时测试文件应在回归前清理或移出被扫目录）

### 留痕要求

报告落 `.verification/iteration-N/smoke.md`；历史报告保留为 `smoke-runN.md`，**禁止覆盖**。

---

## security_scan.py

### 何时执行
1. **W 阶段每轮收尾**（编写期自检，与格式门 A 同批）；E/M 阶段全门复跑（M1-S"安全扫描"行的权威执行者——对应人工清单 M1-5 的 secret/端点机械初筛）
2. **交付前**（V8 属 [M] 机械门：FAIL 阻断，不得进入下一阶段）
3. **任何正文/references/scripts 内容修订后**（新增外链、新增代码片段时必跑）

### 执行目的
- 以机械可判定口径落实 V8：secret 正则+熵（§9.6）、端点与声明比对（§9.2 静态）、多语言交互（§8.3.1）、破坏性关键词防护（§8.3.10）、危险指令关键词（§9.8 关键词部分）
- 报告六行 V8-1~V8-6 + INFO 覆盖行；**代码命中 FAIL / 文档命中 WARN** 两级语义

### 执行影响
- **只读操作**：不联网、不执行被扫描技能的任何代码、唯一输出是 stdout 与 `--out` 报告文件
- 退出码：`0`=全 PASS；`1`=任一 FAIL（[M] 机械门阻断）；`2`=仅 WARN（人工书面评估后放行并留痕）

### 命令示例
```bash
# 标准用法：W 轮收尾 / 交付前终扫（报告落被扫技能的 .verification）
python tools/security_scan.py <skill_dir> --out <skill_dir>/.verification/m1-s/security-scan.md

# 文档引用链接（非真实外联）的豁免：域名白名单，豁免本身须留痕
python tools/security_scan.py <skill_dir> --allow-url docs.python.org --allow-url docs.qq.com
```

### 结果解读
- **V8-3 FAIL**：证据列出的未声明端点逐条裁决——真实外联写入 compatibility 声明（§9.9）；文档引用链接加 `--allow-url` 复跑并留痕
- **V8-4/V8-6 文档 WARN**：多为提示词/文档自身列举违禁词的合规表述，人工确认后放行（先例：llm-review 的 w-prompts.md W-15 行）
- **V8-2 熵 WARN/FAIL**：文本级启发式可能误报（长随机串），人工核对来源
- 覆盖行 WARN：有文件读取失败，覆盖不全，零命中行已同步降 WARN——先解决可读性再复跑

### 留痕要求
- 报告落 `.verification/m1-s/security-scan.md`（与 format-gate.md 同目录）；豁免（--allow-url / 文档 WARN 采信）结论记入当轮 fix-log 或验收留痕

---

## naming_precheck.py

### 何时执行
1. **设计期（立项前）**：技能目录尚不存在时，用 `--name/--description` 直接输入预检——这是 V2 的主时点（[M]，D 门出口判据之一，撞名须更名后才能立项）
2. **目录已存在时**（复检/库扩充后）：传技能目录，库内自动排除自身
3. **库发生增删后**（新技能入库可能让原有相似度关系变化，建议对在库技能批量复跑）

### 执行目的
- 以机械可判定口径落实 V2：同名 name + 目录名冲突检索（FAIL）；description 余弦 >0.85 / 关键词重叠(Jaccard) >0.6 告警（WARN，阈值可调）
- 相似度为启发式初筛（ASCII 词元 + CJK 二字元），告警=人工复核入口；范围定位的实质重叠判断仍由 V1 设计评审（H）承担

### 执行影响
- **只读操作**：不联网、不写入库目录，唯一输出是 stdout 与 `--out` 报告文件
- 退出码：`0`=全 PASS；`1`=同名 FAIL（[M] 阻断，更名后复跑）；`2`=仅 WARN（人工复核相似度告警后放行并留痕）

### 命令示例
```bash
# 设计期：目录尚不存在，直接输入 name/description
python tools/naming_precheck.py --name <new-skill-name> --description "<一句话触发描述>" \
    --library C:/Users/<user>/.workbuddy/skills

# 复检：传技能目录（多库可重复 --library）
python tools/naming_precheck.py <skill_dir> --library <lib1> --library <lib2> \
    --out <skill_dir>/.verification/m1-s/naming-precheck.md
```

### 结果解读
- **V2-1 FAIL**：name 撞名（含大小写变体）或目录名被占——必须更名；name 规范为小写连字符
- **V2-2/V2-3 WARN**：证据列 top-3 相似技能与分值，人工判断是否实质重叠（相近定位应并入既有技能或明确边界，回 V1 设计评审）
- **COV WARN**：库内存在 name 不可解析条目（相似度覆盖有缺口，V2-2/V2-3 已降 WARN）或库路径不可达（全部行降 WARN）——先修复库状态再复跑
- 目标无 description：相似度不可验，V2-2/V2-3 记 WARN 不假 PASS

### 留痕要求
- 报告落 `.verification/m1-s/naming-precheck.md`；设计期无目录时报告可落项目工作区留痕后并入技能 `.verification/`

## token_budget.py

### 何时执行
1. **W 阶段**：SKILL.md 定稿后（V17 预算门属 [M] 机械门，FAIL 阻断进入下一阶段）
2. **M1 终检**：与 A 门、V8 复跑并列执行（M1-S 表预算行）
3. **正文/元数据/扩展层任何变更后**（V7 CI 回归范围）

### 执行目的
- 以 V11 固定口径（ceil(字符/4)，宿主 tokenizer 缺席时的保守兜底实现）落实 V17 预算门：正文 <5000 tokens（官方 [M]）、元数据 name+description ≤100 tokens（项目级收紧）、扩展层 references/assets 单文件 ≤500 行（项目级收紧）
- SKILL.md <300 行归 check_skill.py A6，本工具只记 INFO（≥240 行提示 V27 预警线）——职责不重复

### 执行影响
- **只读操作**：不联网、不改技能内容；预算超限的处置（拆分/外移）由 V26/V27 流程与人工裁决承担，本工具 FAIL 不得自动改写
- 退出码：`0`=全 PASS；`1`=任一预算超限 FAIL（[M] 阻断）或参数错误；`2`=仅 WARN（如 description 缺失）

### 命令示例
```bash
python tools/token_budget.py <skill_dir> \
    --out <skill_dir>/.verification/m1-s/token-budget.md

# 宿主 tokenizer 校准后（实测字符/token 比值），全 CI 须同步同一比值
python tools/token_budget.py <skill_dir> --chars-per-token <实测比值>
```

### 结果解读
- **V11-1 FAIL**：正文 ≥5000 tokens——按 V18/V26 渐进式披露把非核心内容外移 references/ 后复跑
- **V17-1 FAIL**：元数据 >100 tokens——压缩 description（触发职责不变前提下精简，改后须重跑触发门 C）
- **V17-2 FAIL**：扩展层单文件 >500 行——触发拆分评审（附目录或分文件）
- **CJK 占比提示**：chars/4 对 CJK 文本**低估**实际 token（证据内已标注占比），占比 >30% 时建议以宿主 tokenizer 实测值复核
- **COV WARN**：文件读取失败——覆盖不全，零命中行已降 WARN，先修复再复跑

### 留痕要求
- 报告落 `.verification/m1-s/token-budget.md`；宿主 tokenizer 校准事件（比值、实测方式）记入当轮 fix-log

---

## tests/test_regression.py

- **何时执行**：任何工具改动后、V6 冒烟之前（先单测后冒烟）；日常用 `local_gate.py --run` 一键覆盖（LG-1 自动纳入本套件），定位问题时再单跑
- **执行目的**：把六轮评审的修复结论固化为可执行断言（表驱动路径、去重、BOM、Cursor 两场景、OSError 兜底、click 形态等）；2026-10-03 收官批次改写为族 fail/ok 惯例 + test_family_backfill 组固化 VERSION/_BlockArgParser 全员
- **执行影响**：只读 + 临时目录内自建自删测试夹具；其中 mock 会临时替换 `Path.home`/`shutil.which`，仅限进程内，不影响系统
- **用法**：`python tests/test_regression.py`；全过打印 `ALL PASS`，任何断言失败即非零退出

## eval_discipline.py

### 何时执行
1. **E 阶段**：评测集定稿与首轮产出后（V21 断言时机核对；run-log 留痕佐证语义半）
2. **W 阶段 description 优化轮写回后**（V28 一致性核对，提供选定版本依据）
3. **每轮验收通过时**（`--mode record` 落 V29 基线）；**其后任何时点**（V29-2 防覆盖比对）
4. **M1 终检**（评测纪律留痕完整性核对）

### 执行目的
- V21：断言添加时机机械核对（显式 `assertions_added_at` 字段优先，mtime 启发式兜底并声明可被复制重置的局限）；用例数记录（"初始 2–3 条"语义归 H）
- V28：description 选定版本与 frontmatter 落盘逐字符一致（防写回丢失/截断/变形）
- V29：iteration 基线记录与防覆盖比对（篡改/删除/基线外新增均 FAIL）——record→verify 机械闭环

### 执行影响
- **只读操作**（check 模式）；`--mode record` 仅写 `.verification/.iteration-baseline`（不触碰评测产物与 SKILL.md）
- SKIP 不计警告（对齐 check_skill A1 口径）——三门大量场景依赖依据提供与否，SKIP 行均须人工留痕佐证、不豁免上游条款
- 退出码：`0`=全 PASS；`1`=任一 FAIL 或参数错误（统一 exit 1，不撞 WARN 码 2）；`2`=仅 WARN（如基线缺失待人工判断）

### 命令示例
```bash
# 三门检查（E 阶段，提供评测工作区）
python tools/eval_discipline.py <skill_dir> --workspace <skill>-workspace \
    --description-final .verification/desc-final.md --out .verification/m1-s/eval-discipline.md

# 验收通过时落基线（V29 record）
python tools/eval_discipline.py <skill_dir> --mode record --version v1.0 --iteration 1 \
    --accepted-at 2026-10-03T00:00:00 --snapshot-dir .verification/iteration-1
```

### 留痕要求
- 报告落 `.verification/m1-s/eval-discipline.md`；record 落基线须在当轮验收留痕（验收报告路径入 `--acceptance-report`）
- V29-2 旧格式基线（无 snapshot 块）SKIP 的技能，建议首次复检时 record 重落升级；V21/V28 的 SKIP 行处置（佐证方式）记入当轮 fix-log 或验收留痕
- v1.0.1（2026-10-03 首轮外部评审 7 条处置）：record 不带 `--snapshot-dir` 时 stderr 明示"V29-2 将 SKIP"；cases 形态断言全空 → V21-2 WARN（补断言提示），与 queries 形态的 SKIP 区分；snapshot 快照 SKIP 判定按快照根相对路径（祖先目录名 venv 等不再清空快照）；无秒 ISO 时间戳补秒（Python 3.10 兼容）；空 `--description-text` fail-fast exit 1

---

## dep_check.py

### 何时执行
1. **W 阶段**（脚本定稿后）：DEP-1 版本固定 / DEP-2 内联声明 / DEP-3 manifest / DEP-5 清单完备
2. **M1 终检**（M1-1 审计单依赖部分）：与 security_scan/token_budget 并行复跑
3. **第三方技能挂载前**（V13 安装审计的依赖项机械初筛）

### 执行目的
- DEP-1：外部工具调用钉版（§8.1.2）——运行器/包管理调用包规格三态判定
- DEP-2：捆绑脚本内联依赖声明（§8.2.1）——PEP 723/Deno/Bun/Ruby 四语言，agent 单命令可运行
- DEP-3：禁独立 manifest（§8.2.2）——自带 requirements.txt/package.json 等即违背自包含
- DEP-4：版本说明符固定（§8.2.3/§8.2.5 [S]/[P]）——裸依赖/范围说明符/gem 未钉 WARN
- DEP-5：脚本清单完备（§8.2.4）——scripts/ 实际文件 ⊆ SKILL.md 清单

### 执行影响
- **只读操作**（不触碰任何技能文件）
- SKIP 不计警告（无 scripts/、无运行器调用、无内联声明等不适用场景）
- 退出码：`0`=全 PASS；`1`=任一 FAIL 或参数错误（统一 exit 1）；`2`=仅 WARN（DEP-4 说明符/DEP-5 陈旧清单等 [S] 级与人工甄别项）
- 已知局限（docstring 固化）：Ruby 标准库无机械清单（保守口径）、SKILL.md 调用示例中的占位脚本路径会触发 DEP-5 WARN、Python 三引号 docstring/JS 块注释内示例命令可能触发 DEP-1 误报——证据均带文件:行号供人工甄别
- v1.0.1（2026-10-03 首轮外部评审 7 条处置）：dist-tag（latest/next/beta 等）不再判 pinned → ranged；Bun 版本化导入统一 classify_pkg_spec（ranged/dist-tag → DEP-4 WARN 不再静默）；SKILL.md 缺失计入读取失败（COV WARN + PASS 降级）；取值旗标 -r/--requirement/-p/--package 等连值跳过（pip install -r 不再误 FAIL）；TOML 单引号支持

### 命令示例
```bash
python tools/dep_check.py <skill_dir> --out .verification/m1-s/dep-check.md
```

### 留痕要求
- 报告落 `.verification/m1-s/dep-check.md`
- DEP-1/DEP-3 的 WARN 并列证据（文档口径命中/夹具 manifest）须人工甄别后记入当轮 fix-log 或验收留痕
- §8.2.6 环境干扰（Gemfile/node_modules 在场）与依赖实际可解析（M1-9）属 O 实测域，本工具命中提示不替代实测

---

## deliver_check.py

### 何时执行
1. **W 阶段收尾**：EX-1 交付物（SKILL.md+evals.json）/EX-4 license/EX-5~7 B1 留档初筛
2. **E3 人工复核后**：EX-2 feedback.json 落盘复检（SKIP 转 PASS/FAIL）
3. **M1 终检**：EX-1 验收报告在场核对 + EX-3 grading schema 复检

### 执行目的
- EX-1：交付物清单齐全（§15.7/M1-7）——编写期产物缺失阻断、验收报告 M1 时点 WARN
- EX-2/EX-3：运行产物 schema（§7.7.4/E3-2、§7.2.6/E-S）——feedback 双文档口径同认、grading 字段名+summary 四键
- EX-4：license 许可初筛（§2.4.1–2.4.2/V15 [S]）——条款内嵌嫌疑+随包 LICENSE 在场；第三方素材许可留档归人工
- EX-5~7：B1 三类记录存在性（§5.1.3/5.1.6/5.1.9）——关键词/目录初筛，结论裁决归 H（清单 §0 口径）

### 执行影响
- **只读操作**（.verification/ 为留痕扫描主域，不进 SKIP_DIRS——区别于 dep_check）
- SKIP 不计警告：feedback/grading 未产出（W 阶段预期）、license 未声明（内部使用）、留痕域未建
- 退出码：`0`=全 PASS；`1`=任一 FAIL 或参数错误（统一 exit 1）；`2`=仅 WARN（M1 时点项/初筛未见/门 D 类工件等）
- 已知局限：B1 记录可能在技能树外素材档案（关键词初筛未见→WARN 人工确认）；frontmatter 为 YAML 子集解析；iter_vfiles 仅 .md/.txt（.log/.rst 等漏检属初筛局限）
- v1.0.1（2026-10-03 首轮外部评审 8 条处置）：SKILL.md 读入 utf-8-sig+frontmatter_block lstrip 剥 BOM（\ufeff 非 strip() 空白，原致 EX-4 假 SKIP）；feedback B 口径键名无 //- 分隔时证据并入疑似元数据文件提示；grading summary 值非数值（含 bool）WARN；references//assets/ 内 feedback/grading=示例口径不判 FAIL 降 WARN；EX-6 改查实际文件（空子目录不再绕过）；license_field 三返回值+重复 license 键 WARN
- v1.0.2（2026-10-03 二轮追加评审 3 条处置）：okn 死变量删除；grading 断言超 20 条时证据带截断标注（另 N 条未检查，对齐族口径）；summary-only（不列明细）形态独立 WARN——汇总须有明细支撑

### 命令示例
```bash
python tools/deliver_check.py <skill_dir> --out .verification/m1-s/deliver-check.md
```

### 留痕要求
- 报告落 `.verification/m1-s/deliver-check.md`
- EX-5~7 的 WARN（初筛未见）须人工确认留档位置后记入当轮 fix-log 或验收留痕；EX-2/EX-3 的门 D 类工件 WARN 人工甄别

---

## local_gate.py

### 何时执行
- **任何工具/测试改动后**：`python local_gate.py --run` 全量门禁（先过门再同步双盘/提交）
- 快速回路（仅单测）：`python local_gate.py --run --tests-only`

### 执行目的
- LG-1：tests/test_*.py 全套子进程隔离回归（动态 glob 自动纳入新测试）
- LG-2：全工具 V6 冒烟 C1–C5（复用 smoke_runner，排除自身防自引用）

### 执行影响
- **只读+临时子进程**；门禁 FAIL（exit 1）= 阻断——不得同步双盘/提交
- `--out` 落盘报告（建议 .verification/iteration-N/local-gate.md）
- 覆盖口径：local_gate 由 tests/test_local_gate.py 覆盖快速路径（无参契约/timeout 校验/tail/_flat/发现函数/导入兜底/证据压平行为验证，7 组断言，fail-ok 族惯例），刻意不入 LG-2 冒烟清单——防 `--run` 递归自引用；smoke_runner 无专属单测，由 LG-2 冒烟覆盖其无参 C2 契约路径
- A1 相关单测不依赖官方 CLI 在场

### 命令示例
```bash
python tools/local_gate.py --run
python tools/local_gate.py --run --tests-only
python tools/local_gate.py --run --out .verification/iteration-1/local-gate.md
```

### 留痕要求
- 门禁 FAIL 修复后重跑至全绿，报告落盘随当轮 fix-log 归档

---

## check_skill.py

### 何时执行
- W 阶段每轮收尾（编写期自检）；E/M 阶段全门复跑（M1-S 的格式门 A 权威执行者）；任何 SKILL.md/scripts 修订后基线回归

### 执行目的
- 以脚本可判定口径落实 §13 A1–A11（A6 项目收紧 <300，`--lines 500` 可切官方口径）；附加 X1/X2 提供旁证（不计入判定）

### 执行影响
- 只读检测（A10 会以 `--help` 无害调用各脚本），报告默认打印、`--out` 可落盘；退出码 0/1/2 = 全 PASS / 有 FAIL / 仅 WARN-SKIP

### 命令示例
```bash
python tools/check_skill.py <skill_dir> --out <skill_dir>/.verification/m1-s/format-gate.md
python tools/check_skill.py <skill_dir> --lines 500   # 官方口径
```

### 结果解读
- **FAIL**：按证据列"下一步"提示修复后复跑；[M]/[S] 级 FAIL 阻断交付
- **A8 存在性核对**为 WARN 级旁证——SKILL.md 代码块内的用法示例（如 `scripts/foo.py`）可能合法不存在，须人工区分
- **A1 SKIP**：官方 skills-ref CLI 未安装；A2–A11 等效覆盖，装齐后本行自动变为实判

### 留痕要求
- 报告落 `.verification/m1-s/format-gate.md`（不覆盖旧报告，历史按 runN 保留由调用方管理）
### A1 官方校验器口径（T 项，2026-10-03）

- 官方包=PyPI `skills-ref` 0.1.1（anthropics/agentskills，Apache-2.0），**CLI 入口名 `agentskills`**
- 已装托管 venv：`C:\Users\yianyao\.workbuddy\binaries\python\envs\default\Scripts\agentskills.exe`；A1 实检须 PATH 含该 Scripts（或全局安装 agentskills），否则 A1 SKIP（不计警告）
- ⚠️ **npm 同名包 skills-ref 系第三方占用**（crazyyanchao/agentskillsjs，demonstration only）——勿经 `npx skills-ref` 调用；dep_check DEP-1 对未钉版 npx 调用判 FAIL 的纪律与此同源
- 环境重建时：`<venv python> -m pip install skills-ref==0.1.1`（钉版）
- v1.1.2（2026-10-03 追加评审 2 条处置）：A1 探测改官方入口名 agentskills 优先
（npm 第三方占用包 bin 名恰为 skills-ref，并存环境不得优先命中第三方）；参数解析回填
_BlockArgParser——--lines abc 等参数错误统一 exit 1（不再撞 WARN 码，C2 契约仍满足）


## inject_test.py（v1.0，2026-10-03 S 类补齐批次）

### 何时执行
- 人工清单 M0-3/V23 fail-loud 注入测试（新技能验收 M0 阶段；环境/解析器变更后复测）

### 执行目的
- 验证宿主/解析器对非法 frontmatter **报错而非静默跳过**（fail-loud 纪律）；原目录只读自证

### 执行影响
- **只读原目录 + 临时目录副本变异**（每用例独立 mkdtemp、内层目录名=原技能名——官方解析器校验目录名与 frontmatter name 一致）
- 解析器缺位 → V23-0..3 SKIP（COV 不计警告），V23-4 恒实检

### 命令示例
```
python tools/inject_test.py <skill_dir> [--out 报告路径]
# 官方解析器须在 PATH（venv Scripts）；或 --parser-cmd "..." 显式指定
```

### 留痕要求
- 报告落 `.verification/m0-s/inject-test.md`；V23-0 FAIL（对照组失败）= 解析器/环境问题，先排查再复测

## kw_locator.py（v1.0，2026-10-03 S 类补齐批次）

### 何时执行
- 人工清单 B3-1 / W-08 破坏性操作防护评审前（产出"定位段落"供 W-08 投喂）

### 执行目的
- 定位技能内破坏性关键词命中（词表单一来源复用 security_scan V8-5/§8.3.10），逐处给 文件:行+上下文+防护旗标在场性（仅标注不判定——判定归 W-08 L/H）；零命中输出"定位段落为空"（W-08 降级句自此转备用）

### 执行影响
- **信息供给非门禁**：无 FAIL 语义，exit 2 恒不出现（0=报告产出/1=参数错误，设计决策显式声明）
- 只读扫描（跳过二进制/符号链接/>512KB）

### 命令示例
```
python tools/kw_locator.py <skill_dir> [--out .verification/b3-s/kw-locate.md]
```

### 留痕要求
- 报告随技能留档；W-08 评审记录须注明"定位方式：S 定位器（kw_locator v1.0）"
