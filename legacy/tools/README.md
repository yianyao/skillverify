# tools — K 类验证 S 工具链（说明文档）

> 操作方法（何时执行 / 执行目的 / 执行影响）见 [OPERATIONS.md](OPERATIONS.md)。

## 定位

本目录是 `agent-skill-llm-review` 技能生命周期的**验证工具层**（S 工具链）。
按 V6 共识：**执行形态记 S（脚本），验证目标仍记 K（技能）**。
两个脚本均为**无 SKILL.md 的裸脚本**——由人或编排器显式调用，不经宿主的技能匹配管线，不受 D 门/W 组评审管辖（豁免口径见下）。

## 文件清单

| 文件 | 职责 |
|---|---|
| `check_skill.py` | **格式门 A 权威校验器**（待办 #5，2026-10-02 验收后建成；同日外部评审修订为 v1.1）：§13 A1–A11 全量机械判定（A6 项目收紧 <300 且设 80% V27 预警线，`--lines` 可覆盖官方 500；A7 覆盖孤立 \r；A8 先剥离 URL）+ 附加 X1 BOM / X2 evals.json；A1 官方 CLI 在场则实检 validate，缺席记 SKIP 且 **SKIP 不计警告级（全绿时 exit 0）**；v1.1.4（2026-10-03 复检）报告头补版本标识（v1.1.3 补 VERSION 常量但报告头漏写）；v1.1.3（T 项+追加评审 2 条）A1 探测扩官方入口名 `agentskills` 并改官方优先（npm 同名包系第三方占用已警示；并存环境不命中第三方）、参数解析回填 `_BlockArgParser`（参数错误统一 exit 1） |
| `security_scan.py` | **V8 安全扫描器**（待办 S1①，2026-10-02 建成，现 v1.0.3——收官批次回填 `_BlockArgParser`+`--out` 空串校验）：V8 全覆盖六项——secret 正则库 8 类 + 占位符降噪、熵检测（≥4.5，hex 哈希天然不误报）、端点提取与 compatibility/`--allow-url` 比对、多语言交互 8 类（全包扫描面，补强 A9）、破坏性关键词确认防护（§8.3.10）、危险指令关键词（§9.8）；两级语义：代码文件命中 FAIL / 文档命中 WARN；**独立于 check_skill.py 的独立脚本**（承载方式经用户裁决，不触碰冻结的 A 门校验器） |
| `naming_precheck.py` | **V2 命名冲突预检器**（待办 S1②，2026-10-02 建成 v1.0，同日评审修订 v1.0.1：top-1 判定值加粗单列+前 3 名明细、CJK 跨段 bigram 口径成文、--name 格式预检（防越界路径）、skill_dir 优先级成文+stderr 提示、**缺参 exit 2→1 撞码修正**、V2-1 证据去重；v1.0.2 自检修复 v1.0.1 引入的 C2 冒烟回归——自查报错补"用法"提示；v1.0.3 随 token_budget 评审扩撞码覆盖——argparse 类型转换错误经 error() 覆写统一 exit 1）：同名 name（大小写不敏感）+ 目录名冲突 → FAIL；description 余弦 >0.85 / 关键词重叠(Jaccard) >0.6 → WARN（阈值可调）；双输入模式（设计期 `--name/--description` 直接输入 / 技能目录）；多 `--library`、库内自排除、覆盖缺口降 WARN 纪律、退出码 0/1/2；相似度口径与降级语义见 docstring |
| `token_budget.py` | **V11/V17 上下文预算门**（待办 S1③，2026-10-02 建成 v1.0，同日评审修订 v1.0.1：无 SKILL.md 早退 stats 补齐四键、V17-3 读取失败不缺席改 WARN、name+description 合并口径注释固化、**argparse 全部参数错误（含类型转换）经 error() 覆写统一 exit 1**）：V11 token 固定口径（ceil(字符/4)，`--chars-per-token` 可校准但须全 CI 同步；CJK 占比 >30% 证据内提示人工关注）+ V17 预算行——正文 <5000 tokens（官方 [M]）、元数据 name+description ≤100 tokens（项目级收紧）、扩展层 references/assets 单文件 ≤500 行（项目级收紧，scripts/ 不属扩展层）；SKILL.md 行数 INFO（<300 判定归 check_skill A6，读取失败 WARN 不缺席）；frontmatter 剥离后计正文；覆盖缺口降 WARN 纪律 |
| `host_compat.py` | K 类在环试点前的跨宿主兼容性检查入口（**v1.0**——2026-10-03 收官批次首次版本化：补 VERSION+报告头版本标识+`_BlockArgParser`）：识别宿主、裁决试点路径（A/B/C）、探测技能库、体检被试点技能 frontmatter |
| `eval_discipline.py` | **V21/V28/V29 评测纪律三门**（待办 S1④，2026-10-03 建成 v1.0，同日首轮外部评审 7 条全核实处置升 **v1.0.1**：snapshot SKIP 判定改快照根相对路径（高——绝对路径 p.parts 会把祖先目录名 venv 等误判清空快照）、无秒 ISO 补秒 parse_iso_ts（Python 3.10 fromisoformat 兼容防误 FAIL）、cases 空断言新形态 cases-no-asserts → WARN、record 缺 --snapshot-dir stderr 提示+docstring 明确可选、parse_baseline 行内无空格 snapshot:{…} 兼容、空 --description-text fail-fast exit 1、必填字段口径注释；单测 18 组。合一工具——三门同属 E/X 阶段评测与迭代留痕纪律、输入同源，沿 token_budget 两门合一先例）：V21-1 评测集在场+用例数（三形态识别，"初始 2–3 条"语义归 H）/V21-2 断言时机（`assertions_added_at` 显式字段优先、mtime 启发式兜底并声明局限）/V28-1 description 写回一致性（SHA256 逐字符比对）/V29-1 基线在场+必填字段（兼容旧式键值格式）/V29-2 防覆盖比对（snapshot 块逐文件 SHA256，篡改/删除/基线外新增均 FAIL）；**check/record 双模式**（record 写增强基线形成 record→verify 闭环）；SKIP 不计警告（对齐 A1 口径，须人工留痕佐证）；退出码 0/1/2，参数错误统一 1 |
| `dep_check.py` | **§8.1.2/§8.2 依赖检测五项**（待办 S1⑤，2026-10-03 建成 v1.0，同日首轮外部评审 7 条处置升级 v1.0.1——dist-tag 黑名单（pkg@latest 不再误判 pinned）/Bun 导入统一 classify_pkg_spec/SKILL.md 缺失计 COV/取值旗标（-r -p 等）不误取作包名/TOML 单引号，独立脚本，检查项编号 DEP-1~5 为工具本地编号、V1–V29 已占用）：DEP-1 运行器/包管理调用钉版三态（npx/bunx/uvx/pipx/pip/uv/deno/go run——精确 PASS/范围 WARN/缺失 FAIL，代码 FAIL/SKILL.md 文档 WARN）/DEP-2 内联依赖声明四语言（PEP 723 块（sys.stdlib_module_names 机械判定+本地模块豁免）/Deno npm:/jsr:/Bun pkg@ver/Ruby bundler/inline）/DEP-3 禁独立 manifest（package.json/requirements.txt/Gemfile/go.mod FAIL；pyproject/夹具 WARN 人工甄别，Gemfile 附 §8.2.6 干扰提示）/DEP-4 版本说明符（裸依赖/缺 requires-python/范围说明符/gem 未钉 → WARN）/DEP-5 脚本清单完备（scripts/ 实际文件 ⊆ SKILL.md 清单缺列 FAIL，陈旧/示例占位 WARN）；Ruby 标准库无机械清单按保守口径、PEP 723 正则抽 TOML 子集（3.10 兼容）等局限入 docstring；退出码 0/1/2，参数错误统一 1 |
| `deliver_check.py` | **S1⑥ 存在性/schema 门七项**（2026-10-03 建成 v1.0，同日两轮外部评审处置升级 v1.0.2——一轮 8 条：BOM 剥除（utf-8-sig+lstrip 双保险）/B 口径弱约束提示/summary 值类型弱检/references 示例口径降 WARN/EX-6 空子目录绕过修/多 license 键 WARN；二轮 3 条：okn 死变量删/断言超 20 条截断标注/summary-only 形态 WARN，S 类收官批次，独立脚本，检查项编号 EX-1~7 为工具本地编号、V1–V29 已占用）：EX-1 交付物存在性（§15.7/M1-7：SKILL.md+evals.json 缺失 FAIL，acceptance-report.md 缺失 WARN=M1 时点项）/EX-2 feedback.json 落盘+结构（§7.7.4/E3-2：双文档口径同认——A text/passed/evidence 含列表形态、B 键=用例目录名→文本空串=通过；空对象 WARN；不匹配 FAIL；未产出 SKIP）/EX-3 grading.json schema（§7.2.6：断言字段 text/passed/evidence、summary 四键；未见 summary WARN 门 D 类工件人工甄别）/EX-4 license（§2.4.1–2.4.2/V15：字段>120 字符或块标量多行 WARN 条款内嵌嫌疑+随包 LICENSE 在场；均未声明 SKIP）/EX-5~7 B1 三类留档存在性（§5.1.3/5.1.6/5.1.9：关键词初筛+iteration 目录核对，未见 WARN 人工确认——清单 §0 口径记录存在性可脚本核对、结论裁决归 H）；feedback 双口径冲突（总表 vs 操作手册）两口径同认不擅自裁断，留 fix-log；退出码 0/1/2，参数错误统一 1 |
| `local_gate.py` | **本地回归门禁（待办 C，2026-10-03 建成 v1.0，同日两轮评审处置升 v1.2——一轮 8 条（自身零覆盖→新建 test_local_gate/LG-2 ev 转义/导入兜底/timeout 校验/--out 消息/discover 收口）；二评 6 条（run_smoke 返回值恒为清单数防口径分裂/_flat 证据压平收编管道符+换行（行为测试当场抓出单独 \r 粘连缺口）/测试对齐 fail-ok 族惯例（mock 注入解耦、-O 免疫实测））**：LG-1 tests/test_*.py 全套子进程隔离运行（动态 glob 自动纳入新测试，当前 13 套 233 组断言）+ LG-2 复用 smoke_runner.smoke_one 全工具 C1–C5 冒烟（排除自身防递归自引用）；退出码 0/1/2，`--run` 必填语义（无参 exit 1 带用法+执行计划——C2 契约，防长任务无参误触发）、`--tests-only` 快速回路、`--out` 落盘；覆盖口径：local_gate 由 test_local_gate.py 覆盖快速路径（不入 LG-2 防递归），smoke_runner 由 LG-2 覆盖其无参 C2 路径 |
| `inject_test.py` | **V23 fail-loud 注入测试（人工清单 M0-3 单宿主口径，2026-10-03 建成，同日三评升 v1.0.1、复检升 v1.0.2、复检二升 v1.0.3（main 前置读码 OSError 兜底）——SKILL.md 读码 utf-8-sig 双点（main+_mutate，BOM 不误判不变异失效）/删死常量 NAME_PAT；三评——copytree `_IGNORE` 排除留痕目录/无 frontmatter exit 1 防静默变异失效/V23-2 整块剥除（`_drop_top_keys` 键+续行）/`_make_case_copy` 异常清理闭环/SKIP 计 exit 2 口径显式声明（与 A1 SKIP 的设计差异））**：临时副本注入非法 frontmatter（V23-1 非法 YAML/V23-2 缺必填键/V23-3 name 违规），官方解析器（复用 check_skill.find_official_cli，A1 同款 validate 调用形态）非零退出=fail-loud PASS、零退出静默接受=FAIL；V23-0 对照组（未修改副本须通过，失败=环境问题注入转 SKIP）；V23-4 原目录 SHA256 全清单前后一致（只读自证）；解析器缺位 V23-0..3 SKIP（COV），V23-4 恒实检；退出码 0/1/2，`--parser-cmd` 可注入假解析器（测试不依赖外部 CLI） |
| `kw_locator.py` | **B3-1 关键词定位器（§8.3.10 → W-08 定位段落供给，2026-10-03 建成，同日复检升 v1.0.1——security_scan 词表导入失败显式 exit 1 不静默（评审建议的返空列表会伪造 L-3 零命中声明，不采纳）+ docstring 声明扫描口径）**：SKILL.md 正文+文本文件逐行扫描（词表单一来源复用 security_scan V8-5 DESTRUCTIVE_WORD_RE），逐命中产出 文件:行+行文本+±2 行上下文+代码文件防护旗标在场性标注（仅标注不判定，判定归 W-08 L/H）；零命中输出"定位段落为空"声明（W-08 降级句转备用）；**信息供给非门禁——无 FAIL 语义，exit 2 恒不出现**（0=报告产出/1=参数错误，设计决策显式声明） |
| `smoke_runner.py` | V6 脚本冒烟套件（**v1.1**——2026-10-03 回填 `_BlockArgParser` + 收官批次补 VERSION 常量与报告头版本标识）：对指定脚本批量执行 5 项机械检查（C1~C5），报告可落盘 |
| `w_static_lint.py` | **编写期静态补检器 L-1~L-18（验证补全工程甲档工具一，2026-10-03 建成 v1.0，首轮外部评审 2 P0+6 一致性+8 覆盖缺口处置升 v1.0.1——L-5 引号数组先判引号再判裸值（"1.0"/"true" 引号 str 合规写法不再误 FAIL）/L-12 补 is_binary 过滤（二进制 0x0D 不再误判 CR）/L-14 补扫缩进叶值/L-3 空 frontmatter WARN+重复键去重/--host 回显保大小写；独立自查轮升 v1.1——L-7 链图 per-branch（chain 循环内累积把兄弟分支串成假链）/L-15·L-17 行号补 frontmatter 偏移（原为正文相对值冒充文件行号）/判定统计口径对齐（PASS/FAIL 分母明示+WARN/SKIP/INFO 计数）**：编写期静态补检 18 项——L-1 同义变体目录/L-2 无关文件白名单体积/L-3 顶层键白名单/L-4 块标量/L-5 metadata 值类型/L-6 allowed-tools/L-7 引用链二层（围栏外全文，含 frontmatter；rstrip(".") 防 Win32 尾点暗坑）/L-8 Gotchas/L-9 templates+assets/L-10 全包宿主路径/L-11 宿主黑名单（--host 增补）/L-12 全包 LF+BOM（二进制 NUL 嗅探跳过）/L-13 .gitattributes/L-14 i18n/L-15 命令混译/L-16 基线哈希漂移（兼容 eval_discipline 新旧两式）/L-17 笼统指引初筛/L-18 恶意特征初筛（终判归 LL-2/LL-6）；家族纪律全项，退出码 0/1/2，SKIP 不计警告 |
| `eval_artifacts_check.py` | **评测期产物校验器 Q-1~Q-9（验证补全工程甲档工具二，2026-10-03 建成 v1.0，首轮外部评审 2 Bug+5 一致性处置升 v1.0.1——Q-2 train ⊆ 全量对称校验（原漏查 train）/Q-8 证据列显式 or 链（dict.get 默认值仅键不存在时生效）/Q-4 递归 where 路径拼接/Q-5 delta 空 dict 不判缺失/Q-6 清单附 ×n 样本数/Q-9 exists() 单分支/统计口径注明；独立自查轮升 v1.1——Q-6 多 runs.json 合并统计（原只取首个与 Q-7 口径分裂，任一解析失败仍 FAIL）**：Q-1 查询集 schema（条数下限 --min-count 默认 12/配比/布尔/唯一/字段）/Q-2 切分（60/40±5pp、⊆ 全量对称、frozen.sha256 只读冻结一致）/Q-3 timing/Q-4 grading 断言 schema+summary 重算对账（不吃手填）/Q-5 benchmark 两组+delta/Q-6 恒过恒挂摇摆清单/Q-7 离群值按来源分池 >3× 均值/Q-8 留痕字段完整性/Q-9 迭代对账 INFO；产物缺失 SKIP 不计警告（区别 schema 错 FAIL），`--queryset/--split/--min-count` 可配，退出码 0/1/2 |
| `tests/test_check_skill.py` | check_skill.py 固化回归单测（合规全绿 + 六类缺陷响亮 FAIL + v1.1 系列评审回归点 + v1.1.3 收官回填（--lines 0 exit 1/VERSION 常量在场），26 组断言） |
| `tests/test_security_scan.py` | security_scan.py 固化回归单测（合规夹具 + 六类缺陷命中 + 两级语义 + 边界断言/脱敏 + 退出码 0/1/2 + v1.0.3 收官回填（--out 空串 exit 1），16 组断言） |
| `tests/test_naming_precheck.py` | naming_precheck.py 固化回归单测（分词口径 + 同名三类 FAIL + 相似度告警/阈值可调 + 覆盖缺口降级 + 自排除 + 退出码含类型错误统一 1，12 组断言） |
| `tests/test_dep_check.py` | dep_check.py 固化回归单测（合规全绿/无 scripts SKIP/PEP 723 缺失/裸依赖/JS 三态/Ruby 两态/manifest 三判级/清单双向/DEP-1 并行判级/退出码+参数错误统一 1 + 评审 v1.0.1 回归（dist-tag 判级、Bun ranged→WARN、SKILL.md 缺失 COV 降级、TOML 单引号），14 组断言） |
| `tests/test_deliver_check.py` | deliver_check.py 固化回归单测（合规全绿/裸夹具三态/留痕域在场无内容 WARN/EX-1 FAIL/feedback 口径 A-B+空对象+不匹配/grading 缺 passed+summary 键不符+无 summary/license 三态+块标量直测/退出码+参数错误统一 1 + 评审 v1.0.1 回归（BOM 夹具/B 口径弱约束/summary 类型/示例口径/重复 license 键/summary-only/截断标注），15 组断言） |
| `tests/test_token_budget.py` | token_budget.py 固化回归单测（V11 ceil 口径 + frontmatter 剥离 + 三类预算超限 FAIL + scripts 豁免 + CJK 提示 + 覆盖纪律含 V17-3 不缺席 + 退出码/全部参数错误统一 1，13 组断言） |
| `tests/test_eval_discipline.py` | eval_discipline.py 固化回归单测（record→check 闭环 + mtime 两向 os.utime + 显式字段优先 + 三形态识别 + V28 三态 + 旧格式兼容 + 篡改/新增 FAIL + 退出码/六类参数错误统一 1，18 组断言） |
| `tests/test_local_gate.py` | local_gate.py 固化回归单测（无参契约与计划口径/--out 消息点破/--timeout 校验/tail 四边界/discover 软化清单/导入兜底 FAIL 行（mock __import__ 注入）/证据压平行为验证（假模块注入）；fail-ok 族惯例、-O 免疫，刻意不跑全量门禁防递归——与不入 LG-2 清单的豁免口径互为镜像，7 组断言） |
| `tests/test_inject_test.py` | inject_test.py 固化回归单测（全经 --parser-cmd 假解析器驱动不依赖外部 CLI：无参契约/参数校验/fail-loud 全 PASS/静默接受 FAIL/对照组失败注入转 SKIP/V23-4 原目录只读/解析器缺位 SKIP 函数级直调/纪律源码断言；-O 免疫实测，14 组断言） |
| `tests/test_kw_locator.py` | kw_locator.py 固化回归单测（无参契约/参数校验/L-1 定位要素齐备/L-2 防护标注/L-3 零命中声明/--out 落盘/词表单一来源+二进制跳过纪律断言；-O 免疫实测，7 组断言） |
| `tests/test_regression.py` | 固化回归单测（豁免口径的补偿控制，六轮评审结论的可执行化；2026-10-03 收官批次改写为族 fail/ok 惯例 + test_family_backfill 组固化 VERSION×3/_BlockArgParser 全员，9 组断言） |
| `tests/test_static_lint.py` | w_static_lint.py 固化回归单测（合规 18 项全绿 + 各检查项 FAIL/WARN 夹具 + v1.0.1 评审回归（引号数组/二进制跳过/--host 回显/基线双形态/空 frontmatter/重复键去重）+ v1.1 自查回归（链图 per-branch/行号文件真实偏移/统计口径），31 组断言） |
| `tests/test_eval_artifacts_check.py` | eval_artifacts_check.py 固化回归单测（合规基线全绿 + Q-1 配比三口径/Q-2 双向越集与 frozen/Q-3/Q-4 对账与嵌套 where/Q-5 delta 三态/Q-6 摇摆无标注多 runs 合并/Q-7 多池独立/Q-8 证据过短表头不识别/Q-9 文件形态 + 参数回归（--queryset/--min-count 20/--split 个数）+ v1.0.1/v1.1 评审与自查回归，51 组断言） |
| `README.md` / `OPERATIONS.md` | 本文档与操作手册 |

