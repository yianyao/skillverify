# 工具评审修复记录（tools-fix-log.md）

> **终态确认（2026-10-02 15:19，用户确认）**：check_skill.py v1.1d 为确认版——四轮外部评审 23 条全部闭环，单测 20/20、回归 8/8、V6 冒烟 5/5、实弹 exit 0。后续变更走冻结流程（README §冻结与变更流程）。

- 日期：2026-10-02
- 来源：外部评审意见（S-1~S-4 必改级 / P-1~P-7 建议级），对象为 `tools/host_compat.py` 与 `tools/smoke_runner.py`
- 回归依据：工具自身变更 → 按 X-C 规则触发 V6 冒烟回归

## host_compat.py

| # | 修复内容 | 状态 |
|---|---|---|
| S-1 | docstring 退出码改为"0=全 PASS；1=有 FAIL；2=仅 WARN"，与实现对齐 | ✅ |
| S-2 | in_host_session 改为通用判定（识别出任意已知宿主 OR 任一已知技能库存在），不再硬编码宿主名单；新增 `--host` 显式覆盖。验证：`--host "DeepSeek Harness"` 正确裁决为 B 路径 | ✅ |
| S-3 | frontmatter 解析改为显式提取第一个 `---` 行到下一个 `---` 行的块（frontmatter_block），并注明启发式边界、不替代 check_skill.py | ✅ |
| P-1 | detect_host 改为 HOSTS 表驱动，新增 DeepSeek Harness / Qwen Code（千问）/ 智谱 / 豆包（env+家目录启发式，注释标明按实际发行调整） | ✅ |
| P-2 | AGENT_CLIS 新增 dsh / pi / doubao / zhipu（注释：以各宿主实际 CLI 名为准） | ✅ |
| P-3 | 技能计数标注"仅扫一层"，嵌套库提示人工核对 | ✅ |
| 追加 | 修复过程中发现重写时遗漏 check_python()（NameError），已补回并回归 | ✅ |

## smoke_runner.py

| # | 修复内容 | 状态 |
|---|---|---|
| S-4 | C4 dry-run 改为精确匹配 CLI 参数定义（add_argument/--dry-run 字面量），并排除注释行 | ✅ |
| P-4 | C5 先判第二次调用超时（"第二次 --help 调用超时挂起"），不再把挂起误诊为输出不一致 | ✅ |
| P-5 | 跳过自身时打印提示行 | ✅ |
| P-6 | USAGE_HINTS 收紧：先去裸 "error"，最终仅保留 usage/用法/required/必需类——回归中发现 "NameError:" 崩溃栈仍会命中 "error:" 造成 C2 误判 PASS，故彻底移除 error 系关键词（教训已注释入码） | ✅ |
| P-7 | --out 落盘加 try/except，失败报 [FAIL] + 下一步提示并退出 1 | ✅ |

## 回归证据链（iteration-1/）

- smoke-run1.md：首轮（llm-review 脚本缺 --help，FAIL）
- smoke-run2.md：脚本修复后（余 host_compat C2 WARN）
- smoke-run3.md：2026-10-01 末版全 PASS
- smoke.md：2026-10-02 评审修复后最终版，26 项全 PASS，exit 0

## 遗留

- HOSTS 表中 DSH/智谱/豆包的 env 变量与家目录为启发式约定，未在真实环境验证（本机仅 WorkBuddy）；接入新宿主时以实际约定回填。
- 新增宿主的技能库路径（`.agents/skills` 等）为推测项，输出中已标注"请人工确认并回填"。

---

## check_skill.py v1.1（2026-10-02，外部评审 9 条全采纳）

- 来源：外部评审（S-1~S-4 + P-1~P-5），逐条与源码比对**全部属实**
- 对象：`tools/check_skill.py`（建成当日即评审，修订为 v1.1）

| # | 修复内容 | 状态 |
|---|---|---|
| S-1 | A6 行数口径改 `len(text.splitlines())`（编辑器/GitHub 口径，末尾换行不多计），注释标明口径 | ✅ |
| S-2 | SKIP 不再计入警告级 verdict（`has_warn` 只看 WARN），退出码 0 恢复可达 | ✅ |
| S-3 | A1 改真检测：`shutil.which("skills-ref")`；在场则实跑 validate（非零→WARN+人工复核注记），缺席才 SKIP | ✅ |
| S-4 | A6 增 V27 预警线 = 上限 80%（300→240 / 500→400），区间内 WARN 提示拆分评估 | ✅ |
| P-1 | A7 检测 `b"\r"`（同时覆盖 CRLF 与孤立 \r） | ✅ |
| P-2 | A8 提取前先剥离 `https?://\S+`，URL 片段不再误报为相对引用 | ✅ |
| P-3 | A11 缩进续行视为 YAML 多行值，不再误报"行无冒号" | ✅ |
| P-4 | A9 命中证据追加"文本级匹配可能误报，须人工复核"注记 | ✅ |
| P-5 | A2 早退时补 INFO 行"因 A2 FAIL，A3–A11 无法运行" | ✅ |

回归证据：
- `tests/test_check_skill.py` 扩至 15 组断言（新增 6 个 v1.1 回归点：孤立 \r、URL 剥离、多行 YAML、行数口径双断言、80% 预警线、整体 exit 0）→ ALL PASS
- `tests/test_regression.py` 8 组断言 ALL PASS（host_compat/smoke_runner 无回归）
- V6 冒烟 check_skill.py 5/5 PASS（`.verification/iteration-1/smoke-check-skill-v11.md`，D 盘 specSkill 侧）
- 实弹：agent-skill-llm-review 10/10 PASS，退出码 0（修复前恒 2）；v1.1 报告落 `format-gate-v1.1.md` 双盘同步（sha256 5fb003ce…）
- 留痕保护：v1.0 基线报告 `format-gate.md`（c48591a4）曾被 v1.1 复跑覆盖，已从 C 盘副本原样恢复，哈希核验一致

## 遗留（v1.1 追加）

- A1 实检路径未在本机验证（本机无 skills-ref）：`skills-ref validate <dir>` 调用形态按通用惯例写，接入官方 CLI 后首次运行须人工核对调用语法。

---

## check_skill.py v1.1b（2026-10-02，第二轮评审 6 条 [P] 健壮性全采纳）

| # | 修复内容 | 状态 |
|---|---|---|
| 2.1 | A10 f-string 内 `p.stdout.strip()` 改经 `(p.stdout or "")` 归一（`stdout_empty` 变量），防罕见平台 None → AttributeError | ✅ |
| 2.2 | X2 先判 `isinstance(data, dict)`，合法 JSON 但根为 list/str/num 时 WARN"根类型为 X，非对象"，不再崩溃 | ✅ |
| 2.3 | X2 读取 evals.json 补 `except OSError` → WARN"读取失败" | ✅ |
| 2.4 | A9 逐脚本 `read_text` 补 try/except OSError，读取失败跳过该脚本并在 evidence 提示 | ✅ |
| 2.5 | check() 对 `load_skill_md` 调用补 try/except OSError：读取失败记 A11 FAIL + INFO"后续检查未执行"后早退（避免 A6 以空文本误报 0 行 PASS） | ✅ |
| 2.6 | 总结论措辞分级：`；附 WARN（需书面评估）` / `；附 SKIP（仅记录）`，不再混称"人工书面评估" | ✅ |

回归证据：
- `tests/test_check_skill.py` 扩至 16 组断言全 PASS（新增 X2 根非对象 → WARN 不崩溃）
- `tests/test_regression.py` 8/8 PASS；实弹 agent-skill-llm-review exit 0，v1.1b 报告覆盖更新 `format-gate-v1.1.md` 双盘
- 2.3/2.4/2.5 的 OSError 路径在 Windows 夹具下不便稳定构造（chmod 语义不可靠），靠代码评审覆盖，未入单测——已注明

---

## check_skill.py v1.1c（2026-10-02，第三轮评审 3 条全采纳）

| # | 修复内容 | 状态 |
|---|---|---|
| 2.1 [S] | A9 读取失败不再假 PASS：`a9_level = FAIL if bad_a9 else (WARN if a9_read_err else PASS)`，evidence 标明"N 个脚本未检查到"——覆盖不全 ≠ 零命中通过 | ✅ |
| 2.2 [P] | 删 A8 `abs_misc` 的 `ref_pat.match` 二次过滤（盘符开头与 references|scripts|... 前缀不可能重合，纯死代码）。选方案二直接删除并注释：绝对路径一律 FAIL 是正确语义，不做目录名豁免 | ✅ |
| 2.3 [P] | 总结论 suffix 改列表拼接：WARN 与 SKIP 并存时并列展示"WARN（需书面评估）+ SKIP（仅记录）"，不再互相隐藏 | ✅ |

回归证据：
- `tests/test_check_skill.py` 扩至 **17 组断言**全 PASS——2.1 用"目录伪装 .py"夹具跨平台稳定触发 OSError（Windows Permission denied / Linux IsADirectoryError 均为 OSError 子类），修复 A9 读取失败路径此前无法单测的缺口
- `tests/test_regression.py` 8/8 PASS；实弹 agent-skill-llm-review exit 0，报告覆盖更新 `format-gate-v1.1.md` 双盘
- 2.3 位于 main() 报告装配层，经实弹报告人工核对措辞，未入单测

---

## check_skill.py v1.1d（2026-10-02，第四轮评审 5 条全采纳）

| # | 修复内容 | 状态 |
|---|---|---|
| 2.1 [S] | 解析前剥 BOM（`raw[3:]` if `\xef\xbb\xbf`），X1 专职报警——BOM 文件 A11 不再误报"frontmatter 区块缺失"，与 host_compat 的 utf-8-sig 口径对齐（采纳评审推荐方案，未用 evidence 加注替代） | ✅ |
| 2.2 [P] | URL 剥离扩展为 `(?:https?\|file)://\S+`。核实修正：评审称 `file:///C:/proj` 会被 abs_misc 捕获——实为否（lookbehind 见前置 `/` 拒绝），但 `file://.../references/g.md` 确会漏进 ref_pat 被当相对引用，修复方向正确 | ✅ |
| 2.3 [P] | A10 补捕 `OSError`（解释器无法启动等罕见场景），报"--help 调用失败"不崩整份报告 | ✅ |
| 2.4 [P] | A9/A10 合并为一次 `scripts_glob`，消除重复 glob | ✅ |
| 2.5 [P] | `_order` 补 `"INFO": 50`，INFO 行固定排 A11 之后、X 之前 | ✅ |

回归证据：
- `tests/test_check_skill.py` 扩至 **20 组断言**全 PASS——新增 BOM 夹具（A11 PASS + X1 WARN 双断言）与 file:// 夹具（A8 PASS 且"无引用"）
- `tests/test_regression.py` 8/8 PASS；实弹 agent-skill-llm-review exit 0，报告更新 `format-gate-v1.1.md` 双盘





---

# 第二轮修复（2026-10-02，联网核实 + 评审 2.1~2.8）

## 联网核实结论（宿主名称）