## 设计要点

- **仅标准库**，Python >= 3.10，Windows/Linux 兼容（路径去重用 `os.path.normcase` 按平台语义处理大小写）
- **host_compat.py**：
  - `HOSTS` 表是宿主识别与技能库路径的**单一真源**——env 变量 + 家目录启发式，命中即认定；新增宿主只改表一处
  - Claude Code / Cursor 的 `home` 刻意留空：`~/.cursor` 兼作 Cursor 编辑器配置目录，入表会让仅装过编辑器的机器被误判（探测由 `skill_dirs_for()` 显式分支承担）
  - "宿主名未识别但磁盘有技能库"的场景与"真在宿主会话内"**不可区分**，故路径裁决给 `B（半自动，待确认）` 并在提示中写明改走 C 的条件
  - frontmatter 检测是启发式（utf-8-sig 剥 BOM、顶层键逐行判定），**不替代 check_skill.py 的精确校验**
- **smoke_runner.py**：
  - 只做机械可判定项：C1 `--help` 可运行 / C2 无参报错带用法 / C3 非 TTY 不挂起 / C4 dry-run 适用性 / C5 `--help` 幂等
  - `--help` **内容**正确性属语义项，不在本套件范围（交 LLM 清单 W-14）
  - C4 只认参数定义形态（argparse `add_argument` / click `option`），不认裸字面量（曾因 "error:" 崩溃栈命中关键词产生误判，教训已注释入码）
  - 报告不覆盖历史：复跑前先保留旧报告为 `smoke-runN.md`
- **security_scan.py**：
  - **两级命中语义**：代码文件（scripts/ 目录 + 代码扩展名）命中 → FAIL；文档文件命中 → WARN（人工复核——W-15 类提示词自身列举违禁词属合规表述）。V8-3 端点例外：文档链接同样记未声明，豁免走 `--allow-url` 并留痕，不降 WARN
  - 熵检测阈值 ≥4.5 且长度 ≥20：常规 hex 哈希（SHA256 等）每字符熵上限 4.0 天然不误报；hex 形态 secret 依赖正则库覆盖（AKIA/Google 等已含）
  - 扫描面：全包文本文件；跳过 `.git`/`.verification`/`__pycache__`/`node_modules`/venv、二进制扩展名黑名单（宁可误扫不漏扫）、>2MB 超限
  - 覆盖不全不假 PASS：文件读取失败 → 覆盖行 WARN + 全部零命中行降 WARN，exit 不得为 0（对齐 check_skill v1.1c 纪律）
  - 语义审计（§9.1/§9.2/§9.8 完整语义）仍由 W-L + H 承担，本工具零命中不豁免语义审计

## 豁免口径（2026-10-02 用户确认生效）

两工具**豁免 D 门与 W 组评审**，条件：

1. **形态限定**：保持裸脚本形态；一旦包装成技能（带 SKILL.md 进技能库），自动恢复受 D/W 管辖
2. **补偿控制**：冻结 + 变更触发 V6 回归留痕；`tests/` 固化单测随工具分发；冒烟报告附证据行供人工抽查；首次接入真实新宿主强制实测 host_compat
3. 本口径作为 agent-skill-llm-review **M1 终检的检查项之一**