| 用户提法 | 核实结论 | CLI | 技能库路径 | 依据 |
|---|---|---|---|---|
| deepseek harness | ✅ 官方名 **DeepSeek Harness**（2026-08-13 v0.1 开发者预览，MIT，"Everything is a Plugin"，兼容 Anthropic 风格 SKILL.md） | `dsh`（npm @deepseek-ai/dsh） | 未获官方文档证实，保留启发式 | deepseek.com/harness、github deepseek-ai/deepseek-harness |
| herness | 系 harness 笔误，非独立宿主 | — | — | — |
| PI | ✅ **Pi Coding Agent**（earendil-works，pi.dev；注意与 Inflection 的 Pi 助手重名，编码语境指前者） | `pi`（npm @earendil-works/pi-coding-agent） | 支持 Skills/扩展，路径未核实 | pi.dev/docs |
| 千问 | ✅ **Qwen Code** | `qwen` | **~/.qwen/skills/**（个人）、.qwen/skills/（项目）——官方文档确认 | qwenlm.github.io/qwen-code-docs |
| 智谱 | ⚠️ 修正为 **智谱 ZCode**（官方 CLI；`.zhipu/.glm` 降为兜底启发式）；glmcode 为社区包非官方 | `zcode`（npm @zhipu/zcode） | 配置 ~/.zcode/cli/config.json；技能库路径待核实 | npm、51CTO 报道 |
| 豆包 | ⚠️ 编码代理形态为 **TRAE**；搜到的 doubao-cli 是 macOS 桌面会话自动化 CLI，非编码宿主 | `trae`（doubao 仅列示） | 启发式 | npm doubao-cli |

HOSTS 表/AGENT_CLIS 已按此更新（"智谱"→"智谱 ZCode"，CLI 增 zcode/glmcode/trae，doubao 标注非编码宿主）。

## 评审 2.1~2.8 修复

| # | 修复内容 | 状态 |
|---|---|---|
| 2.1 [S] | results 统一为三元组 list[tuple[str, str, str]]（check_skill_dirs 的 note 合并入口 add()），消除类型标注不一致 | ✅ |
| 2.2 [S] | any_skill_dir 改为从 HOSTS 表派生（for h in HOSTS for d in h['home']），不再与表不同步 | ✅ |
| 2.3 [P] | frontmatter_keys() 逐行顶层键集合判定（跳过注释/缩进行），排除 myname:/filename: 子串误报；负例/正例单测通过 | ✅ |
| 2.4 [P] | C4 检测前剥除三引号 docstring/字符串块再过滤行注释 | ✅ |
| 2.5 [P] | skill_dirs_for 兜底：非已知宿主且无已命中目录时探测 ~/.<host小写>/skills | ✅ |
| 2.6 [P] | VS Code 分支显式注明"无专属技能库" | ✅ |
| 2.7 [P] | C2 PASS 条件：评审自评"基本吻合，可接受"→ 不改，保持 v1.1 口径 | ➖ 维持 |
| 2.8 [P] | --json 输出补 "schema_version": "1.0" | ✅ |

## 回归

- host_compat 默认模式：WorkBuddy/路径 B/exit 2（与基线一致）；HOSTS 名单单测通过
- frontmatter_keys 负例（myname:/filename: 不误报）与正例单测通过
- V6 全量冒烟：PASS（exit 0），smoke.md 已更新

## 仍然遗留

- DSH/Pi/ZCode/TRAE 的 env 变量、家目录、技能库路径多数未获官方文档证实（Qwen Code 已确认），接入真实宿主时逐项回填
- C4 剥 docstring 是正则近似，复杂嵌套字符串场景理论上仍可绕过（评审亦认可 v1.2 候选级别）

## 第三轮（2026-10-02 晚）：意见 2.1/2.2/2.3 核实与修复

| # | 核实结论 | 修复 | 验证 |
|---|---|---|---|
| 2.1 [S] | **属实**：custom_guess 从宿主名派生，"DeepSeek Harness"→~/.deepseekharness、"智谱 ZCode"→中文路径、"豆包/TRAE"→多级目录，三例全部复现 | 新增 host_homes()：已知宿主从 HOSTS 表 home 列表取值，仅未知宿主按名字派生兜底 | 单测：三宿主候选集合==表内 home 全集；MyCustomHost→.mycustomhost 兜底正常 |
| 2.2 [P] | **属实**：--json 的 checks 用 `for l, m, *_` 丢掉 note，人工确认提示对 JSON 消费方不可见 | checks 改为 `for l, m, n`，输出补 "note" 字段 | 子进程跑 --json，断言全部 checks 含 note |
| 2.3 [P] | **属实但引例偏差**：第二条裸字面量正则确会误报（如 `print("使用 --dry-run")` 紧贴闭引号时命中），但评审给的 `logger.info("invoke with --dry-run to preview")` 因 flag 后有尾文**不会**命中；且 C4 仅影响适用性标注（level 恒 PASS），危害有限 | 删除第二条正则，C4 只认 add_argument 定义形态 | 单测负例（字面量提及→不适用）/正例（真实 add_argument→适用）双过 |

回归：host_compat 默认模式基线不变（WorkBuddy/路径 B/WARN）；V6 全量冒烟 PASS（exit 0），smoke.md 已更新。


## 第四轮（2026-10-02 10:3x）：意见 2.1~2.6（S 级 2 项 + P 级 4 项）

| # | 核实结论 | 修复 | 验证 |
|---|---|---|---|
| 2.1 [S] | **属实**：any_skill_dir 从 HOSTS 表 home 派生，Claude Code/Cursor 表内 home=[] → ~/.claude/skills 永远查不到；env 未识别时 Claude Code 用户被误降级 C 路径 | 采纳方案一（单一真源）：any_skill_dir = any(p.is_dir() for _, p, _ in skill_dirs_for(host))——skill_dirs_for 的 .claude/.workbuddy 分支本就是无条件目录探测，与宿主名解耦 | 单测模拟 fake home 只有 .claude/skills：detect_host 未识别 → skill_dirs_for 仍检出 → B 路径 True |
| 2.2 [S] | **属实**："DeepSeek Harness/智谱 ZCode/豆包/TRAE" 触发名单 + 排除名单是与 HOSTS 表脱节的第二处硬编码 | 推测分支条件改为查表：host_entry 有非空 home → 按表探测；未知宿主（非通用/VS Code）且无候选 → 名字兜底；新增 host_homes 表查询，新增宿主只改 HOSTS 一处 | 单测：三宿主候选==表内 home 全集；WorkBuddy/Qwen 与专用分支重叠路径已去重（恰好一次） |
| 2.3 [P] | **属实但修法需修正**：AGENT_CLIS 本身无重名，按名字 set() 去重无效；真问题是软链——两个名字解析到同一可执行文件 | check_agent_clis 按 which 结果 resolve 后去重，保留先出现者 | 单测模拟 zcode/zhipu 同路径 → found=['zcode'] |
| 2.4 [P] | **属实**：C4 只认 argparse，click 的 @click.option('--dry-run') 漏报（仅影响适用性标注，level 恒 PASS） | 增加第二条 option\( 形态正则（仍只认参数定义，不回到裸字面量） | 单测：click 正例判"适用"、负例（--verbose）判"不适用" |
| 2.5 [P] | **属实**：--host help 未说明"仅影响裁决与探测、任意字符串也触发 B" | help 文本补全三要点（不改实际能力/任意串触发 B/不支持的宿主应走 A 或 C） | --help 输出核验 |
| 2.6 [P] | **属实**：SKILL.md 无 --- 块时报"缺 name/description"不精准 | 先判 fm 为空 → 单独报"无 YAML frontmatter"；缺键另有其报错 | 单测：无块/缺键两类报错文案已区分 |

回归：host_compat 默认模式 exit 2（WARN 基线不变）；DSH --json → B 路径 + 2 条表驱动推测目录 + checks 含 note；V6 全量冒烟 PASS（exit 0），smoke.md 已更新。


## 第五轮（2026-10-02 10:4x）：意见 2.1~2.6

| # | 核实结论 | 修复 | 验证 |
|---|---|---|---|
| 2.1 [S] | **属实**：文本输出 `for l, m, *_` 吞 note——第三轮只给 --json 补了 note，文本路径漏同步（v1.1 引入的不一致） | 采纳方案一：`for l, m, n`，note 以 `← 前缀` 追加显示，保留信息分层 | 单测：DSH 文本模式输出含 "← 启发式探测" |
| 2.2 [P] | **属实但两方案均不可取，需裁决**：方案一（host!=通用终端 AND any_skill_dir）会把第四轮 2.1 的 S 级修复打回去——"env 缺失但真在 Claude Code 内"（应走 B）与"纯终端+残留目录"（应走 C）从脚本视角**完全不可区分** | 保留 B 判定 + 加强版方案二：该场景路径标注升级为 "B（半自动，待确认）"，advice 显式给出改走 C 的条件；已识别宿主场景 advice 不变 | 单测：fake home 场景 → "待确认"+"改走 C" 文案出现；WorkBuddy 正常场景无"待确认" |
| 2.3 [P] | **属实**：--json 是 print 到 stdout，docstring"落盘"不准确 | 改为"（--json 仅输出至 stdout）" | 单测：docstring 含新表述、不含"落盘" |
| 2.4 [P] | 按评审自评**维持不改**：与宿主名解耦是有意设计（多宿主切换核心价值），且标签已含宿主名 | 无代码变更，记录设计决定 | — |
| 2.5 [P] | **属实，有一行修法**（比"可忽略"更好） | `os.path.normcase()` 包裹 resolve 结果：Windows 规范化小写，其他平台 no-op | 代码变更；Windows 单机行为与 resolve 等价，无回归 |
| 2.6 [P] | **属实**：空 frontmatter（---\\n---）与无 frontmatter 共用 FAIL 分支 | 三分报错：不以 --- 开头 / 块为空（含未闭合）/ 缺键 | 单测五类文案（无块/空块/未闭合/缺键/正常）全部正确区分 |

**过程注记**：本轮复跑冒烟曾出现假 WARN——并行执行时临时测试文件 _test_r5.py 尚未删除即被 smoke_runner 扫描；删净后复跑 PASS（exit 0）。教训：临时测试文件应在跑回归**之前**清理，或放 tools/ 目录之外。

回归：host_compat 默认模式 exit 2（WARN 基线不变）；V6 全量冒烟 PASS（exit 0）。


## 第六轮（2026-10-02 10:5x，最终轮）：意见 2.1~2.5

| # | 核实结论 | 修复 | 验证 |
|---|---|---|---|
| 2.1 [S] | **属实**：Cursor env 被识别但无目录探测分支，推测分支因表内 home=[] 不触发；env 未识别时 Cursor 用户被误降级 C | **修正评审方案一**：显式探测分支照加（host=="Cursor" or 目录存在，覆盖两场景），但 HOSTS 表 home 特意保持空——~/.cursor 兼作 Cursor 编辑器配置目录，若入表会让装过编辑器的机器被 detect_host 误判（表遍历中 Cursor 先于 WorkBuddy） | 单测：--host Cursor → 报告预期路径；fake home 场景 → 检出且检测不被 ~/.cursor 劫持 |
| 2.2 [P] | **属实**：BOM 开头的 SKILL.md 会被误报"无 frontmatter" | read_text 改用 encoding="utf-8-sig" 自动剥 BOM（比手工 [1:] 更稳，且与常见 check 脚本口径一致） | 单测：BOM 文件 PASS |
| 2.3 [P] | 按评审判定：不对称是有意的 | 仅加注释说明"显式 --host 时即使目录不存在也报告官方预期路径，请勿修复成对称" | — |
| 2.4 [P] | **属实**：read_text OSError 未捕获会崩溃丢结果 | try/except OSError → FAIL + "请检查文件权限" | 单测：mock OSError → FAIL 不崩溃 |
| 2.5 [P] | **属实**：.lower() 在大小写敏感 FS 会误合 ~/Skills 与 ~/skills | 去重键改 os.path.normcase()（与 check_agent_clis 口径统一） | 代码断言 + 平台语义 |

回归：host_compat 默认模式 exit 2（WARN 基线不变）；V6 全量冒烟 PASS（exit 0）。

## 收尾结论

六轮评审（S-1~S-4、P-1~P-7、三轮 2.1~2.8/2.1~2.6/2.1~2.6、最终轮 2.1~2.5）全部闭环。host_compat.py 与 smoke_runner.py 自本轮起**冻结功能变更**，转入 E/M 阶段验证；后续如需改动按 X-C 触发 V6 回归并在本文件追加轮次记录。


## 豁免口径（2026-10-02 11:1x 用户确认生效）

host_compat.py 与 smoke_runner.py 作为 S 工具链脚本，**豁免 D 门与 W 组评审**，条件如下：

1. **形态限定**：保持"无 SKILL.md 的裸脚本"；一旦包装成技能（带 SKILL.md 进入技能库），自动恢复受 D/W 管辖
2. **补偿控制**：
   - 冻结 + X-C 变更触发 V6 全量冒烟并留痕（已生效）
   - `tools/tests/test_regression.py` 固化单测随工具分发（本轮落地）
   - 冒烟报告附原始证据行，人工签认时抽查至少一条（已具备）
   - 首次接入真实新宿主时强制实测一次 host_compat（待办）
3. **留痕定位**：本口径作为 M1 终检的检查项之一

文档：`tools/README.md`（说明）/ `tools/OPERATIONS.md`（操作，含何时执行/执行目的/执行影响）。
## security_scan.py v1.0（2026-10-02，S1① V8 安全扫描器建成——待办 S1 首项）

> 承载方式裁决（用户拍板）：**新建独立脚本**（非扩展 check_skill.py）。理由：V8 扫描面=全包文本文件，与 A 门（SKILL.md+scripts/*.py）结构不同；不触碰已冻结的 check_skill.py v1.1d，零回归风险；与 M1-S 表"A 门复跑 + 安全扫描"两行并列结构对齐，符合工具族"一工具一门"惯例。

### 检查项（V8 全覆盖）

| 项 | 内容 | 总表依据 |
|---|---|---|
| V8-1 | secret 正则库 8 类（AWS/GitHub/OpenAI/Slack/Google/私钥块/JWT/通用赋值型）+ 占位符降噪 | §9.6 |
| V8-2 | 熵检测：长度>=20 且香农熵>=4.5（阈值设计排除 hex 哈希——hex 每字符熵上限 4.0） | §9.6（V8 补手段） |
| V8-3 | 端点提取与 compatibility 声明 + --allow-url 白名单比对；未声明即 FAIL（不降 WARN） | §9.2 静态 + §9.9 |
| V8-4 | 多语言交互 8 类模式（与 A9 同清单），扫描面扩展到全包 | §8.3.1（补强 A9 限界） |
| V8-5 | 破坏性关键词 13 词命中代码文件而无 --confirm/--force/--dry-run → FAIL | §8.3.10 静态 |
| V8-6 | 危险指令关键词（绕过/跳过确认、静默上传、权限扩张等，含"用户"插入变体） | §9.8 关键词部分 |

### 设计要点（三级语义 + 两项纪律）

- **两级命中语义**：代码文件（scripts/ 目录 + 代码扩展名）命中 → FAIL；文档文件命中 → WARN（人工复核，如 W-15 提示词自身列举违禁词属合规表述）。V8-3 端点例外：文档链接同样记未声明，豁免走 --allow-url 留痕不降级
- **扫描面纪律**：跳过 .git/.verification/__pycache__/node_modules/venv 与二进制扩展名黑名单（宁可误扫不漏扫）、>2MB 超限跳过并计数；.verification 是工具留痕非交付物
- **覆盖不全不假 PASS**（对齐 check_skill v1.1c 2.1）：读取失败 → 覆盖行 WARN + 全部零命中 PASS 行降 WARN，exit 不得为 0
- **退出码 0/1/2 工具族约定**（全 PASS / 有 FAIL / 仅 WARN）；报告 markdown 表式与 check_skill 同型，--out 落 .verification/m1-s/security-scan.md
- 仅标准库、零第三方依赖、零网络；self-contained（不 import check_skill，保持工具独立冻结）

### 验证闭环

1. `tests/test_security_scan.py` **11 组断言全 PASS**（合规夹具全绿、六类缺陷各自响亮命中、占位符降噪计数、hex 不误报、--allow-url 豁免、两级语义、.verification 跳过、覆盖不全降 WARN、退出码 0/1/2 子进程级验证 + --out 落盘）
2. V6 冒烟 5/5 PASS（C1–C5，smoke_runner 机械项）
3. 既有回归零影响：test_check_skill.py 20/20、test_regression.py 8/8
4. **实弹**：agent-skill-llm-review（13 文件）——V8-1/2/3/4/5 全 PASS，V8-6 WARN 3 处=w-prompts.md:187 W-15 提示词合规表述，exit 2（预期，**人工复核点：建议采信为合规**）；agent-skill-trigger-eval（6 文件）全 PASS exit 0
5. 正式报告落 `.verification/m1-s/security-scan.md`（宿主库侧，双盘同步）

### 遗留声明

- secret 正则库与危险关键词均为**示例清单可扩展**口径（与 §8.3.10 条文一致）；熵检测为启发式，hex 编码 secret 依赖 V8-1 正则库覆盖（AKIA/Google 等已含 hex 形态）
- V8-6 对 llm-review 的 3 处 WARN 为工具预期设计（文档提及≠违规），是否采信由人工签认
## security_scan.py v1.0.1（2026-10-02，首轮外部评审 9 条：8 属实采纳 + 1 补文档）

| # | 严重性 | 核实 | 处置 |
|---|---|---|---|
| 1 | 高 | **属实**：短密钥（AKIA 20 字符等 <48）经 `m.group(0)[:48]` 完整入报告，落盘 .verification 有二次泄露面 | `mask_secret()` 首尾保留式脱敏（4+4+长度），V8-1/V8-2 证据统一走该口径；单测断言报告不含完整密钥但含 AKIA 特征 |
| 2 | 高 | **属实**：`url.startswith(a)` 前缀匹配放行 https://example.com.evil.io；compatibility 声明分支同病 | URL 形态条目一律解析 netloc 做主机边界（== 或 endswith"."），带路径再补路径边界（/v1 不匹配 /v1evil）；单测 5b/5c/5d 三组边界断言 |
| 3 | 中 | **属实**：读取失败 append 进 V8-1 hits → FAIL 且证据是"读取失败"，"扫出密钥"误读 | 读取失败移出 V8-1，独立 **COV 覆盖行**（WARN）承载；V8 各行仅由真实命中定级，覆盖不全仍使零命中行降 WARN + exit≠0；单测断言"读取失败（"细节只出现在 COV 行 |
| 4 | 中 | **属实**：`"无 --confirm" in it[2]` 判定与消息文本耦合 | V8-5 条目改 4 元组（末位 protected 布尔位），判定消费布尔位；fmt 只消费前三位 |
| 5 | 低 | **属实**：折叠标量 `compatibility: >` 续行 URL 漏提取 → V8-3 假阳性 | load_frontmatter 缩进续行并入上一个顶层键；单测 10b 断言折叠声明放行 |
| 6 | 低 | **属实（有意设计未声明）**：scripts/ 任意扩展名按代码判 | 保持行为，docstring 显式声明"可执行邻接位宁可误报不漏报"及豁免路径 |
| 7 | 低 | **属实**：symlink 跟随读取技能目录外目标 | `p.is_symlink()` 跳过并计数入 COV；单测 10c（无权限环境条件跳过） |
| 8 | 低 | **属实**：无版本标识 / group(1) 未过 md_escape / 关键词逐词 re.search | VERSION="v1.0.1" 入报告头；key 过 md_escape；DESTRUCTIVE_WORD_RE 单次预编译 |
| 9 | 低 | **属实**：input( 命中 reinput(/my_input(；read -p 漏 read -rp | INTERACTIVE_PAT 改 (label, 预编译正则)，调用型加 `(?<!\w)` 前置断言，read 改 `-\w*p` 组合形态；单测 6b 断言 |

### 运行期事故记录（v1.0.1 收尾时发现，非代码缺陷）

v1.0.1 首次复扫 llm-review 报 1/6 FAIL——根因：**本轮新建的 C 盘 tools 镜像位于技能目录内**，扫描器把工具链测试夹具（AKIA 假密钥/高熵串/示例 URL/input( 常量表）当成交付物。处置：镜像迁出至 `C:/Users/yianyao/.workbuddy/skill-tools/`（"C 盘工具链"自此指向该路径），**不改扫描面纪律**——第三方技能自带 tools/ 目录属交付物应当被扫，加白名单会给 V13 审计场景制造盲区。复扫恢复 5/6 PASS + V8-6 已知 WARN（w-prompts W-15 合规表述），exit 2。

### 回归证据

- `tests/test_security_scan.py` 扩至 **15 组断言**全 PASS（新增：脱敏、主机/路径边界、前置断言、折叠标量、symlink 条件测试、COV 语义）
- test_check_skill.py 20/20、test_regression.py 8/8（零影响）；V6 冒烟 PASS
- 实弹：llm-review exit 2（仅已知 WARN）、trigger-eval exit 0
## security_scan.py v1.0.2（2026-10-02，第二轮外部评审 6 条：4 改代码 + 2 补文档）

| # | 严重性 | 核实 | 处置 |
|---|---|---|---|
| 1 | 低 | **属实**：v1.0.1 评审 9 只给调用型 3 类加了 (?<!\w)，getpass/inquirer/prompt_toolkit 仍是裸子串（命中 mygetpass/reinquirer/prompt_toolkits），同函数内 5/8 严 3/8 松 | 三类统一 `(?<!\w)…\b`；单测 6b 扩 mygetpass/disinquirer/prompt_toolkits 负例 + getpass 真实调用正例 |
| 2 | 低 | **属实**：`read\s+-\w*p` 的 \w* 含数字/下划线，误中 read -3p 及不存在的 read 选项组合 | 收紧为 `\bread\s+-[a-zA-Z]*p\b`；单测 6b 加 read -3p 负例（-rp/-sp 正例已有） |
| 3 | 低 | **属实**：mask_secret 首尾 4+4 对 20 字符密钥泄露 8 字符（40%） | tail 4→2（对齐 GitHub 前 4 / AWS 末 4 惯例，泄露面 8→6）；单测 1b 加"尾段不得含 MPLE/NN7EX"断言 |
| 4 | 低 | **属实（隐性设计决策）**：声明 api.example.com 自动放行子域，未成文 | url_allowed docstring 显式声明口径（声明域含全部子域，_host_matches 承载；--allow-url 同口径；未来需精确匹配应加开关而非改 _host_matches） |
| 5 | 低 | **属实（语义未声明，非缺陷）**：断链符号链接 is_file() 即 False 不入统计，n_symlink_skipped 仅计有效链接 | scan 内 COV 注释显式声明该语义 |
| 6 | 低 | **属实**：COV 行用全角"；"连接，其它行用 ASCII "; " | 统一为 "; " |

### 修订过程记录

- docstring 写入 `(?<!\w)`/`-\w*p` 字面量触发 SyntaxWarning（非 raw 字符串），已转义 `\\w` 消警（`-W error::SyntaxWarning` 导入验证通过）
- 回归：test_security_scan 15 组、test_check_skill 20 组、test_regression 8 组全 PASS；V6 冒烟 PASS
- 实弹：llm-review exit 2（仅 V8-6 已知 WARN=W-15 合规表述，3 处）、trigger-eval exit 0
## naming_precheck.py v1.0（2026-10-02，S1② V2 命名冲突预检器建成）

> 承载方式：**新建独立脚本**（沿 S1① 同款"一工具一门"惯例，不触碰冻结的 check_skill.py）。V2 条目（[M] 设计期）：目标技能库中无同名 name、无高度重叠 description（余弦 >0.85 或关键词重叠 >0.6 告警，可调）。

### 检查项

| 项 | 内容 | 依据 |
|---|---|---|
| V2-1 | 同名 name 检索（大小写不敏感）+ 目录名冲突（name 必须与目录名一致，目录撞名等价撞名；目录检索不依赖 frontmatter 解析）→ FAIL | 方案 V2 + 总表 §1 第 2 条 |
| V2-2 | description 余弦相似度 top-1 >0.85 → WARN（告警级） | 方案 V2（默认阈值，--cos-threshold 可调） |
| V2-3 | description 关键词重叠（Jaccard=交集/并集）>0.6 → WARN | 方案 V2（--overlap-threshold 可调） |

### 设计要点

- **双输入模式**：设计期（立项前目录不存在）用 `--name/--description` 直接输入；也可传技能目录（SKILL.md 取值，name 缺失以目录名兜底）
- **相似度口径（启发式，docstring 显式声明）**：分词 = ASCII 词元 + CJK 二字元（不取单字防虚字淹没）；余弦=计数向量，重叠=Jaccard；误报漏报由人工复核，不替代 V12/V1 语义判断
- **降级语义精确化**（开发期单测暴露后修正）：不可解析条目的**目录名仍参与 V2-1**（目录扫描不依赖解析），解析缺口只降相似度行（V2-2/V2-3）；不可达库影响全部行。目标无 description → 相似度不可验，WARN 不假 PASS
- **自排除**：目标目录位于库内时按 resolve 路径排除自身（自比相似度恒 1.0 无意义）
- **多库支持**：--library 可重复；退出码 0/1/2 工具族约定；仅标准库 self-contained

### 验证闭环

1. `tests/test_naming_precheck.py` **12 组断言全 PASS**（分词口径、合规全绿、同名三类 FAIL、余弦/Jaccard 告警、阈值可调、两类覆盖缺口、自排除、目录模式、退出码子进程级 + --out + 缺参报错）
2. V6 冒烟 5/5 PASS（C1–C5）；既有回归零影响（security_scan 15 + check_skill 20 + regression 8）
3. **实弹**：llm-review / trigger-eval / quality-ab 三技能对宿主库各扫——全 PASS exit 0；自排除验证通过（llm-review top-1=trigger-eval 余弦 0.308，库内最高 0.328 远低于 0.85）；报告落 `.verification/m1-s/naming-precheck.md`（三技能）
## naming_precheck.py v1.0.1（2026-10-02，首轮外部评审 7 条全属实：5 改代码 + 2 补文档）

| # | 严重性 | 核实 | 处置 |
|---|---|---|---|
| 1 | 中 | **属实**：V2-2/V2-3 证据写 `top-1:` 但 top3() 拼 3 项，读者会误读为"任一超阈值告警" | 证据改双段：`top-1 **name=值**（判定取第 1，超阈值即告警）；前 3 名: ...`——判定值加粗单列，明细明确为"前 3 名" |
| 2 | 中 | **属实**：CJK bigram 的"相邻"= 抽取序列相邻（findall 丢弃中间非 CJK 字符，"评审 Agent Skill 的"产出"审的"跨段伪 bigram），docstring 未声明 | docstring 显式声明口径（有意行为）；测试 0 加跨段断言固化防无声变更 |
| 3 | 低 | **属实**：--name "../etc"/"a/b" 构造越界路径喂 cand.is_dir()（只读危害有限，但报告展示越界路径且与 V2 name 规范脱节） | main() 入口 `re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*")` 预检，不符 return 1 并提示 §1 规范；测试 11 加 ../etc 与 a/b 两负例 |
| 4 | 低 | **属实**：skill_dir 与 --name/--description 同传时后者静默忽略，docstring 未声明优先级 | docstring 写明"skill_dir 优先"；检测到组合打 stderr 提示（不静默） |
| 5 | 低 | **属实（机制层，优先级最高）**：argparse required=True 缺参 SystemExit(2) 与 WARN 码 2 撞码——编排器会把参数错误当"不阻断"放行 | 去掉 required=True，main() 自查缺 --library 返回 1（FAIL 阻断码）；测试 11 断言从"非零"收紧为"==1"；docstring 退出码行同步声明 |
| 6 | 低 | **属实**：同名+同目录时 V2-1 证据完整路径出现两次（name 条目内 1 次 + dir 条目 1 次） | name_collisions 改 (name, dir) 元组，dir_collisions 按路径集合去重；测试 2 断言路径恰好出现 1 次 |
| 7 | 低 | **属实（语义未声明 + UX 指引缺失）**：scan_library 的 unparsed/skipped_dirs 区分未成文；无 description 设计期必 exit 2 无指引 | scan_library docstring 补"无 SKILL.md 系有意排除不计覆盖缺口"；docstring 退出码节补"description 未定稿建议先成草稿再预检或走人工复核" |

### 修订过程记录

- 证据拼装首版误写坏表达式（walrus 残留），当轮发现当轮修正为 name_evs/dir_evs 清晰实现
- 回归：test_naming_precheck **12 组**（扩 3 断言）、security_scan 15、check_skill 20、regression 8 全 PASS；V6 冒烟 PASS
- 实弹：llm-review / trigger-eval / quality-ab 三技能复扫全 PASS exit 0；新 top-1 文案与优先级提示按设计呈现（库内最高余弦仍 0.328）
## token_budget.py v1.0（2026-10-02，S1③ V11 token 口径 + V17 预算门建成）

> 承载方式：新建独立脚本（一工具一门惯例）。V11 [M]：token 计数统一口径（宿主 tokenizer 优先，chars/4 保守兜底，CI 固定同一实现）；V17 预算门 W-S §3 各行中未被 check_skill A6 覆盖的预算项。

### 检查项

| 项 | 内容 | 依据 |
|---|---|---|
| V11-1 | SKILL.md 正文 token 估算 <5000（官方 [M]），ceil(字符/4) 固定口径，CJK 占比 >30% 证据内提示人工关注 | V11 + 总表 §3 |
| V17-1 | 元数据（name+description）token ≤100（项目级收紧，官方 [S]），缺失 WARN 不假 PASS | V17 项目收紧 |
| V17-2 | 扩展层 references/ assets/ 单文件 ≤500 行（项目级收紧，官方 [P]），scripts/ 不属扩展层 | W-S §3 行 |
| V17-3 | SKILL.md 行数 INFO（<300 判定归 check_skill A6，≥240 V27 预警线提示），不重复判定 | 职责边界声明 |

### 设计要点

- frontmatter 剥离后才计正文 token（与 naming_precheck v1.0.1 同源解析口径：BOM/续行合并）；行数口径与 A6/A7 同源（\n 计数、剥孤立 \r）
- symlink 跳过；覆盖不全不假 PASS（读取失败 → COV WARN + PASS 行降 WARN）
- 退出码 0/1/2；缺参/非法参数自查返回 1（argparse exit 2 撞 WARN 码教训全工具对齐——skill_dir 位置参数亦自查）
- 验证闭环：tests/test_token_budget.py **13 组断言**全 PASS（ceil 口径/frontmatter 剥离/三类超限/scripts 豁免/阈值可调/CJK 提示/覆盖纪律/退出码含非法参数）；V6 冒烟 PASS；既有回归 12+15+20+8 零影响
- 实弹三技能全 PASS exit 0：llm-review 正文 844 tok/元数据 87 tok、trigger-eval 835/93、quality-ab 690/95——**人工关注点：三技能元数据均逼近 100 收紧线**（CJK 占比 42–54%，chars/4 口径实际偏低估，真实宿主 tokenizer 计数更高）

## naming_precheck.py v1.0.2（2026-10-02，自检发现 v1.0.1 引入 V6 冒烟 C2 回归——修复）

- **回归**：v1.0.1 评审 5 把 --library 的 argparse required=True 改为自查返回 1 后，自查消息只含"错误/下一步"、**缺"用法"提示**——V6 冒烟 C2（无参调用报错须含用法提示，USAGE_HINTS 认 usage/用法/required）从 PASS 降 WARN。这是改退出码路径时未复跑冒烟的疏漏（S1③ 冒烟顺带暴露）。
- **修复**：缺参自查消息补"用法:"行（含两种调用形态）；同款口径同步 token_budget.py（其 skill_dir 位置参数缺参原也走 argparse exit 2，一并自查返回 1 + 用法提示）。
- 验证：test_naming_precheck 12 组、test_token_budget 13 组全 PASS；两工具 V6 冒烟 C2 回 PASS、总结论 PASS。
- **教训入档**：改任何退出码/报错路径必须复跑 V6 冒烟全项（C2 的"报错带用法"是机械可判定契约）；自查报错消息必须含用法提示。
## token_budget.py v1.0.1（2026-10-02/03，首轮外部评审 6 条：4 改代码 + 2 按结论保留）

| # | 严重性 | 核实 | 处置 |
|---|---|---|---|
| 1 | 中 | **属实**：无 SKILL.md 早退 stats 只含 read_err/ext_files，缺 body_tokens/meta_tokens——下游调用方 KeyError 风险 | 早退 stats 补齐四键（body_tokens=0/meta_tokens=0）；测试 9b 扩四键断言 |
| 2 | 中 | **属实**：count_lines 失败时 V17-3 静默消失（`if body_lines is not None`），审查者找不到行 | 失败分支补 V17-3 WARN 行（"行数不可验，A6 判定交由 check_skill.py 复核"）；测试 9 断言 V17-3 在场且 WARN |
| 3 | 中 | **属实（按结论保留）**：meta_text 含 1 个连接空格 ≈0.25 token；V17 原文口径即 name+description 合并 | 行为不变，加注释固化"合并口径与规格一致，不做仅 description 口径"防后续误改 |
| 4 | 低 | **属实**：测试 10 `fat_meta :=` 赋值即弃 | 清理为普通表达式 |
| 5 | 低 | **属实（按比建议更彻底的修法处置）**：--chars-per-token abc 等 argparse 类型转换错误走内部 error() → exit 2 撞 WARN 码。评审建议 docstring 记一句，但既定撞码纪律（naming_precheck v1.0.1 评审 5）优先级更高且修法简单——**覆写 ArgumentParser.error() 统一 exit 1**，覆盖全部解析错误（含未知旗标），usage 提示照常输出（V6 冒烟 C2 认 usage 关键词不受影响） | 两工具同修；token_budget 测试加 --chars-per-token abc / --body-budget abc 断言 |
| 6 | 低 | **属实（按结论保留）**：build_report 传整个 args 与其他工具风格不一 | 不改，纯风格差异无功能影响 |

**naming_precheck.py v1.0.3（同轮联动）**：#5 同源问题（--cos-threshold abc → exit 2）一并修——同款 error() 覆写；测试 11 加 --cos-threshold abc 断言。docstring 退出码段两工具同步声明"所有参数错误统一 exit 1"。

### 回归证据

- test_token_budget **13 组**（9b 扩 stats 四键、9 扩 V17-3 WARN、10 扩两类型错误断言）、test_naming_precheck **12 组**（扩类型错误断言）全 PASS
- 既有回归零影响：security_scan 15 + check_skill 20 + regression 8
- V6 冒烟双工具 5/5（C2 确认 exit=1 且报错含用法提示——error() 覆写未破坏 C2 契约）
- 实弹六扫全 exit=0（token-budget ×3 + naming-precheck ×3），报告版本行 v1.0.1/v1.0.3 已刷新
## eval_discipline.py v1.0（2026-10-03，S1④ V21/V28/V29 评测纪律三件套建成）

> 承载判定（按 §3 手段表核）：V21 H/S 的机械半（时间戳核对；"未提前定义 PASS/FAIL"语义归 H）、V28 S（哈希比对）、V29 S/C（基线记录+比对）——均机械可判，纯脚本成立无需 K 编排。**合一工具**（非三脚本）：三门同属 E/X 阶段评测与迭代留痕纪律、输入同源（评测产物+基线文件），沿 token_budget.py（V11+V17 两门合一）先例。check（默认）/record 双模式。

### 检查项（三门全维）

| 项 | 内容 | 依据 |
|---|---|---|
| V21-1 | 评测集在场+用例数：evals.json 解析（cases/assertions/queries 三形态识别）；当前数记 INFO——"初始 2–3 条"为流程纪律，终态无法机械验证初始值，须 run-log 留痕佐证（语义归 H）；缺失/解析失败 FAIL | §7.1.1/§7.1.5 [M] |
| V21-2 | 断言时机：优先显式 `assertions_added_at` 字段；mtime 启发式兜底（evals.json mtime 晚于 workspace 首轮 outputs 最早文件；证据内显式声明 mtime 可被复制重置的局限）；断言形态未提供 workspace / 非断言形态（queries）→ SKIP 不计警告 | §7.1.6/§7.4.5，E-H 行 S 半 |
| V28-1 | 写回一致性：--description-final 文件 / --description-text 文本 vs frontmatter description 逐字符比对（SHA256）；未提供 → SKIP（未做 description 优化轮属常态） | §6.5.7（V28 [S]） |
| V29-1 | 基线在场：.verification/.iteration-baseline 解析 + 必填字段（iteration/accepted_at/version）校验；缺失 WARN（是否已过验收归人工判断——不假 PASS 亦不误阻断） | §15.4（V29 [S]） |
| V29-2 | 防覆盖比对：基线含 snapshot 块（record 生成：快照目录逐文件 SHA256）→ 逐文件比对现状，删除/改动/基线外新增均 FAIL；旧式键值基线（llm-review M 阶段形态，哈希外引）→ SKIP + 提示 record 升级 | §15.4（V29 [S]） |

### 设计要点

- **record 模式**：写增强基线（键值头 + snapshot JSON 块），record→verify 机械闭环；兼容既有旧格式（键值头照常解析）
- **SKIP 不计警告**（对齐 check_skill A1 SKIP 口径）：三门大量场景依赖依据提供与否，SKIP 须人工留痕佐证、不豁免上游条款（报告头显式声明）
- 退出码 0/1/2；全部参数错误（缺参/非法值/互斥/路径不存在）经 _BlockArgParser 统一 exit 1（撞码纪律全工具对齐）；C2 用法提示口径
- **开发期自测暴露两缺陷当轮修复**：① 基线键解析沿用 FM_KEY_RE（不含下划线）把 accepted_at/snapshot_sha256_skill_md 全解析丢——旧格式兼容性破坏，改 BASELINE_KEY_RE；② record 行内 JSON 与解析器"独立行+缩进块"口径不匹配，record→verify 闭环断裂——record 改独立行+缩进，解析器两形态兼容
- **单测自身暴露夹具时序污染**：篡改恢复用例重写文件把 mtime 重置为当下，污染 V21-2 时序前提——恢复须内容与 mtime 双恢复（教训：mtime 基断言的夹具，任何写操作后必须同步回拨）

### 验证闭环

1. `tests/test_eval_discipline.py` **12 组断言**全 PASS（record→check 闭环、evals 缺失/坏 JSON、mtime 两向 os.utime、显式字段早晚两向、queries 形态、V28 三态、旧格式兼容、基线缺失、篡改/新增 FAIL、退出码 0/1/2+record CLI+六类参数错误）
2. V6 冒烟 5/5 PASS；既有回归零影响（13+12+15+20+8）
3. **实弹三技能**：llm-review exit 0（queries 形态 12 条→V21-1 INFO/V21-2 SKIP；旧格式基线 V29-1 PASS iteration 1/v1.3；V29-2 SKIP 建议 record 升级）；trigger-eval/quality-ab exit 2——V29-1 WARN 基线缺失，**考证后确认非缺口**：两技能 evals.json meta 明示查询集"待实测草案（未冻结）"，尚未进入 E 阶段验收，基线缺失属常态（WARN 正确提示人工判断，不应补 record——版本号与验收时点均无事实依据）
4. 报告落三技能 `.verification/m1-s/eval-discipline.md`

## eval_discipline.py v1.0.1（2026-10-03，首轮外部评审 7 条全核实：6 改代码+1 补注释）

| # | 级别 | 评审 | 处置 |
|---|---|---|---|
| 1 | 高 | snapshot_dir_files 用绝对路径 p.parts 判 SKIP_DIRS——祖先目录名（venv 等）命中即清空整个快照 → record 报"快照目录无文件"或 V29-2 全量假告警（基线外新增）；record 调用路径同病 | 属实必修：改 `p.relative_to(d).parts`（对齐同文件 earliest_output_mtime 的正确口径）。测试未暴露因 tmp 前缀 ed-test- 不含 SKIP_DIRS 名——新增夹具（快照置于 …/venv/… 下）固化，内部 venv/ 仍正确跳过 |
| 2 | 中 | ISO_TS_RE 允许无秒，但 Python 3.7–3.10 fromisoformat 要求 :SS → ValueError → 走"格式非法"分支误 FAIL（本机 3.13 掩盖） | 属实：新增 parse_iso_ts() 补秒归一（TS_PAD_RE 负向断言 `(?![\d:])` 防重复补已带秒/小数形态），非法仍返回 None。K 类档案未明确最低 Python 版本，按 3.10 兼容保守处置 |
| 3 | 中 | cases 结构存在但断言全空 → asserts=[] → `or None` → V21-2 误 SKIP"非断言形态" | 属实：parse_evals_shape 新形态 `cases-no-asserts`，V21-2 记 WARN"先补断言再评测"（不再与 queries 的"不适用"SKIP 混同） |
| 4 | 中 | record 缺 --snapshot-dir 静默产键值基线，与 docstring"追加 snapshot 块使 V29-2 具备机械比对依据"承诺不符 | 属实（行为明确性）：stderr 明示"V29-2 将 SKIP（无机械比对依据）+ 重落指引"，docstring 声明 --snapshot-dir 可选及不提供时基线形态 |
| 5 | 低 | parse_baseline 行内 JSON 兼容不完整：`snapshot:{…}`（无空格）不匹配 `startswith("snapshot: {")` → 走块形态 → json.loads("") 异常 → 整基线"解析失败" | 属实（record 自身不生成此形态，注释乐观）：重构 payload 识别——payload 以 `{` 开头即行内解析；`snapshot: <非JSON值>` 仍落普通键值（保旧行为） |
| 6 | 低 | --description-text "" → chosen="" → 与非空 fm_desc 判"不一致"FAIL，误导 | 属实：main fail-fast exit 1（参数错误撞码纪律口径），报错含下一步指引 |
| 7 | 低 | BASELINE_FIELDS_REQUIRED 缺"三项必填、其余可选"说明 | 属实（补注释级）：常量旁注释 + docstring 口径 |

### 验证闭环（v1.0.1）

1. `tests/test_eval_discipline.py` 12→**18 组断言**全 PASS（新增：venv 祖先目录快照不清空、parse_iso_ts 四向+端到端无秒 PASS、cases 空断言 WARN、record 缺快照 stderr 提示+键值基线、行内无空格 snapshot JSON、空 --description-text exit 1）
2. V6 冒烟 5/5 PASS（C2 仍 exit 1 带用法提示——撞码修复未回归）；既有回归 20+12+13+15+8 零影响
3. 实弹三技能复扫：llm-review exit 0 / trigger-eval、quality-ab exit 2（既证 WARN 基线缺失——与 v1.0 结果一致，零行为回归）；三技能 `.verification/m1-s/eval-discipline.md` 报告已刷新（工具版本 v1.0.1）

## dep_check.py v1.0（2026-10-03，S1⑤ §8.1.2/§8.2 依赖检测五项建成）

> 承载判定（方案 W-S 手段表四行全 S）：§8.1.2 版本固定（正则检索）、§8.2.1/§8.2.2 内联声明/禁 manifest（PEP 723/Deno/Bun/Ruby 检测）、§8.2.3 PEP 508 说明符、§8.2.4 清单交叉比对——均机械可判，纯脚本成立。独立脚本沿"一工具一门"惯例；检查项编号 **DEP-1~5** 为工具本地编号（V1–V29 已被 V 系列占用），映射在各行标题显式标注。

### 检查项（五项全维）

| 项 | 内容 | 级别 | 依据 |
|---|---|---|---|
| DEP-1 | 运行器/包管理调用（npx/bunx/uvx/pipx/pip/uv/deno/go run）包规格钉版三态：精确（pkg@1.2.3/==）PASS、范围（^~>*<）WARN、缺失 FAIL；代码 FAIL/SKILL.md 文档 WARN 两级语义 | [M] | §8.1.2 |
| DEP-2 | 内联依赖声明四语言：Python PEP 723 块（第三方导入经 sys.stdlib_module_names 机械判定+scripts 内本地模块豁免）/Deno npm:/jsr: 版本化/Bun pkg@ver/Ruby bundler/inline；缺失或不完整 FAIL | [M] | §8.2.1 |
| DEP-3 | 禁独立 manifest：package.json/requirements.txt/Gemfile/go.mod 等根与 scripts 命中 FAIL；pyproject.toml/setupcfg（常为工具配置）与 references/assets 夹具命中 WARN 人工甄别；Gemfile 命中附 §8.2.6 环境干扰提示 | [M] | §8.2.2+§8.2.6 |
| DEP-4 | 版本说明符固定：PEP 723 裸包名/缺 requires-python、npm:/jsr: 范围说明符、Ruby gem 未钉版本 → WARN | [S]/[P] | §8.2.3+§8.2.5 |
| DEP-5 | 脚本清单完备：scripts/ 实际文件 ⊆ SKILL.md 清单，缺列 FAIL；SKILL.md 提及不存在脚本 → WARN（陈旧或示例占位路径，人工甄别） | [M] | §8.2.4 |

### 口径声明（docstring 固化的机械初筛局限）

- Ruby 标准库无机械清单——非相对 require 一律按 gem 依赖保守口径（误报人工甄别）
- PEP 723 用正则抽 TOML 子集（tomllib 为 3.11+，项目按 3.10 兼容——沿 eval_discipline v1.0.1 评审 2 口径）
- 运行器行级词法扫描，注释行跳过；docstring/示例内命令可能误报，证据带 文件:行号
- 运行器选择与环境匹配（§8.1.5–§8.1.6/V22）、依赖实际可解析（M1-9）属 O 实测域，不在范围

### 验证闭环

1. `tests/test_dep_check.py` **10 组断言**全 PASS（合规全绿/无 scripts SKIP/PEP 723 缺失 FAIL/裸依赖 WARN/JS 三态/Ruby 两态/manifest 三判级/清单双向/DEP-1 并行判级/退出码 0/1/2+参数错误统一 1+--out）
2. V6 冒烟 5/5 PASS（C2 exit 1 带用法提示）；既有回归 20+12+13+15+18+8 零影响
3. **实弹三技能**：llm-review exit 2——唯一 WARN=DEP-5 陈旧清单启发式命中 SKILL.md 调用示例占位路径（`--inputs SKILL.md scripts/foo.py` 示例行，非清单条目，**考证后非缺口**，证据已补充"或调用示例占位路径"甄别提示）；trigger-eval/quality-ab exit 0 全 PASS（DEP-1/4 SKIP=无运行器调用与内联声明，DEP-2/3/5 PASS）；报告 `.verification/m1-s/dep-check.md` ×3
4. 开发期当轮修两处：①DEP-4 SKIP 条件漏计 Ruby gem 在场（gem 钉版场景被误 SKIP）→ 补 ruby_gems 旗标；②DEP-1/DEP-3 FAIL 行丢 WARN 明细 → WARN 项并列进证据（与工具族"证据可甄别"口径一致）

## dep_check.py v1.0.1（2026-10-03 同日首轮外部评审 7 条处置：5 改代码+1 补注释+1 测试清理）

> 评审 7 条全核实属实（2 高 2 中 2 低 1 极低），另核实中自抓 1 处伴生缺陷一并修。

### 处置明细

| # | 级别 | 处置 |
|---|---|---|
| 1 | 高 | `classify_pkg_spec` 新增 DIST_TAGS 黑名单（latest/next/beta/canary/rc/alpha/dev）——`pkg@latest` 原误判 pinned（ver[0] in "^~>*<" 只覆盖范围说明符），npm:/jsr: 分支与纯分支两处同修，dist-tag → ranged（DEP-1 代码 WARN/文档 WARN，DEP-4 WARN）；"latest 恰是永远漂移的典型违背，§8.1.2 不得判固定" |
| 2 | 高 | Bun 版本化导入分支改统一 `classify_pkg_spec` 判据——原来只计数不判级，`pkg@latest`/`pkg@^1.0.0` 静默计入 js_declared（DEP-2 PASS + DEP-4 消失），与 npm:pkg@^1.0.0 判 WARN 同语义不同判定违反单一判据；现在 unpinned → DEP-2 FAIL、ranged → DEP-4 WARN、pinned → 计入声明 |
| 3 | 中 | SKILL.md 缺失分支补 `n_read_err += 1`——原来 read_err_files 有内容但计数为 0，COV 判 INFO、PASS 降级不触发（DEP-5 已 FAIL 但 DEP-2/3 的 PASS 被当作可信结论），与工具族"覆盖不全 → COV WARN + PASS 降级"纪律相悖 |
| 4 | 中 | `first_spec` 新增取值旗标过滤（VALUE_FLAGS：-r/--requirement/-c/--constraint/-e/--editable/-i/--index-url/--extra-index-url/-t/--target/--prefix/-p/--package）——`pip install -r requirements.txt` 原取 requirements.txt 作包名误 FAIL（合法用法与 §8.2.2 禁 manifest 冲突，manifest 口径归 DEP-3）；`npx -p some-pkg some-tool` 原取 some-pkg，现取实际运行的 some-tool（评审指出同向但证据误导） |
| 5 | 低 | PEP723_PY_RE / PEP723_DEP_ITEM_RE 扩单引号（TOML 允许单引号字面量）——requires-python 单引号原漏报误 WARN |
| 6 | 低 | 运行器扫描局限 docstring 补句：Python 三引号 docstring / JS 块注释内示例亦可触发，证据行号自辩（评审⑦口径） |
| 7 | 极低 | 测试文件删除 `_LAST_ROWS` 全局变量残留（改局部 rows0；补正：levels(_LAST_ROWS) 实际有使用，全局赋值确无必要） |
| 附 | — | 伴生缺陷（评审未提）：纯分支 `pkg@`（尾随空版本）`ver[0]` IndexError → 补 `if not ver: return "unpinned"` 守卫（npm:/jsr: 分支原有同款守卫，纯分支遗漏） |

### 验证闭环

1. `tests/test_dep_check.py` 10→**14 组**全 PASS（新增：dist-tag 判级 + classify 六规格直测、Bun ranged/dist-tag → DEP-4 WARN、SKILL.md 缺失 COV WARN+PASS 降级、TOML 单引号抽取）
2. V6 冒烟 5/5 PASS（C2 exit 1 带用法提示）；既有回归 20+12+13+15+18+8 零影响
3. 实弹三技能复扫与 v1.0 零行为差异：llm-review exit 2（唯一 WARN=DEP-5 示例占位路径，前轮已考证非缺口）、trigger-eval/quality-ab exit 0

## deliver_check.py v1.0（2026-10-03，S1⑥ 存在性/schema 门七项建成——S 类收官）

> 承载判定（原始 S1⑥ 清单"存在性/schema 类（feedback/grading）"+ 收敛后 B1/license/M1-7）：存在性核对、JSON schema 校验、关键词留痕初筛均机械可判，纯脚本成立。七项合一独立脚本（沿 dep_check 合一先例）；检查项编号 **EX-1~7** 为工具本地编号（V1–V29 已占用），映射在各行标题显式标注。

### 检查项（七项）

| 项 | 内容 | 级别 | 依据 |
|---|---|---|---|
| EX-1 | 交付物存在性：SKILL.md + evals/evals.json 缺失 FAIL；acceptance-report.md 缺失 WARN（M1 时点项，W/E 阶段预期缺失） | [M] | §15.7/M1-7 |
| EX-2 | feedback.json 落盘+结构：双文档口径同认——A 操作手册/清单 text/passed/evidence（含列表形态）、B 总表 §7.7.4 键=用例目录名→文本（空字符串=通过）；空对象 WARN（逐用例留键）；不匹配 FAIL；未产出 SKIP | [M] | §7.7.4/E3-2 |
| EX-3 | grading.json schema：断言字段须 text/passed/evidence（缺 passed/非布尔 FAIL、缺 evidence WARN）、summary 须 passed/failed/total/pass_rate（键不符 FAIL、未见 WARN 门 D 类工件人工甄别）；未产出 SKIP | [M] | §7.2.6/E-S |
| EX-4 | license：frontmatter 字段长度启发式（>120 字符/块标量多行 → WARN 条款内嵌嫌疑）+ 随包 LICENSE 文件在场核对；均未声明 SKIP（对外交付 V15 升 [M]） | [S] | §2.4.1–2.4.2/V15 |
| EX-5 | 反向测试记录存在性：.verification/ md/txt 关键词"反向测试"初筛，未见 WARN（留档可能在技能树外素材档案） | [S] | §5.1.3/B1-1 |
| EX-6 | 执行→修订闭环记录：.verification/ 下 iteration-N 目录（含文件）在场核对，未见 WARN | [S] | §5.1.6/B1-2 |
| EX-7 | 执行轨迹分析记录：关键词"轨迹"初筛，未见 WARN | [S] | §5.1.9/B1-3 |

### 口径决策（fix-log 留档）

1. **feedback.json 双口径冲突消解**：总表 §7.7.4（键值文本）与操作手册/清单 E3-2（text/passed/evidence）并存且均为权威文档——工具两口径同认、证据标明命中格式，不擅自裁断；后续若规范收敛可收紧
2. **B1 三类记录无固定文件名约定**：清单 §0 口径"记录是否存在可脚本核对、结论裁决归 H"——关键词初筛 + WARN 人工确认，不用假 PASS
3. **验收报告降 WARN 不降 FAIL**：M1 时点项，W/E 阶段缺失属预期；SKILL.md/evals.json 为编写期产物缺失即 FAIL
4. **.verification/ 不进 SKIP_DIRS**（区别于 dep_check）——本工具的留痕扫描主域恰是该目录

### 开发期当轮修

- FM_LICENSE_RE `\s*` 跨行吞噬续行 → 限 `[ \t]*`；license_field 块标量（| >）视为已声明+续行计数（原误返回 None）；count_cont 跳过 license 行自身余量
- EX-3 判级补 elif warns → WARN 分支（无 FAIL 但有人工甄别项不得记 PASS）
- validate_feedback 补顶层数组形态（口径 A 列表）

### 验证闭环

1. `tests/test_deliver_check.py` **9 组断言**全 PASS（合规全绿/裸夹具三态/留痕域在场无内容 WARN/EX-1 FAIL/feedback 三态/grading 三态/license 三态/license_field 直测/退出码+参数错误统一 1+--out）
2. V6 冒烟 5/5 PASS；既有回归 20+12+13+15+18+14+8 零影响
3. **实弹三技能**：全部 exit 2 纯 WARN/SKIP 零阻断——EX-1 WARN=验收报告未出（M1 时点，预期）；EX-5 反向测试关键词均未见（留档在技能树外素材档案，人工确认项）；llm-review EX-6/7 PASS（iteration-1+轨迹留痕在案）；quality-ab EX-3 WARN=gate-d grading.json 无 summary 四键（门 D 类工件，按设计人工甄别）；报告 `.verification/m1-s/deliver-check.md` ×3

## deliver_check.py v1.0.1（2026-10-03 同日首轮外部评审 8 条处置：6 改代码+1 docstring+1 保留现状）

> 评审 8 条全核实属实（1 高 2 中 + 1 中弱改进 + 3 低 + 1 极低）。BOM 条经工具族交叉验证确认口径偏离：host_compat.py:233 用 utf-8-sig、test_regression.py:108 固化"BOM 应被剥除"断言。

### 处置明细

| # | 级别 | 处置 |
|---|---|---|
| 1 | 高 | **BOM 未剥**——`"\ufeff".isspace()` 为 False，`strip()` 剥不掉 → 首行 `"\ufeff---"` 判空 → frontmatter 整块丢失 → EX-4 假 SKIP（即便 license 已声明）。双保险修：SKILL.md 读入改 `utf-8-sig`（对齐 host_compat 族口径）+ `frontmatter_block` 起手 `lstrip("\ufeff")`（防调用方传未剥文本） |
| 2 | 中 | **validate_feedback B 口径过度宽松**——任意全字符串值 dict 判 B PASS（`{"name": "skill-x"}` 类元数据文件误命中无感知）。加弱约束 WARN：键名均无 `/` 或 `-` 分隔符时证据并入"疑似元数据文件须人工甄别"提示（不判 FAIL——B 口径本身合法，防误伤真实用例目录名） |
| 3 | 中 | **validate_grading summary 值类型不校验**——`{"passed": "1", ...}` 字符串数字键名齐即过。加弱类型检查：passed/failed/total/pass_rate 非 int/float（bool 显式排除）→ WARN"类型人工甄别"（规范仅约定字段名，故 WARN 不 FAIL） |
| 4 | 低 | **find_json_files 命中 references//assets/ 示例**——示例结构不规范会误 FAIL。新增 `is_sample_path()`：示例口径命中不判 FAIL 降 WARN 人工甄别（EX-2/EX-3 两处，对齐 dep_check DEP-3 对 pyproject/夹具的处置）；解析失败/结构违规均并入示例 WARN 明细 |
| 5 | 低 | **EX-6 `any(d.rglob("*"))` 空子目录绕过**——iteration-N/ 只含空子目录亦 PASS（rglob 返回目录条目）。改 `any(x.is_file() for x in d.rglob("*"))`，与 docstring"含文件"口径对齐 |
| 6 | 低 | **license_field 不报多 license 键**——`search` 只取首个，YAML 重复顶层键非法无感知。改 `finditer` 计数，签名扩三返回 `(值, 续行数, 是否重复键)`，EX-4 对重复键 WARN（取首个判定） |
| 7 | 低 | iter_vfiles 仅 .md/.txt——docstring 明示".log/.rst/.yaml 等漏检属关键词初筛局限"（口径声明补句） |
| 8 | 极低 | 测试组号中文注释——保留现状（评审自评"可保留"） |

### 验证闭环

1. `tests/test_deliver_check.py` 9→**14 组**全 PASS（新增：BOM 夹具 EX-4 PASS、B 口径无分隔键 PASS+证据提示、summary 字符串数值 WARN、references/ 示例违规 WARN 不 FAIL、重复 license 键 WARN；license_field 直测适配三元返回）
2. V6 冒烟 5/5 PASS（C2 exit 1 带用法提示）；既有回归 20+12+13+15+18+14+8 零影响
3. 实弹三技能复扫与 v1.0 零行为差异：全部 exit 2 纯 WARN/SKIP 零阻断（EX-1 验收报告 M1 时点 WARN、EX-5 初筛未见 WARN 等均按设计）

## deliver_check.py v1.0.2（2026-10-03 二轮追加评审 3 条处置：3 改代码）

> 评审 3 条全核实属实（均低档，一致性/完备性收口）。

| # | 处置 |
|---|---|
| 1 | **okn 死变量删除**——EX-3 循环 `okn = 0`/`okn += 1` 从未消费（PASS 分支用 `len(gr_files)`；PASS 场景样本口径必带 WARN，故 len 恰为全合规数，语义等价），删 2 行 |
| 2 | **entries[:20] 截断未标注**——超 20 条断言时加 WARN"仅检查前 20 条（另 N 条未检查）——全量核对须人工"，对齐 security_scan/dep_check 的"另 N 处略"族口径 |
| 3 | **summary-only 形态静默通过**——原 `not entries and "summary" not in data` 把"只有 summary 不列明细"排除在外；改 `not entries` 独立 WARN，证据区分两种形态（仅有 summary→"汇总须有明细支撑"；全不可识别→"结构人工甄别"） |

### 验证闭环

1. `tests/test_deliver_check.py` 14→**15 组**全 PASS（新增：summary-only WARN"不列明细"、>20 条断言 WARN 截断标注）
2. V6 冒烟 5/5 PASS；既有回归 20+12+13+15+18+14+8 零影响
3. 实弹三技能复扫与 v1.0.1 零行为差异：全部 exit 2 纯 WARN/SKIP 零阻断（报告刷新 v1.0.2）

## T 项完成：skills-ref 官方校验器接入（2026-10-03，check_skill.py v1.1→v1.1.1 A1 实检化）

> 档案 §5.15 原判定"T 实测 SKIP、环境无官方 CLI、预计仅留痕声明"。本轮复测推翻一半：官方校验器真实存在且可装，T 升级为真实接入。

### 考证与甄别（供应链安全，留档）

- **官方包 = PyPI `skills-ref` 0.1.1**：author Keith Lazuka <klazuka@anthropic.com>、repo github.com/anthropics/agentskills、docs agentskills.io、Apache-2.0、requires_python>=3.11（依赖 click/strictyaml）
- **npm 同名包 `skills-ref@0.1.5` 系第三方占用**：maintainer yc.ma（crazyyanchao/agentskillsjs），自述"demonstration purposes only，not for production"，与官方无关——**勿经 `npx skills-ref` 调用**（第三方供应链风险）。操作手册 §5.2/附录 B 原文命令名 `skills-ref validate` 与官方入口名不符
- **官方 CLI 入口名 = `agentskills`**（非 skills-ref）：`agentskills validate <skill_dir>`

### 落地动作

1. 托管 venv（`~/.workbuddy/binaries/python/envs/default`）`pip install skills-ref==0.1.1`（钉版，§8.1.2 纪律）；入口 `agentskills.exe`
2. `agentskills validate` 实测三技能（llm-review/trigger-eval/quality-ab）全 "Valid skill"（exit=0）；留痕 `.verification/m1-s/skills-ref-validate.md` ×3
3. **check_skill.py v1.1→v1.1.1**：A1 探测 `shutil.which("skills-ref")` → `which("skills-ref") or which("agentskills")`（原实现装了官方包也探不到——入口名错位）；SKIP 证据补安装与 PATH 口径；docstring/版本行同步；**npm 投毒警示写入 A1 注释**（工具自身 §8.1.2/DEP-1 纪律的自洽要求）
4. 实弹：带 venv Scripts PATH 复扫三技能，A1 三行全 PASS（exit=0），check-skill.md ×3 刷新；A1 从 SKIP 转 PASS 不触发警告级（v1.1 S-3 口径自洽）

### 验证闭环

- `tests/test_check_skill.py` 20 组全 PASS（测试环境无 CLI → A1 仍 SKIP，不触新分支）；V6 冒烟 5/5；其余六套回归 12+13+15+18+14+8 零影响
- 无官方 CLI 的环境下行为与 v1.1 完全一致（SKIP 路径不变，仅证据措辞更新）

### 遗留口径

- 调用约定：A1 实检须在 PATH 含 venv `Scripts`（或已全局安装 agentskills）的环境运行 check_skill.py；否则 A1 SKIP（不计警告）——已写入 SKIP 证据与 OPERATIONS

## check_skill.py v1.1.2（2026-10-03 追加评审 3 条处置：2 改代码 + 1 考证后不采纳）

| # | 级别 | 处置 |
|---|---|---|
| 1 | 中 | **A1 探测优先序与文档语义相反（属实）**——原 `which("skills-ref") or which("agentskills")` 在两 CLI 并存环境会优先命中 npm 第三方占用包（其 bin 名恰为 skills-ref），validate 结果不可信。抽模块级 `find_official_cli(which=shutil.which)`（可注入假 which 直测），官方入口名 agentskills 优先、skills-ref 仅作别名兜底；注释同步改口径 |
| 2 | 低 | **未用 _BlockArgParser（属实）**——v1.1d 冻结时该纪律未成型。原建议留"回填批次"，但待办清单无回填批次一项且改动仅 8 行，当轮回填：补 `_BlockArgParser`（error() 覆写 exit 1，沿 eval_discipline v1.0.3 现成模式），`--lines abc` 不再撞 WARN 码；C2 冒烟复测"报错含用法提示"契约仍 PASS（exit 由 2 变 1 正是回填生效） |
| 3 | 低 | **deliver_check 版本头"7 条 vs 8 条"（部分不实，不采纳改 7）**——考证 fix-log 第 533 行：v1.0.1 首轮评审实为 **8 条**（1 高+2 中+1 中弱改进+3 低+1 极低=8；"6 改代码+1 docstring+1 保留现状"=8）。评审者"v1.0.1 修的是 7 条"前提有误：笔误在 v1.0.1 版本头当时写的"7 条"，v1.0.2 改版本头时已写成正确的 8 条——按建议改回 7 反而引入错误。处置：v1.0.2 版本头数字保持 8，补构成明细（1 高+…=8）绝歧义 |

### 验证闭环

1. `tests/test_check_skill.py` 20→**24 组**全 PASS（新增：find_official_cli 并存取 agentskills / 仅别名兜底 skills-ref / 双缺 None 三态注入直测、`--lines abc` exit 1 带用法提示子进程实测）
2. V6 冒烟 5/5 PASS；其余七套回归 12+13+15+18+14+15+8 零影响
3. 实弹三技能复扫（PATH 含 venv Scripts）：A1 三行全 PASS、exit 0，与 v1.1.1 零行为差异；无 CLI 环境 A1 SKIP 路径不变

## C 项完成：local_gate.py v1.0 本地回归门禁建成（2026-10-03，S/T 执行机制固化）

> 待办 C 口径（§5.14③："C（CI 门禁）是 S/T 的执行机制、无 S 则无 C"）——S 类六批 + T 项已全部完成，本工具把回归固化为一键门禁：任何工具改动后先过本门再同步双盘/提交。

### 检查项（两项，工具本地编号 LG-1/LG-2）

| 项 | 内容 | 判级 |
|---|---|---|
| LG-1 | tests/test_*.py 全部逐套**子进程隔离**运行（动态 glob——未来新增测试自动纳入，当前 8 套 113 组断言）；exit 0=PASS、非 0=FAIL、超时=FAIL，证据取输出尾部 | 单套 FAIL 即门禁 FAIL |
| LG-2 | 复用 smoke_runner.smoke_one 对 tools/*.py 全部脚本 C1–C5 冒烟（排除自身防自引用，动态发现同 LG-1） | 任一 C 项 FAIL 即门禁 FAIL |

退出码 0/1/2 沿族纪律；`--run` 必填语义（无参报错 exit 1 带用法）；`--tests-only` 快速回路；`--out` 落盘报告。工具自身豁免单测（smoke_runner 先例：基础设施执行器由 LG-2 覆盖）。

### 开发期当轮修（C2 契约三步收敛——冒烟自测直接抓出）

1. 首版无参即全量跑（97s）→ smoke_runner C2 判 **FAIL 挂起**——族内 C2 契约"无参调用须快速返回带用法"被违背（自测门禁反被门禁纪律抓住，闭环自洽的实证）
2. 改无参打印执行计划 exit 0 → C2 WARN"无参也能跑"——不满足 PASS 形态
3. 终版：无参=stderr 错误+用法提示+执行计划 exit 1（token_budget 模式）→ C2 **PASS**；`--run` 显式启动全量

### 顺带回填（发现于门禁首跑）

- **smoke_runner.py**：C2 走 argparse 默认 exit 2 撞 WARN 码（与 check_skill 同源，v1.1d 时代成员）→ 补 `_BlockArgParser` 当轮回填（error() 覆写 exit 1）；其 C2 判定"非零且含用法=PASS"不受退出码变化影响，冒烟零回归

### 验证闭环

1. V6 冒烟：local_gate.py 5/5 **PASS**（C2 exit=1 含用法提示）、smoke_runner.py 5/5 PASS
2. **全量门禁自证**：`local_gate.py --run` 53 项全 PASS（8 套单测 113 组断言 + 9 脚本×5 冒烟项）exit 0；`--out` 落盘正常
3. 门禁清单动态性：LG-1/LG-2 均动态 glob，S 类后续新增工具/测试无需改本工具

## local_gate.py v1.0→v1.1（2026-10-03 首评 8 条处置：2 高+3 中全改码 + 1 低重构收口 + 1 低防御覆盖 + 1 极低措辞）

| # | 级别 | 处置 |
|---|---|---|
| 1 | 高 | **自身零覆盖（属实，精确考证）**——`discover_scripts` 只排 SELF，smoke_runner 实际**在** LG-2 清单内（其无参 C2 契约路径被冒烟覆盖，docstring 的"smoke_runner 先例"对它成立）；但 local_gate 自身被排除且无单测，docstring"由 LG-2 冒烟覆盖"对自身是虚假声称。采纳：新建 `tests/test_local_gate.py`（8 组断言：无参契约/--out 提示/timeout 校验/tests-only 计划/tail 四边界/双 discover 清单/导入兜底/ev 转义），**刻意不跑全量门禁**（--run 会递归自引用 LG-1）；docstring 改为如实"覆盖口径"声明（快速路径单测 + 不入 LG-2 互为镜像） |
| 2 | 高 | **LG-2 ev 未转义（属实）**——考证 smoke_runner 现网各 ev 恰好均经 head()（已压平 \|），当前无实际破表；但属耦合脆弱（smoke_runner 改动即失效），且 LG-2"框架异常"行 `f"{type(e).__name__}: {e}"` 完全裸奔。采纳：LG-2 两处拼接（正常 ev + 异常 ev）统一 `.replace("|", "｜")`，单测以源码断言固化 |
| 3 | 中 | **smoke_runner 导入失败崩整份门禁（属实）**——import 在 try 外，改名/删除即 ImportError 冒泡到 main，连 LG-1 已得结果一并丢失。采纳：try/except ImportError 兜底，返回 `LG-2 框架导入 FAIL` 行 + 0 脚本（覆盖缺口纪律：缺口须可见非崩溃） |
| 4 | 中 | **--timeout <= 0 未校验（属实）**——0 会让每次 subprocess 立即超时→全 FAIL 误导。采纳：main 解析后校验 `<= 0` → stderr"须为正整数"exit 1（不进全量跑） |
| 5 | 中 | **--out 缺 --run 消息不友好（属实）**——用户传了 --out 更困惑。采纳：消息条件补"（--out 只是报告落盘路径，执行仍需 --run）"；不采纳"--out 隐式触发 --run"（破坏显式执行纪律） |
| 6 | 低 | **scope_plan/scope 重复计算+措辞漂移（属实）**——discover_scripts() 调两次，"脚本 V6 冒烟" vs "脚本冒烟"。采纳：main 一次 discover，scripts 传入 run_smoke（签名改 `(scripts, timeout)`），scope 措辞统一"脚本 V6 冒烟" |
| 7 | 低 | **--tests-only 下 n_scripts=0 隐含契约（防御性，不单独改码）**——随 #6 重构自然收口：n_scripts 仅在非 tests-only 分支赋值，scope 在 tests-only 下不提 LG-2 |
| 8 | 极低 | **docstring C2 措辞不清（属实）**——"防长任务被冒烟 C2 判挂起"表述绕。采纳：help 改"防长任务无参误触发"（C2 契约实质 = 无参须快速报错带用法，原措辞已删） |

### 验证闭环

1. `tests/test_local_gate.py` 新建 8 组全 PASS；其余八套回归 24+15+14+18+12+8+15+13 零影响（合计 9 套 127 组断言）
2. V6 冒烟 local_gate 5/5 PASS（C2 exit=1 含用法提示不变）；零宽字符写入前自检双文件 clean
3. 全量门禁自证：LG-1 9 套 + LG-2 9 脚本×5 = 54 项（结果见档案第 24 条）

## local_gate.py v1.1→v1.2（2026-10-03 二评 6 条处置：2 改码 + 3 测试改造 + 1 docstring；1 条按族惯例考证后调整执行方式）

| # | 级别 | 处置 |
|---|---|---|
| 1 | 高 | **run_smoke 返回值语义分裂（属实）**——import 失败返 0（实际处理数）vs 成功返清单数（计划数），报告头"LG-2 0 脚本"与执行计划自相矛盾。采纳建议 1：两条路径恒返 `len(scripts)`（计划口径一致），实际未处理由 FAIL 行明示 |
| 2 | 极低 | **run_smoke docstring 返回值语义未提（属实）**——随 #1 一并修：docstring 明说"脚本数恒为纳入清单数（导入失败也返清单数，实际未处理由 FAIL 行明示）" |
| 3 | 高 | **测试 assert+循环偏离族惯例（部分属实，考证后处置）**——考证：7/9 套确为 fail() 模式，但 test_regression.py（最早期）同为 assert 风格，评审"8 个全部"前提小有出入；三个子点中"traceback 失败现场损失""python -O 假阳性"属实，"首败中断"一点工具族本身即 fail-fast（fail()=print+sys.exit(1)），评审建议的 try/except 容错循环反而**不符合**族惯例。处置：全文件改写为 fail/ok 惯例（消息明确、-O 免疫——已实测 `python -O` 全过 exit 0），保留 fail-fast 不加容错循环（按族惯例执行） |
| 4 | 高 | **test_import_fail_guard 全局变量 hack 脆弱（属实）**——三重依赖（模块级 TOOLS_DIR/sys.modules 无缓存/cwd 不在 tools）均真实，尤其从 tools/ 手动跑会静默失效。采纳：改 `mock.patch.object(builtins, "__import__")` 注入 ImportError，与路径/cwd/缓存全解耦 |
| 5 | 中 | **test_ev_escape 源码字符串断言（属实）**——结构断言伪行为断言，重构即误报。采纳：改假模块注入（sys.modules 塞 types.ModuleType，finally 恢复）行为验证，断言含 `\|` 与 `\r` 的 ev 压平结果；**行为测试当场抓出 _flat 真缺口**——单独 `\r` 被删除致前后文粘连（"b\rc"→"bc"），修为 `\r\n`/`\r`/`\n` 统一作分隔（`_flat` helper 收编两处拼接） |
| 6 | 中 | **test_discover 硬编码 test_regression.py（属实）**——软化：只依赖自引用（test_local_gate.py 必在）+ 非空 + 全为存在 test_*.py |
| 7 | 中 | **test_tests_only_plan 语义混淆（属实）**——实际验证的是缺 --run 分支的计划展示。采纳：与 test_no_run_contract 合并（评审低 #1 同路径建议），组名 test_no_run_contract_and_plans 消歧；真实 --run --tests-only 计划展示不单独测（须真跑 LG-1，重且递归风险，docstring 已声明快速路径口径） |
| 8 | 低 | **两测试重复（属实）**——按 #7 合并为同一组断言（7 组）；未采 try/except 容错循环（#3 同口径，族惯例 fail-fast） |
| 9 | 低/极低 | TemporaryDirectory vs finally rmtree 混合、print([fn]) 风格——评审自评"可接受"，不改；mock 方案落地后 tempfile 依赖已自然消失 |

### 验证闭环

1. `tests/test_local_gate.py` 重写 7 组全 PASS；`python -O` 实测全过 exit 0（假阳性缺口关闭）；其余八套回归零影响（合计 **9 套 126 组断言**）
2. 行为测试当场抓出 `_flat` 单独 `\r` 粘连缺口并当轮修复——行为断言取代源码断言的价值实证
3. V6 冒烟 local_gate 5/5；全量门禁自证 54 项全 PASS exit 0（结果见档案第 25 条）；零宽自检双文件 clean

## 收官回填批次（2026-10-03 全量盘点评审处置：4 工具改码 + test_regression 改风格 + 全员冻结）

### 评审核实结论（盘点层 3 处修正）

1. **VERSION 缺口实为 3 个非 2 个**——check_skill.py 也无 VERSION 常量（v1.1.2 及以前仅记 docstring），评审"8/10"应为 7/10；本轮一并补齐
2. **"对齐 test_local_gate v1.2 的 ok()/fail() + try/except 循环"描述不实**——test_local_gate v1.2 无 try/except 循环；族惯例 = fail()=print+sys.exit(1) fail-fast（上轮已考证），test_regression 改造按真惯例执行
3. **"local_gate --run 是工具族第一次自洽证明"不实**——v1.1/v1.2 已两轮全量自证 54 项 PASS exit 0；本轮为收官态第三次复证
4. 评审自相矛盾一处：横向矩阵"--out ✅ 10/10"与偏离清单"host_compat 无 --out"并存（后者正确）

### 改码清单（版本升位）

| 文件 | 版本 | 改动 |
|---|---|---|
| security_scan.py | v1.0.2→v1.0.3 | _BlockArgParser 回填（族内最后 2 个未回填成员之一）+ `--out ""/空白` 显式 exit 1（原静默不落盘） |
| host_compat.py | 首次版本化 v1.0 | _BlockArgParser 回填（另一成员）+ VERSION 常量 + 报告头补版本标识 |
| smoke_runner.py | v1.0→v1.1 | VERSION 常量 + 报告头补版本标识 |
| check_skill.py | v1.1.2→v1.1.3 | VERSION 常量 + `--lines <=0` 正整数校验（原 `--lines 0` 使 A6 无条件 FAIL——warn_line=0 两比较永假恒 FAIL） |

### 测试改造与固化

- **test_regression.py 全文改写**：17 处 assert → fail/ok fail-fast（traceback 现场损失 + `-O` 假阳性双缺口关闭）；新增 test_family_backfill 组（VERSION ×3 + _BlockArgParser 全员覆盖源码断言）8→9 组
- test_check_skill 24→**26 组**：--lines 0 exit 1 行为断言（归属正确化）+ VERSION 常量在场
- test_security_scan 15→**16 组**：--out 空/空白串 exit 1 行为断言
- 可选项处置：frontmatter_block 抽公共模块与 ev 转义统一（`\|` vs `｜`）——**本轮不改**（评审自评"长期可做/无对错"；两策略各自自洽且无实际审计混淆案例，记 fix-log 留待真需求出现再动，避免收官批次扩大化）；host_compat 无 --out 保持现状（诊断入口性质，评审同判）

### 验证闭环

1. 9 套单测 **130 组**全 PASS（26+15+14+18+12+9+16+13+7）；零宽自检：test_regression 的 0xfeff 为 BOM 剥除夹具字面量（原文件即有，非污染）
2. 实弹：check_skill v1.1.3 三技能 exit 0；security_scan v1.0.3 三技能（llm-review WARN 预期 / trigger-eval、quality-ab PASS）；host_compat v1.0 报告头版本标识在位
3. 全量门禁自证 54 项（结果见档案第 26 条）——收官态第三次全绿

## S 类补齐批次（2026-10-03——§六清单外 3 条真实遗留处置：2 新工具 + 1 清单回写）

### 背景与处置范围

全量盘点评审后用户指示处置 3 条档案 §六清单之外的真实遗留：①人工清单 §0 标注总表未回写；②V23 fail-loud 注入测试（M0-3）为六批唯一未覆盖 S 缺口；③B3-1 关键词定位器（§8.3.10，W-08 降级句兜底）。处置 = ②③ 补建 + ① 回写。

### 新工具

| 文件 | 版本 | 要点 |
|---|---|---|
| inject_test.py | v1.0 | V23 fail-loud 注入测试（M0-3 单宿主口径）：V23-0 对照组（未修改副本须通过——失败=环境问题，注入用例转 SKIP 不硬判）+ V23-1 非法 YAML（tab 缩进）/V23-2 缺必填键/V23-3 name 违规三注入用例（官方解析器非零退出=fail-loud PASS，零退出静默接受=FAIL）+ V23-4 原目录 SHA256 全清单前后一致（只读自证，不依赖解析器恒实检）；解析器复用 check_skill.find_official_cli（A1 同款 validate 调用形态——agentskills 系命令组，裸路径被拒识为未知子命令，实弹首跑踩中后修正）；临时副本内层目录名=原技能目录名（官方解析器校验目录名与 frontmatter name 一致，实弹二跑踩中后重构 _make_case_copy 每用例独立 mkdtemp）；--parser-cmd 假解析器注入使单测全离线；解析器缺位 V23-0..3 SKIP（COV）。退出码 0/1/2 |
| kw_locator.py | v1.0 | B3-1 关键词定位器：定位段落产出供 W-08（降级句转备用）；词表单一来源 from security_scan import DESTRUCTIVE_WORD_RE/PROTECTION_FLAGS（禁复制）；L-1 逐命中 文件:行+行文本+±2 行上下文（_flat 压平）+L-2 防护旗标在场性标注（仅标注不判定，与 security_scan V8-5 门禁分工）+L-3 零命中"定位段落为空"声明；**信息供给非门禁——无 FAIL 语义 exit 2 恒不出现**（设计决策显式声明于 docstring/OPERATIONS）；只读扫描跳过二进制/符号链接/>512KB |

### 清单回写（Agent-Skill-人工评审检查清单.md §0）

- 15 行标注更新：D-4/5、B1-1/2/3、B3-1、B6-1、E1-1、E1-2、E2-1、E3-2、E5-3、M0-3、M1-1、M1-5、M1-6、M1-7、M1-8 → 〔S 已实现〕（各注工具名与检查项号）
- 图例补"S 待建 2026-10-03 起已清零"；统计口径重写：S 已实现 4→15、S 待建 11→0
- M0-3 行下执行项（149-150 行 checkbox）保留——per-skill 执行记录，不因工具建成而勾选

### 测试与验证闭环

1. tests/test_inject_test.py 10 组 + tests/test_kw_locator.py 7 组（族 fail/ok fail-fast、-O 免疫实测均 exit 0、零宽自检 clean）
2. 行为测试抓出两处真缺口并当轮修：kw_locator 零命中夹具正文自含 "delete"（夹具缺陷）；inject_test 临时目录名与 frontmatter name 不一致被官方解析器拒（对照组 FAIL——先误判为环境问题，考证 Usage 报错实为调用形态、再考证 Validation failed 实为目录名校验，两轮修正收敛）
3. 其余 9 套回归零影响（合计 **11 套 147 组断言**）
4. 实弹：inject_test × agent-skill-llm-review（官方解析器）**5/5 全 PASS exit 0**——宿主对三种非法注入均报错、原目录 92 文件零触碰；kw_locator × 三技能全零命中（声明正常）
5. 全量门禁自证（结果见档案第 27 条）

## inject_test.py v1.0→v1.0.1（2026-10-03 三评 8 条处置：4 改码 + 4 测试改造；kw_locator 本体不动）

| # | 级别 | 处置 |
|---|---|---|
| 1 | 中 | **copytree 未排除 .verification（属实）**——留痕目录全拷贝=效率浪费+敏感留痕扩大临时暴露窗口。采纳：`_IGNORE = shutil.ignore_patterns(".git/.verification/__pycache__/node_modules/.venv/venv/.idea/.vscode")` 入 `_make_case_copy`；测试补 .verification 夹具 + 直调断言（不入副本、本体完整） |
| 2 | 中 | **无合法 frontmatter 时 _mutate 静默失败（属实）**——fm=[] 致三注入副本与对照组字节相同，误报"静默接受"。采纳：main() 起手 `_split_frontmatter` 校验，无 fm → exit 1 带指向性提示（"注入用例无目标，核对 SKILL.md 或以 check_skill.py 复检"）；测试补 bare 夹具组 |
| 3 | 中 | **SKIP 计 exit 2 与 check_skill 口径分歧（属实）**——分叉合理但须显式声明。采纳：docstring 补"注: SKIP 计 exit 2——与 check_skill A1 SKIP 计 exit 0 的差异为设计决策：A1 SKIP 有 A2–A11 等效覆盖，本工具 SKIP 表示'注入未跑'的真实覆盖缺口，须触发提醒" |
| 4 | 低 | **V23-2 折叠标量场景语义偏差（属实）**——删 `description: >` 行留孤续行，产物是 YAML 结构错而非"缺必填键"（fail-loud 仍成立但用例声明与实测语义不一致）。采纳**建议 1**（更优）：新增 `_drop_top_keys` 整块剥除（顶层键+缩进续行/嵌套块），其余顶层键保留；docstring 同步"键**及其整块**"；测试直调 _mutate 断言（折叠续行消失/compatibility 保留/name 删除） |
| 5 | 低 | **_make_case_copy 无异常清理（属实）**——copytree 中途失败 outer 残留。采纳：签名改返 `(outer, case_dir)`，内部 try/except BaseException 就地清理再抛；调用方（对照+注入两处）try/finally rmtree outer |
| 6 | 低 | **test_inject_test import shutil 未使用（属实→转使用）**——随 #1/#5 新增的直调测试（9b _IGNORE/9c _mutate）实际用到 shutil.rmtree，import 转为必要 |
| 7 | 中 | **测试硬编码版本号（属实且范围更大）**——考证实为 **4 个文件**：test_inject_test/test_kw_locator（评审点名）+ test_check_skill 225 行/test_regression 195 行（评审"同源一并处理"成立，均为收官批次引入）；test_regression 的 host_compat/smoke_runner 两处本就是 hasattr+startswith 软断言。采纳：4 处统一软化为 `'VERSION = "v' in src`，消息补"软断言防版本升位误报" |
| 8 | 低 | **test_kw_locator 第 3 段未检查 returncode（部分不实）**——考证：第 3 段两次 run 均 `if p.returncode != 0: fail(...)` 在场（首块与重写文件后各一次），评审误报；**delete 在注释中的歧义（属实）**——补澄清注释"有意让 delete 出现在注释中——词表匹配是文本级，注释也算" |
| — | 极低 | 第 9 条（"同 inject_test.py 的 shutil"）为对 #6 的重复确认，inject_test.py 本体的 shutil 系 copytree/rmtree 实用，无问题 |

### 验证闭环

1. 11 套单测 **150 组**全 PASS（test_inject_test 10→13 组：+无 frontmatter/_IGNORE 直调/折叠标量直调；零宽自检 clean——test_regression 0xfeff 为 BOM 剥除夹具字面量非污染）
2. 实弹复证：inject_test v1.0.1 × agent-skill-trigger-eval（官方解析器）5/5 全 PASS exit 0
3. 全量门禁自证（结果见档案第 28 条）

## 复检批次（2026-10-03——上批 2 未闭环 + 本批 5 新发现：5 改码 + 2 考证不实）

### 上批未闭环（2/2 清零）

| # | 处置 |
|---|---|
| 1 | **check_skill 报告头缺 VERSION（属实，v1.1.3→v1.1.4）**——报告头补 `{VERSION}`（评审指认准确：v1.1.3 补常量但报告头漏写，审计者从落盘报告看不到版本，与补常量初衷相悖）；实弹复证报告头 `# 格式门 A 校验报告（check_skill.py v1.1.4）` |
| 2 | **inject_test NAME_PAT 死常量（属实，v1.0.1→v1.0.2）**——删除（V23-3 实用 re.sub 硬编码模式，常量自建成起零引用） |

### 本批新发现（5 条）

| # | 结论 | 处置 |
|---|---|---|
| 3 | **main() utf-8 读 SKILL.md（属实，且考证波及更广）**——BOM 技能（\xef\xbb\xbf---）首行判空 → 误报"无合法 frontmatter"exit 1；**更深一层：_make_case_copy 的 _mutate 同用 utf-8 读，BOM 下 fm=[] → 变异静默 no-op → 注入副本与对照字节相同**（与 v1.0.1 修的静默失败同型，评审未点名） | main 起手 + _mutate 读码**双点**改 utf-8-sig；test_inject_test 新增 2c 组（BOM 夹具：不误判 + 直调 _mutate 变异生效断言，10→14 组） |
| 4 | **locate() 对 security_scan import 无兜底（属实，但评审建议方案有害）**——改名/删除即 ImportError 崩栈；**评审建议的 `return [], 0, 0` 不采纳**：空结果会被 build_report 误读为"全域零命中"→ 伪造 L-3"定位段落为空"声明，比崩溃更危险 | main() 捕获 ImportError → stderr"词表导入失败（security_scan 缺位/改名？）下一步核对在位"exit 1（kw_locator v1.0→v1.0.1）；docstring 同步"不静默"决策 |
| 5 | **docstring 未声明扫描口径（属实）**——kw_locator docstring 补"跳过目录/符号链接/二进制与不可解码/>512KB；'扫描 N 文件'为实际解码成功数" | 已修 |
| 6 | **_scan_files 判断顺序冗余（不实）**——`is_file()` 跟随符号链接（指向常规文件的链接返回 True），`is_symlink()` 前置**实为必要**：跳过指向文件的符号链接防出界跟随（OPERATIONS"跳过符号链接"纪律）；若按评审改为仅 `not p.is_file()`，symlink→file 会被扫描 | 不采纳，评审前提（"is_file() 对符号链接返回 False"）与 Python 语义不符 |
| 7 | **两测试 import shutil 未使用（不实）**——test_inject_test 的 shutil 在 v1.0.1 新增的 _IGNORE 直调测试中实际使用（shutil.rmtree，181 行附近）；test_kw_locator 无模块级 import（grep 命中为夹具字符串内容） | 无需改动 |

### 验证闭环

1. 11 套单测 **151 组**全 PASS（test_inject_test 13→14：+BOM 组；`-O` 免疫实测 exit 0；零宽自检 clean）
2. 实弹：check_skill v1.1.4 报告头版本在位；kw_locator v1.0.1 报告头版本在位
3. 全量门禁自证（结果见档案第 29 条）

## 复检二批次（2026-10-03——验收实操前 2 条预检，均属实改码）

| # | 结论 | 处置 |
|---|---|---|
| 1 | **inject_test main 前置读码无 try/except（属实）**——.is_file() 过但不可读（权限/占用）→ 裸抛 OSError traceback，违反族"读不了给友好提示 exit 1"惯例（对照 check_skill 5 处/security_scan 3 处 OSError 兜底） | inject_test v1.0.2→**v1.0.3**：读 SKILL.md 包 try/except OSError → stderr 指向性提示 exit 1 |
| 2 | **test 2c 断言环境依赖（属实）**——`returncode==2` 仅在"无 agentskills"环境成立；有 CLI 环境真注入（且 BOM 夹具目录名 bom 与 frontmatter name bom-skill 不一致 → 对照 FAIL）会得 exit 0/1 → 测试 fail，违反环境无关性 | 采纳评审方案：只断言 `| V23-0 |`/`| V23-4 |` 报告行在场（跑完注入流程即可，不绑退出码）；**双环境实测**——无 CLI 与 PATH 含 agentskills 两种环境各跑一遍均 ALL PASS（14 组），环境漂移点实证关闭 |

### 验证闭环

1. 11 套单测 **151 组**全 PASS；零宽自检 clean
2. 2c 双环境实测通过（环境无关性）
3. 全量门禁自证（结果见档案第 30 条）

## 验收流程实操批次（2026-10-03——三技能全门组合复扫 + acceptance-report ×3，§六收官后首个实操项）

### 执行口径

- 门序：check_skill（A+A1）→ security_scan → naming_precheck → token_budget → eval_discipline → dep_check → deliver_check → inject_test（V23）→ kw_locator（B3-1）→ agentskills validate，共 10 门 ×3 技能 = 30 门次
- 分报告落 `<skill>/.verification/acceptance/`；验收报告规范位 `<skill>/.verification/acceptance-report.md`（deliver_check EX-1 期望路径），acceptance/ 内留同步副本
- naming_precheck 排重范围=设计库（specSkill 根）——首轮误含宿主部署目录致与自身部署副本"撞名"伪 FAIL，按口径修正重跑（部署副本同名系预期）

### 结论总表

| 技能 | PASS 门 | WARN 门 | FAIL |
|---|---|---|---|
| agent-skill-llm-review | 7（check/naming/token/eval/inject/kw/validate） | 3（security V8-6 文档防护性提及 / dep DEP-5 foo.py 示例占位 / deliver EX-3 gate-d grading schema） | 0 |
| agent-skill-trigger-eval | 8 | 2（eval V29-1 baseline 待 record / deliver EX-6 iteration-N 未见） | 0 |
| agent-skill-quality-ab | 8 | 2（eval V29-1 / deliver EX-3+EX-6） | 0 |

- **EX-1 闭环实证**：验收报告落盘后复跑 deliver_check，三技能 EX-1 全部 WARN→PASS——工具族首次在验收流程中形成"产出→复检→闭环"回路
- V23 注入 3×5 全 PASS（官方解析器）；kw_locator 三技能零命中（声明正常）
- 全部 WARN 均为留痕类/历史留痕 schema 类，无功能阻断；人工裁决项在报告 §三标注待人工

### 验收报告

- 3 份 acceptance-report.md（含门次汇总表/WARN 明细/人工裁决项/分报告 SHA256 留痕表），报告内含首轮 naming 口径伪 FAIL 的审计说明

## 人工终审回执批次（2026-10-03——纯 H 12 项终审通过 + D 盘同步哈希核验）

### 用户裁决回执（三项）

1. **D 盘已同步——哈希核验确认**：
   - 3 份规范位验收报告 SHA256 前 8 位与留痕逐一吻合：llm-review `808bca3d` / trigger-eval `6d861dd1` / quality-ab `cbbcde9b`
   - 3 份分报告（`acceptance/` 同步副本）与规范位成对一致（同上三哈希）
   - `tools/` 12 工具 + `tests/` 11 套单测在位完整；档案（tools-fix-log.md）含验收实操条目且为库内最新修改文件，时序自洽
2. **人工终审：通过**——纯 H 12 项裁决回执落档，三技能 30 门次结论维持（零 FAIL），验收实操批次正式关闭
3. **V29 baseline record：待办保留**——等待工具链解冻后执行（trigger-eval 唯一功能性待办，EX 侧无阻断）

### 状态备注

- WARN 书面评估未随本回执提交，7 处 WARN（V8-6 / DEP-5 / EX-3×2 / EX-6×2 / V29-1）维持报告 §三标注原状，待用户后续单独裁决
- 宿主部署副本（`~/.workbuddy/skills/agent-skill-*`）内 tools-fix-log.md 为部署时快照，未随本次设计库续记同步——部署副本按验收口径系预期独立，不构成双盘缺口

## B 区条件项执行批次（2026-10-03——V29 baseline record 补落 + 7 处 WARN 书面评估，工具链解冻）

> 用户回执授权执行（"做了"）；至此 B 区条件触发项中可执行部分清零。

### V29 baseline record（×2 补落，llm-review 已有旧式基线不动）

- trigger-eval：`--mode record --version v1.1 --iteration 1 --accepted-at 2026-10-03T11:40:00`（版本口径=SKILL.md 头部版本行）
- quality-ab：同上，version v1.2
- snapshot-dir 口径：`.verification/iteration-1/`（工具建议口径，内放 record-baseline.md 留痕）——**实弹踩坑当轮修**：首跑误传相对路径，snapshot 解析到设计库根 `.verification/iteration-1/`（误抓 smoke-check 文档且两技能哈希相同暴露），改绝对路径重落（record 覆盖写自愈）
- 复跑验证（闭环实证，EX-1 同款）：两技能 V29-1 WARN→PASS、V29-2 SKIP→PASS，eval 门总结论 PASS exit 0

### WARN 书面评估（×3 落 `.verification/warn-assessment.md`，逐条复跑取证代拟，终效以用户确认）

- llm-review 3 处全部**接受**：V8-6（w-prompts.md:187 系评审清单防护性列举，非危险指令）、DEP-5（foo.py 系示例占位，顺带修订建议不单独开轮）、EX-3（gate-d 历史工作区工件不回改）
- trigger-eval 2 处**全部闭环清零**：V29-1 整改闭环 + EX-6 随 iteration-1 目录在场复跑转 PASS（意外连带闭环）
- quality-ab 3 处：V29-1/EX-6 同上闭环；EX-3（3 处 gate-d side-effects 历史工件）接受
- 插曲：三份文档写入混入"acompañ"乱码一词，当轮发现当轮清除

### 最终 WARN 态（vs 验收实操批次）

| 技能 | 前 | 后 |
|---|---|---|
| llm-review | 7P+3W | 7P+3W（3 处书面评估=接受留痕） |
| trigger-eval | 8P+2W | **10 门全 PASS** |
| quality-ab | 8P+2W | 9P+1W（EX-3 接受留痕） |

### 哈希留痕（SHA256 前 8 位）

- 基线：trigger-eval b59e6e1f / quality-ab bfe14af2；record 留痕：trigger f9c42d67 / qa 3e87f51f
- 评估：llm-review b4872783 / trigger-eval 698f722a / quality-ab b3ebdd6c
- 本档案续记前 7f737e5b

### 开放项

- B2 其余条件项（如涉及）与 B 区待外部条件项不变；本轮两项按用户回执关闭

## 可读性治理批次（2026-10-03——代号体系自足化，WARN 评估终效关闭）

### WARN 评估终效

- 用户回执确认：warn-assessment.md ×3 的"接受"结论正式生效，该项关闭（llm-review 文档已追加终效确认节）

### 用户提出的可读性问题（代号依赖）

- 症状：llm-review description 含 L 类/D/W/E/R/V12/W 组/版本 A/B 等代号；specSkill 大量文档脱离关联参考文件难读
- 定性：代号体系封闭词汇表问题——受众冲突（宿主触发 vs 陌生读者）；留痕文档受众为未来自己+审计，全面自足化不经济

### 处置（3 件）

1. **GLOSSARY.md**（设计库根，f891d013）：代号总表——生命周期/手段标注/检查项编号体系规则/状态码/查询路径；维护纪律=新增代号先入表再使用
2. **README.md** 头部加"新读者入口"（93694d0e）指向 GLOSSARY
3. **description 修订提案**（iteration-1/description-revision-proposal.md）：前半句自足化+触发词区保留代号；不直接改 SKILL.md——须修订轮（V28-1 + 门 C 实测），待人工裁决

### 口径结论（对外发布物 vs 留痕）

- 需自足的=技能包门面（SKILL.md description）与仓库入口（README/GLOSSARY）；references 系 LLM 执行材料、.verification 系留痕，体系内可读+GLOSSARY 兜底即可——与业界 skill 发布惯例一致

## v1.4 修订轮批次（2026-10-03——description 可读性自足化，用户采纳提案，全链闭环）

### 变更与同步

- SKILL.md：description 前半句去代号（L 类/D/W/E/R/V12/W 组→四阶段中文+通俗表述，触发词区代号降括注）；版本行 v1.3→v1.4（SKILL.md 哈希 ad531f4d）
- CHANGELOG 续记 v1.4；evals.json 版本 1.3→1.4 同步；宿主部署副本三文件同步（双盘 ad531f4d 一致）

### 验证闭环

1. check_skill A 门：10/10 PASS（exit 0）
2. eval_discipline V28-1（--description-text）：PASS 逐字符一致（1138f748）
3. **门 C 触发回归（runs.md 批次 6）**：train 12 条 × 3 轮 = 36 次全新子代理（协议 C2 路径 B + 诚实回报纪律）——**12/12 条 PASS，36/36 零偏差**；正例 1.000/v1.3 为 0.667（P03 修复）、负例 0.000/v1.3 为 0.333（N02 误触发修复）——代号降括注未伤召回、负向边界保持
4. V29 基线 re-record：v1.4/iteration 1/12:30:00，新式带 snapshot 9 文件（V29-2 SKIP→PASS）
5. deliver_check：EX-1/EX-6 PASS，EX-3 维持已评估"接受"

### 副作用处置（P05 三轮实际执行评审，先例如实留痕）

- W-02-20261003-121113 双评包 + 3 条 10-03 log 记录保留并同步设计库（两个独立子代理会话 A/B 判定一致）——**采信待人工签认**；8 套冗余包移 side-effects/；log"[包A] [包A]"重复瑕疵按 V12 不回改
- 插曲：V28-1 复跑时命令误留空 heredoc 致 python REPL 空转（254MB 日志），无文件损伤，当轮发现重跑

### 留痕哈希（SHA256 前 8 位）

- SKILL.md ad531f4d；基线 de7ecd92；runs.md 1c0f49b7；v1.4-revision-closure.md 2dfa6ccc；本档案续记前 5983a391

### 遗留

- validation 子集 8 条未跑（可选，train 零偏差）——2026-10-03 用户签认 v1.4 放行 + W-02 副作用留痕采信，修订轮关闭（详见 v1.4-revision-closure.md 放行签认节）

## 状态卡 + 可读性治理 + 验证编排技能批次（2026-10-03，第 38 条）

### 四件套（用户五项指示）

1. **状态卡蒸馏**：K类实现-状态卡.md 新建（standardSkill）——原跨会话续接档案完整保留不动；状态卡收头部产物表/手段完成度表/A–D 区待办/模板 v8/历史速查，作为此后新会话唯一入口。
2. **代号中文化**：specSkill README 全文重写（中文为主、代号为辅，如"LLM 语义评审技能（L 类）""安全扫描器（检查项 V8）"）；OPERATIONS 六个场景标题中文化 + 新增场景 0（一键编排入口）；standardSkill README 配套产物表同步。
3. **验证操作总说明书.md**（specSkill 根，新手版）：全景图 + 设计/编写/测试/交付/运行五阶段逐步操作（每步含执行者/命令/过门线）；补入官方工具两件——agentskills validate（PyPI skills-ref 0.1.1 的 CLI，npm 同名系第三方占用警示）与 skill-creator（设计期向导，冲突以本仓库规范为准）；§7 一键编排指引、§9 速查表。
4. **agent-skill-validation-suite v1.0 新建**（第四个编排技能）：SKILL.md + scripts/validate_suite.py（分阶段调度器 design/write/test/deliver/auto，--tools-dir 四级探测 fail-loud、官方 CLI 双路探测、SKIP 合成步不计警告）+ references/lifecycle-map.md + evals.json 草案 8 条（未冻结）。家族纪律全项：_BlockArgParser/VERSION/exit 0-1-2/报告头/无交互。

### dogfood 实证（自家工具抓自家调度器）

- 设计期 naming_precheck 3/3 PASS（与 llm-review 最高相似度 0.438）；交付期全门 11 步复扫：首跑冒烟步 FAIL——smoke_runner 吃脚本清单不吃目录，调度器当轮修（展开 scripts/*.py 传 --scripts；无 scripts 目录像合成 SKIP）；重跑 0 FAIL + 2 WARN（V29-1 基线未落/EX-1 验收报告未出=M1 时点预期）。
- 官方校验实检 PASS（agentskills validate 经托管 venv）；V23 注入 3/3 fail-loud PASS；A 门/安全/预算/依赖全 PASS；调度器无参/坏参数组合 exit 1+用法、auto 模式正确判交付期。
- 宿主部署副本四文件同步，双盘哈希成对一致（SKILL.md 18383679 / validate_suite 05abf6d6 / lifecycle-map 2014513f / evals 313e06b8）。

### 口径与边界

- 编排器不替代：触发评测子代理实测（trigger-eval）、双跑对照（quality-ab）、语义评审（llm-review）、人工终审——SKILL.md 边界节与总说明书 §7 均显式声明；仓库纪律第 5 条"不得仅凭退出码作验收阻断"写入报告头。
- 本批未触碰冻结工具链（tools/ 零改动），无单测增量；新技能自身触发实测（门 C 20 条冻结版）留待 A 区口径，evals.json 现为草案占位。

### 留痕哈希

- 状态卡（standardSkill）；总说明书、README、OPERATIONS（specSkill）；新技能四文件哈希见上；deliver-precheck.md 首跑 FAIL→修复重跑 0 FAIL 两版均在 .verification/ 留证

## 验证补全工程批次（2026-10-03，第 39 条——甲档 2 新工具全链落地）

### 工程产物（任务书：standardSkill/验证补全工程-跨会话任务书.md，七条裁决分档）

- **tools/w_static_lint.py v1.1**（新增，L-1~L-18 全 18 项编写期静态补检）：_BlockArgParser/utf-8-sig/is_symlink 前置/NUL 嗅探/exit 0-1-2/SKIP 不计警告家族纪律全项；L-5 引号 str 数组（首轮评审 P0）、L-12 二进制过滤（is_binary 此前未用，P0）、L-7 围栏外扫描+per-branch 链图、L-15/L-17 真实行号（frontmatter 偏移）等历轮评审与自查修复均已固化；L-16 兼容 eval_discipline 新旧两式基线
- **tools/eval_artifacts_check.py v1.1**（新增，Q-1~Q-9 全 9 项评测产物校验）：Q-2 train/validation 对称 ⊆ 全量+frozen.sha256 只读校验、Q-4 summary 重算对账（不吃手填）、Q-6 恒态清单附 ×n 样本数且合并全部 runs.json（与 Q-7 同口径）、Q-7 按来源文件分池（timing 聚合值不与 runs 逐次混池——首轮单测夹具抓出）；产物缺失→SKIP 不计警告
- **单测两套**：test_static_lint 31 组 + test_eval_artifacts_check 51 组，全 PASS + python -O 免疫；全量 local_gate **78 项全绿**（LG-1 动态收录、LG-2 冒烟自动纳入）
- **validate_suite.py v1.0→v1.1**（非冻结例外）：write 阶段挂 w_static_lint、test 阶段挂 eval_artifacts_check，无 .verification/ 走 __skip__ 合成步

### 评审闭环（历轮模式，两工具各两轮）

- w_static_lint：首轮外部评审 2 P0 + 6 一致性 + 8 覆盖缺口 → 15 改码 1 考证不采纳（n_binary 语义）→ v1.0.1；独立自查 3 处真问题 → v1.1
- eval_artifacts_check：首轮外部评审 2 Bug（Q-2 train 越集静默 PASS / Q-8 证据列 fallback 失效）+ 5 一致性 → 7 改码 1 设计差异不采纳（tag 前缀形态统一——无下游机器解析消费方）→ v1.0.1；独立自查 Q-6 多 runs.json 口径分裂 → v1.1

### dogfood（四目标 × write/test）与书面声明 5 项

- 当轮修 2 项：llm-review / quality-ab 各补 .gitattributes（L-13 WARN→PASS，非 SKILL.md 不触发 V29 联动）
- 声明不采纳 3 项：①suite L-10 命中 _DEFAULT_LIB=D:/sData/specSkill——fail-loud 兜底必需；②trigger-eval L-10 命中冻结样例集 sample-queryset.json payload——§6.2.3 真实语境示范+字节冻结（sha256 752f7c38 未动）；③llm-review L-15 SKILL.md:69,76 CJK 尾注/quality-ab L-8 缺 Gotchas——留各技能下一版本迭代
- V29-2 FAIL 系 14:46 前会话追加留痕的既有漂移，非本轮产物；本批续记后经 record 刷新基线（用户第 7 步开工指令即授权，任务书 §二第 7 步明文）

### 文档批（第 6 步，八份同步）

操作手册 v1.5（§5.1.1 双列改回脚本列+补遗漏行 §1.8/§9.1/§8.2.6、新增 §1.4 丙档个人版口径 8 项、A.2 执行方式汇总）；OPERATIONS（场景 8 十二门+三档执行方式、场景 4 计数 13 套 233 组）；两库 README 版本总览（12+2 工具 + 1 门禁 + 13 套单测）；GLOSSARY 新增 L-xx/Q-xx/LL-xx；总说明书 v1.1（§2.6/§3.7/全景图/编排表）；状态卡工程进度刷新；tools/README 登记两工具两测试+本批次记录追加（历史只增不改）

### 双盘同步（C2 纪律，SHA256 成对一致）

- validate_suite.py f1f8d0cc、quality-ab/.gitattributes a79691a9、llm-review/.gitattributes a79691a9 → C 盘宿主库（~/.workbuddy/skills/），PAIR-OK ×3，同步后全量复 diff 干净
- tools/ 两新工具与单测仅存 D 盘基线（宿主技能库按历轮口径不含 tools/，调度器经 _DEFAULT_LIB 四级探测引用，书面在案）

### 留痕哈希（SHA256 前 8 位）

- w_static_lint b899e94d；eval_artifacts_check 0ae7108d；test_static_lint 5af6982a；test_eval_artifacts_check a893f7af；validate_suite f1f8d0cc；dogfood 留痕 c70e6903；任务书 0deea9b8

### 遗留

- llm-review validation 子集 8 条实测（承第 38 条遗留，可选）；quality-ab Gotchas 节与 llm-review CJK 尾注留下一版本迭代；两新工具 v1.1 若再触发外部评审按历轮闭环续记第 40 条