## 冻结与变更流程

自 2026-10-02 起**冻结功能变更**（适用于 host_compat.py 与 smoke_runner.py 的既有功能；待办 #9 record_review isdir 校验仍挂"解冻时做"）。任何改动必须走完整闭环：

```
改动 → python tests/test_regression.py → V6 全量冒烟（报告落 .verification/iteration-N/）
     → tools-fix-log.md 追加轮次记录 → 同步 D:\sData\specSkill（含 .verification/ 隐藏目录）
```

> **check_skill.py 建成记录（2026-10-02，验收后待办 #5）**：新增工具不属"既有功能变更"，按同一补偿控制执行——`tests/test_check_skill.py` 全 PASS、V6 冒烟 5/5 PASS、实弹验证 = 真实技能全绿 + 六类缺陷夹具全部响亮 FAIL（exit 1）。工具本身豁免 D/W（裸脚本形态），条件同豁免口径。**同日外部评审四轮共 23 条全采纳修订为 v1.1→v1.1b→v1.1c→v1.1d**（A6 行数口径 splitlines + 80% 预警线、A1 真检测 + SKIP 不计警告、A7 覆盖孤立 \r、A8 剥离 http(s)/file URL + 删死代码、A9/A11/X2/A10 全链路 OSError 防护 + 读取失败不假 PASS、解析前剥 BOM 由 X1 专职报警、总结论措辞分级并列等），单测扩至 20 组断言全 PASS，实弹退出码由恒 2 修复为全绿 0；详见 tools-fix-log.md v1.1 各节。

> **security_scan.py 建成记录（2026-10-02，待办 S1①）**：新增工具不属"既有功能变更"，按同一补偿控制执行——`tests/test_security_scan.py` 11 组断言全 PASS、V6 冒烟 5/5 PASS、既有回归（20+8）零影响、实弹 = llm-review exit 2（V8-6 文档 WARN 3 处=W-15 提示词合规表述，人工复核点）+ trigger-eval exit 0。承载方式经用户裁决为**独立脚本**（不扩展已冻结的 check_skill.py）。豁免口径同前（裸脚本形态），详见 tools-fix-log.md security_scan.py 节。
> **v1.0.1（同日首轮外部评审 9 条：8 属实采纳+1 补文档）**——证据脱敏（报告不含完整密钥）、--allow-url/声明匹配改主机+路径边界（修 example.com.evil.io 绕过）、读取失败移出 V8-1 独立 COV 行、V8-5 结构化判定、折叠标量续行提取、symlink 跳过、交互模式前置断言+read -rp、版本标识/预编译；单测扩至 **15 组断言**。运行期事故：C 盘工具链镜像曾置于技能目录内致扫描自噬（1/6 FAIL），已迁出至 `~/.workbuddy/skill-tools/`——第三方技能自带 tools/ 仍属扫描面（V13 审计不设盲区）。
> **v1.0.2（同日第二轮外部评审 6 条：4 改代码+2 补文档）**——V8-4 词形模式补齐边界断言（getpass/inquirer/prompt_toolkit 统一 `(?<!\w)…\b`，不命中 mygetpass/reinquirer/prompt_toolkits）、read 短选项收紧 `[a-zA-Z]*p`（不再误中 read -3p）、mask_secret tail 4→2（20 字符密钥泄露面 8→6 字符）、COV 行分隔符统一；url_allowed 显式声明"声明域同时放行其全部子域"口径、COV 符号链接计数语义（仅统计有效链接）入注释。单测 15 组断言扩负例后全 PASS。
>
> **naming_precheck.py 建成记录（2026-10-02，待办 S1②）**：V2 命名冲突预检器 v1.0，独立脚本（沿 S1① 惯例）。`tests/test_naming_precheck.py` 12 组断言全 PASS、V6 冒烟 5/5 PASS、既有回归（15+20+8）零影响、实弹 = llm-review/trigger-eval/quality-ab 三技能对宿主库全 PASS exit 0（自排除验证通过，库内最高余弦 0.328）。设计期双输入模式（--name/--description 无需目录）、相似度启发式口径与降级语义精确化（解析缺口只降相似度行，目录检索不依赖解析）详见 docstring 与 tools-fix-log.md naming_precheck.py 节。

## 归档与同步

`D:\sData\specSkill` 为归档基线。每次阶段产出后同步并做 SHA256 抽验；
`.verification/` 是隐藏目录，资源管理器复制时极易漏掉（2026-10-02 曾因此缺 13 个文件），建议命令行复制。

> **dep_check.py 建成记录（2026-10-03，待办 S1⑤）**：§8.1.2/§8.2 依赖检测五项 v1.0，独立脚本（沿 S1① 惯例，DEP-1~5 本地编号因 V1–V29 已占用）。`tests/test_dep_check.py` 10 组断言全 PASS、V6 冒烟 5/5 PASS、既有回归（20+12+13+15+18+8）零影响、实弹 = llm-review exit 2（唯一 WARN=DEP-5 启发式命中 SKILL.md 调用示例占位路径 scripts/foo.py，考证后非缺口，证据已补甄别提示）+ trigger-eval/quality-ab exit 0。开发期当轮修两处（DEP-4 SKIP 条件漏计 Ruby gem；DEP-1/3 FAIL 行丢 WARN 明细）。详见 tools-fix-log.md dep_check.py 节。
> **dep_check.py v1.0.1 评审处置记录（2026-10-03 同日）**：外部评审 7 条全核实属实（2 高 2 中 2 低 1 极低），另自抓伴生缺陷 1 处（pkg@ 尾随空版本 IndexError）一并修。单测 10→14 组、V6 冒烟 5/5、既有回归（20+12+13+15+18+8）零影响、实弹三技能与 v1.0 零行为差异。详见 tools-fix-log.md dep_check.py v1.0.1 节。
> **deliver_check.py 建成记录（2026-10-03，待办 S1⑥——S 类收官）**：存在性/schema 门七项 v1.0，独立脚本（EX-1~7 本地编号）。`tests/test_deliver_check.py` 9 组断言全 PASS、V6 冒烟 5/5 PASS、既有回归（20+12+13+15+18+14+8）零影响、实弹三技能全部 exit 2 纯 WARN/SKIP 零阻断（EX-1 验收报告 M1 时点 WARN、EX-5 反向测试留档在技能树外人工确认、quality-ab EX-3 gate-d grading 无 summary WARN 均按设计）。口径决策（feedback 双文档口径同认、B1 关键词初筛局限、验收报告降 WARN）留 tools-fix-log.md deliver_check.py 节。
> **deliver_check.py v1.0.1 评审处置记录（2026-10-03 同日）**：外部评审 8 条全核实属实（1 高 2 中+1 中弱改进 3 低 1 极低保留），高=BOM 未剥致 frontmatter 假 SKIP（双保险修）。单测 9→14 组、V6 冒烟 5/5、既有回归（20+12+13+15+18+14+8）零影响、实弹三技能零行为差异。详见 tools-fix-log.md deliver_check.py v1.0.1 节。
> **deliver_check.py v1.0.2 二轮评审处置记录（2026-10-03 同日）**：追加评审 3 条全核实属实（okn 死变量/entries[:20] 截断未标注/summary-only 静默通过），3 改代码。单测 14→15 组、V6 冒烟 5/5、既有回归零影响、实弹三技能零行为差异。详见 tools-fix-log.md deliver_check.py v1.0.2 节。
> **check_skill.py v1.1.1 / T 项接入记录（2026-10-03）**：官方校验器考证=PyPI skills-ref 0.1.1（anthropics/agentskills，CLI 入口名 agentskills；npm 同名包系第三方占用勿用）。A1 探测扩 agentskills 入口名；托管 venv 已装并实测三技能全 Valid；A1 实检口径（PATH 含 venv Scripts）写入 SKIP 证据与 OPERATIONS。详见 tools-fix-log.md T 项节。
> **check_skill.py v1.1.2 追加评审处置记录（2026-10-03）**：评审 3 条——A1 探测优先序改官方入口名 agentskills 优先（抽 find_official_cli 可注入直测）、_BlockArgParser 回填（参数错误统一 exit 1）、deliver_check 版本头条数考证（v1.0.1 实为 8 条，不采纳改 7）。单测 20→24 组、V6 冒烟 5/5、实弹三技能零行为差异。详见 tools-fix-log.md check_skill.py v1.1.2 节。
> **local_gate.py 建成记录（2026-10-03，待办 C——S/T 执行机制固化，待办清单全部收官）**：一键门禁 LG-1（8 套单测）+ LG-2（全工具 V6 冒烟），53 项全 PASS exit 0 自证；C2 契约开发期三步收敛（无参全量跑 FAIL 挂起→计划 exit 0 WARN→`--run` 必填 exit 1 带用法 PASS）；顺带回填 smoke_runner `_BlockArgParser`。任何工具改动后先 `python local_gate.py --run` 再同步双盘。详见 tools-fix-log.md C 项节。
> **local_gate.py v1.0→v1.1 首评 8 条处置记录（2026-10-03 同日）**：评审 8 条（1 高自身零覆盖/1 高 LG-2 ev 未转义/3 中导入兜底·timeout 校验·--out 消息/3 低重复计算·隐含契约·措辞）7 改码 + 1 低防御性随重构收口；考证澄清——smoke_runner 实际在 LG-2 清单内（其 C2 契约路径被覆盖），原 docstring 仅对 local_gate 自身虚假。新建 tests/test_local_gate.py 8 组断言（刻意不跑全量防递归）；单测 8→9 套、断言 113→127 组。详见 tools-fix-log.md local_gate.py v1.1 节。
> **local_gate.py v1.1→v1.2 二评 6 条处置记录（2026-10-03 同日）**：run_smoke 返回值恒为清单数（导入失败也返清单数，防报告头与执行计划口径分裂）；`_flat` 证据压平收编（管道符+各类换行——行为测试当场抓出单独 \r 粘连缺口）；test_local_gate 重写对齐族 fail-ok 惯例（mock 注入取代全局变量 hack、假模块行为验证取代源码断言、`python -O` 免疫实测）。测试 8→7 组、9 套 126 组断言。详见 tools-fix-log.md local_gate.py v1.2 节。
> **收官回填批次记录（2026-10-03 全量盘点评审处置——工具族进入冻结态）**：一次性回填 4 工具（security_scan v1.0.3 `_BlockArgParser`+`--out` 空串校验 / host_compat v1.0 首次版本化+`_BlockArgParser` / smoke_runner v1.1 VERSION+报告头标识 / check_skill v1.1.3 VERSION+`--lines` 正整数校验）+ test_regression 改写为族 fail/ok 惯例；盘点层 3 处修正（VERSION 缺口实为 3 个含 check_skill/「try/except 对齐 v1.2」描述不实/「第一次自洽证明」不实）。9 套单测 130 组、三技能实弹、全量门禁 54 项全 PASS。可选项（frontmatter 抽公共模块、ev 转义统一）留 fix-log 不动。详见 tools-fix-log.md 收官回填批次节。
> **S 类补齐批次记录（2026-10-03——§六清单外 3 条真实遗留全部清零）**：① 新建 `inject_test.py` v1.0（人工清单 M0-3/V23 fail-loud 注入测试——六批唯一未覆盖 S 缺口；V23-0 对照 + 三注入用例 + 原目录只读自证；官方解析器实弹 agent-skill-llm-review 5/5 全 PASS exit 0）；② 新建 `kw_locator.py` v1.0（B3-1 关键词定位器——W-08 降级句转备用；词表单一来源复用 security_scan V8-5；三技能实弹零命中声明正常）；③ 人工清单 §0 标注总表回写（S 待建 11→0，S 已实现 4→15，统计口径重写）。工具族 12 工具 + 1 门禁 + 11 套单测 147 组断言。详见 tools-fix-log.md S 类补齐批次节。
> **复检批次记录（2026-10-03——上批 2 未闭环清零 + 本批 5 新发现：5 改码 + 2 考证不实）**：check_skill v1.1.4（报告头补 VERSION）；inject_test v1.0.2（SKILL.md 读码 utf-8-sig 双点——main+_mutate，BOM 不误判且变异不失效【评审未点名的更深层缺口】/删死常量 NAME_PAT）；kw_locator v1.0.1（词表导入失败 exit 1 不静默——评审建议返空列表会伪造零命中声明，不采纳；docstring 声明扫描口径）。考证不实 2 条：_scan_files 的 is_symlink() 前置实为必要（is_file() 跟随符号链接）；两测试 shutil 均在用。11 套单测 151 组、全量门禁 66 项全 PASS。详见 tools-fix-log.md 复检批次节。
>
> **验证补全工程批次记录（2026-10-03——甲档两新工具建成入列）**：新建 `w_static_lint.py`（L-1~L-18 编写期静态补检）与 `eval_artifacts_check.py`（Q-1~Q-9 评测产物校验），各自过一轮外部评审（→v1.0.1）+ 独立自查轮（→v1.1）；validate_suite v1.1 挂载（write 阶段 + test 阶段）+ 四目标 dogfood；单测 11→13 套、断言 151→233 组，全量门禁 78 项 PASS。12 原工具 + local_gate 冻结未动，两新工具为新增文件，第 7 步双盘同步后入冻结管理。本文档文件清单已同步登记。
> **验收流程实操记录（2026-10-03——三技能全门组合复扫 + acceptance-report ×3）**：10 门 ×3 技能 = 30 门次零 FAIL；EX-1 复跑闭环实证（验收报告落盘→deliver_check WARN→PASS）。报告规范位 `.verification/acceptance-report.md`，分报告在 `.verification/acceptance/`；naming_precheck 排重口径=设计库（宿主部署副本同名系预期非冲突）。WARN 7 门均为留痕/历史 schema 类待人工。详见 tools-fix-log.md 验收流程实操批次节。
