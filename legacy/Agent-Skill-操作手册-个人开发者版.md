# Agent Skill 生命周期验证 · 个人开发者操作手册

> **版本**：v1.5（2026-10-03；v1.5 验证补全工程文档批——§1.4 个人版口径（丙档剔除 8 项）、§5.1.1 双列口径改回脚本列（w_static_lint L 系）+ 补遗漏行 §1.8/§9.1/§8.2.6、§6 接口表补两新工具、附录 A.2 验收报告加执行方式汇总；v1.4 §2.1/§3/§6 工具名与 specSkill 实际工具族同步——12 工具 + 1 门禁已全部落地；v1.3 §5.3 集成 agent-skill-llm-review 技能 + skills-ref→agentskills 勘误）
> **依据**：《Agent-Skill 生命周期验证方案》v1.3，经"个人开发者（团队 ≤2 人）可工程实现"裁剪
> **配套文档**：《Agent-Skill 验证 SOP · 个人开发者版》《Agent-Skill 人工评审检查清单》《Agent-Skill LLM 评审提示词清单》
> **本手册回答**：每一步具体怎么动手做、用什么工具、命令怎么敲、留痕写在哪里。

---

## 1. 裁剪说明（相对 v1.3 方案）

### 1.1 剔除（个人无法通过工程手段实现，不保留）

| 原条目 | 剔除内容 | 替代方案 |
| --- | --- | --- |
| V9 运行期遥测（自动采集触发误报/漏报、token 成本漂移、脚本失败率） | 自动埋点、自动统计、自动告警 | **人工运行日志表**（附录 A.4）+ 每周回顾一次 |
| V24 运行期安全遥测（自动告警异常外部请求/权限提升/secret 泄露） | 自动监控告警基础设施 | 运行日志表中增设"异常观察"列，人工记录；疑似事件回流 V13 审计 |
| C 类 CI 门禁（企业级持续集成流水线，V7 的流水线形态） | 强制 CI 基础设施 | **本地一键校验脚本为底线**；技能库托管 GitHub 时可用单文件 Actions workflow 作可选增强 |

### 1.2 降级（保留目标，降低工程形态）

| 原条目 | 原形态 | 个人版形态 |
| --- | --- | --- |
| V7 持续回归 | CI 自动触发 | 修订前后必跑 `check_skill.py`（写入个人纪律清单）。**底线为二选一强制**：git pre-commit hook **或** 单文件 GitHub Actions，至少启用其一，不允许两者皆无——否则 V7 的 [M] 目标落空。推荐 pre-commit hook（本地零依赖） |
| §6.2 查询集 20 条（8–10/8–10 配比） | 固定 20 条 | **下限 12 条**（6 正例/6 负例），60/40 切分照旧；高复用技能建议回到 20 条 |
| V27 拆分由专项 skill 执行 | skill-creator 类技能为主力 | **人工 + LLM 辅助拆分为默认**（原方案的降级路径转正），告知义务与格式门复跑不变 |
| V25/V29 iteration 基线的 CI 比对 | CI 自动比对 | `.iteration-baseline` 文件 + 手动核对（脚本可选） |
| E-S 断言统计脚本（触发率、离群值 >3× 均值） | 专门脚本 | 用例数少，**电子表格/手算即可**；触发率阈值 0.5 判定不变 |
| V2 余弦相似度预检 | embedding 相似度 | **关键词重叠 >0.6 告警**（原文二选一口径）；同名检测必做，余弦为可选增强 |
| V11 token 计数宿主 tokenizer | 优先宿主 tokenizer | **字符数 ÷4 保守估算**为默认（原文允许的兜底口径），全流程固定同一实现 |
| V23 多宿主实测 | 声明多宿主时 ≥2 宿主实测 | 个人默认**单宿主交付**：只做 fail-loud 注入测试；确需多宿主时按原文执行 |

### 1.3 全量保留（个人工程能力覆盖）

- **S 类**：全部静态检查（格式门 A、V8 安全扫描、V14 目录黑名单、V17 预算门、LF/BOM、secret 扫描、URL 提取比对等）——用 §6 的小脚本套件实现；
- **L 类**：全部语义评审——用 LLM 会话执行，按 V12 留痕（见《LLM 评审提示词清单》）；双评 = 两个独立会话或两个不同模型，个人可负担；
- **H 类**：全部人工终审——见《人工评审检查清单》；
- **K 类**：全部动态实测（触发评测、双跑对照、脚本冒烟 V6、盲评）——LLM 会话 + 手动执行，规模按 1.2 裁剪。

### 1.4 个人版口径（丙档剔除项——"本项按个人版人工执行"）

> 以下 8 项经三份外部评审盘点、按用户七条裁决分档为**丙档：剔除在外**（个人开发者无法完成或必须人工）。各项**不建任何工程物**，按下表口径人工执行，消除"方案声称有、个人版做不到"的口径落差。

| 条目 | 个人版口径（本项按个人版人工执行） |
| --- | --- |
| V3 注册发现冒烟 / V4 多技能共存冒烟 | 人工——须真实宿主查询能力（host API 不可编程访问）；新宿主实测（B1）时一并执行 |
| V5 依赖环境实测 / §8.2.6 环境干扰 | 人工——O 类环境事实，目标宿主实测运行器/网络/版本 |
| V22 运行器环境匹配 | 人工——环境事实，随 V5 一并实测 |
| V13 完整安装审计单 | 人工——按附录 A.3 模板出单（deliver_check EX 门存在性初筛已覆盖脚本化部分） |
| V9/V24 运行期遥测 | 个人版降级——人工 run-log.md 台账（附录 A.4）+ 周体检 C1 承接，不建自动埋点 |
| V15 第三方素材许可判断 | 人工——价值裁决（EX-4 存在性已脚本化） |
| V7 CI 流水线（GitHub Actions 等） | 个人版降级——local_gate 手动门禁 + validation-suite 编排即 C 形态，**不建 CI**；pre-commit hook/单文件 workflow 二选一（§1.2） |
| 统一终检编排入口（skill_gate.py） | **不新建**——agent-skill-validation-suite 已承担（甲档两新工具已挂进其步骤表） |

---

## 2. 环境准备

### 2.1 工具清单

| 工具 | 用途 | 必需性 |
| --- | --- | --- |
| Python 3.10+ | 运行校验脚本套件 | 必需 |
| `tools/check_skill.py`（v1.1.4） | 格式门 A 权威校验器（A1–A11 + X1/X2；A1 实检需官方 CLI） | 必需（接口见 §6） |
| `tools/w_static_lint.py`（v1.1） | 编写期静态补检器（检查项 L-1~L-18：全包卫生/引用链二层/i18n/恶意初筛等，见 §5.1.1 对照表） | 必需（编写期每轮） |
| `tools/eval_artifacts_check.py`（v1.1） | 评测期产物校验器（检查项 Q-1~Q-9：查询集 schema/切分冻结/grading 对账/离群值等） | 必需（E 阶段产物在 .verification 时） |
| `tools/security_scan.py`（v1.0.3） | V8 安全扫描六项（secret 正则+熵、端点比对、交互、破坏性/危险关键词） | 必需 |
| `tools/naming_precheck.py`（v1.0.3） | 设计期命名冲突预检（V2） | 必需 |
| `tools/token_budget.py`（v1.0.1） | V11 token 口径 + V17 预算门 | 必需 |
| `tools/dep_check.py`（v1.0.1） / `tools/deliver_check.py`（v1.0.2） | 依赖检测五项 / 交付物存在性+schema 七项 | 必需（M1 终检） |
| `tools/inject_test.py`（v1.0.3） / `tools/kw_locator.py`（v1.0.1） | V23 fail-loud 注入 / B3-1 关键词定位（W-08 供给） | 必需（M0 / W-08 前） |
| `tools/host_compat.py`（v1.0） / `tools/smoke_runner.py`（v1.1） | 跨宿主试点路径裁决 / V6 脚本冒烟 | 必需（试点前 / 脚本变更后） |
| `tools/local_gate.py`（v1.2） | 一键本地门禁（LG-1 全套单测 + LG-2 全工具冒烟） | 必需（任何脚本改动后） |
| `agentskills` 官方校验器 | frontmatter 官方校验（§2.8；CLI 入口名 agentskills，PyPI 包名 skills-ref） | 可用则必跑，不可用按附录 B 降级清单 |
| 触发率统计 | `agent-skill-trigger-eval/scripts/calc_trigger_rate.py`（随 K 技能分发） | 必需（E 阶段；电子表格可替代） |

> 注：以上工具均已落地于 `D:\sData\specSkill\tools\`（含 13 套固化单测），版本以 `tools/README.md` 为准；gitleaks 等现成 secret 扫描器不再需要（security_scan.py 已内置正则+熵检测）。
| git + pre-commit hook **或** 单文件 GitHub Actions | 把 `check_skill.py` 挂到提交前/推送前（V7 底线） | **必需（二选一强制）** |
| LLM 会话入口 | 语义评审、断言评分、盲评、轨迹诊断 | 必需 |

### 2.2 目录约定

```
my-skill/
├── SKILL.md
├── references/  scripts/  assets/  evals/
└── .verification/          ← 验证留痕目录（不随技能分发，git 可 ignore 也可留存）
    ├── design.md           ← 设计说明（V1 留痕）
    ├── name-precheck.md    ← V2 预检输出留痕
    ├── llm-review-log.md   ← LLM 评审留痕（V12）
    ├── manual-checklist.md ← 人工检查清单填写结果（存档快照）
    ├── iteration-1/ …      ← 测试期逐轮记录（不覆盖历史，V25）
    ├── .iteration-baseline ← 已验收 iteration 标记（V29）
    ├── audit-sheet.md      ← 安装审计执行单（V13）
    ├── acceptance-report.md← 验收报告
    └── run-log.md          ← 运行期日志（替代自动遥测）
```

---

## 3. 总流程

```
D  设计评审(V1：设计说明三项) ──► 命名冲突预检(V2)
      │
W  编写 ──► check_skill.py（A 门）+ security_scan.py（V8）+ token_budget.py（V17）
      │      + agentskills validate（可用时，CLI 名见 §5.2 勘误）
      │      + LLM 语义评审（提示词清单 W 组，V12 留痕）
      │      └─ 内容门 B 人工终审（检查清单 W 部分）
      │
E  触发评测(12–20 条查询集) ──► 质量双跑 ──► 脚本冒烟(V6)
      │      └─ 断言时机(V21) ──► 人工复核(§7.7) ──► 触发门 C + 质量门 D
      │
M0 挂载 ──► 注册冒烟(V3) + 共存冒烟(V4) + fail-loud 注入测试(V23 单宿主口径)
      │
M1 全门终检(A 复跑 + V8 复扫 + V17) ──► 依赖实测(V5/V22) ──► 审计单(V13/V15) ──► 验收报告
      │
R  运行日志(替代 V9/V24 遥测) ──► 纠错沉淀(V10/V26) ──► 行数漂移检查(V27) ──► 回流 W/E
```

---

## 4. D 设计期操作

### 4.1 填写设计说明（V1）

复制附录 A.1 模板到 `.verification/design.md`，填写并自查三项齐全：

1. **真实取材来源清单**：任务轨迹 / 项目文档 / 事故报告，逐条列出（§5.1.4）；
2. **一句话范围定位**：本技能做什么、不做什么（§5.2.1–5.2.3）；
3. **相邻技能边界清单**：与库内哪些技能相邻、边界在哪。

**纪律**：三项任一缺失不得立项（不建目录、不写 SKILL.md）。

### 4.2 命名冲突预检（V2）

```bash
python tools/naming_precheck.py --name my-skill --description "一句 description" \
  --library <技能库根目录>   # 多库可重复 --library；设计期无目录即可预检
```

输出：同名命中（**FAIL，[M] 阻断**）/ 关键词重叠 >0.6 告警（**WARN**，不直接阻断，须书面评估并记录处置结论）/ 通过。结果存 `.verification/name-precheck.md`。

### 4.3 出口判据

设计说明三项齐全 + 预检零 FAIL（重叠 WARN 项已书面评估并记录于 name-precheck.md）→ 立项，进入 W。

---

## 5. W 编写期操作

### 5.1 一键静态检查

```bash
python tools/check_skill.py <skill_dir>
```

覆盖：目录结构（§1 全表，含 V14 同义变体黑名单 docs/utils/lib/helpers/doc）、frontmatter（§2 全表：YAML fail-loud、必填键、name 正则 `^[a-z0-9]+(-[a-z0-9]+)*$`、description 1–1024、compatibility ≤500 等）、行数预算（**<300 行阻断，≥240 预警**，V17/V27）、正文 token 估算（字符÷4，<5000）、元数据 token（约 100）、扩展层单文件 ≤500 行、相对路径扫描（§4.1.3/§10.1）、引用深度一层（§4.1.5）、被引文件存在（§4.1.10）、LF/UTF-8 无 BOM（§10.3/§10.4）、脚本依赖内联声明（§8.2）、多语言交互调用检测（V8：`input(`、`getpass`、`read -p`、`confirm`、`readline`、`inquirer`、`prompt_toolkit`、`click.confirm`）、破坏性关键词须含 `--confirm/--force/--dry-run`（§8.3.10）、secret 扫描（密钥正则 + 熵检测）、外部端点提取比对（§9.2）。

输出逐项 `PASS / FAIL / WARN`，**任一 [M] 级机械门 FAIL 即阻断**（处置见 SOP §7）。

### 5.1.1 W-S 全量覆盖对照表（"S 类全量保留"的落地口径）

> 本表逐项对应方案 v1.3 W-S 静态检查条目，杜绝"名义全量、实际漏项"。"脚本"= 纳入 `check_skill.py` 覆盖范围；"脚本+LLM/人工"= 脚本做模式定位，语义复核交 LLM 或人工；脚本未实现前一律走人工兜底列并留痕。
>
> **甲档落地（2026-10-03）**：编写期静态补检 18 项由 `tools/w_static_lint.py`（检查项 L-1~L-18）承载，评测期产物校验 9 项由 `tools/eval_artifacts_check.py`（Q-1~Q-9）承载——此前"声称脚本、实际未实现"的行已改回脚本列并标注工具与检查项编号；漏项 §1.8/§9.1/§8.2.6 已补行。

| 方案条目 | 覆盖方式 | 人工兜底（脚本未实现时） |
| --- | --- | --- |
| §1 全表（目录结构/SKILL.md 位置）+ V14 同义变体黑名单 | 脚本（check_skill A 门 + w_static_lint L-1） | 目录核对清单 |
| **§1.8 无关文件/扩展名白名单/单文件体积**（漏项补行） | 脚本（w_static_lint L-2） | 人工目检目录 |
| §2 全表（frontmatter 解析/必填/name/description/compatibility/metadata/allowed-tools） | 脚本 | 附录 B 清单 |
| §3 长度/行数/token/引用深度、<300 行（V17/V27）、扩展层单文件 | 脚本（check_skill + w_static_lint L-16 基线哈希漂移比对） | 手数 + grep |
| §4.1.3/§4.1.4/§10.1 相对路径（禁 `/`、盘符、`~`、`$HOME`） | 脚本（check_skill A8 仅 SKILL.md + w_static_lint L-10 全包扩扫） | grep 正则 |
| §4.1.5 引用深度一层 | 脚本（A8 一层链图 + w_static_lint L-7 二层扫描与链图输出） | 人工追引用链 |
| §4.1.6 触发条件存在 | LLM（乙档 LL-1：机械模式匹配无脚本收益，语义判定走 W 组评审） | 逐个被引文件核对"当…读取 references/<file>"与"Read references/<file> when…"；未命中交 W-04 |
| **§4.1.7 禁笼统指引** | 脚本（w_static_lint L-17 机械初筛）+ LLM 终判（LL-2） | grep + W-04 |
| §4.1.10 被引文件存在 | 脚本 | 逐个点开核对 |
| **§5.5.1 Gotchas 节存在** | 脚本（w_static_lint L-8） | 人工目检 |
| **§5.5.6 模板内联/assets 归置** | 脚本（w_static_lint L-9） | 人工目检 |
| §5.5.4 Gotchas 位置（S 定位部分） | 脚本（节位置/引用形态） | 人工目检；信号是否明显交 LLM |
| **§7.1.1 evals.json 存在与 schema** | **脚本（JSON schema 校验）** | 人工对照字段 |
| §8.1.2/§8.2.1–8.2.3 版本固定/依赖内联声明 | 脚本（正则） | grep |
| **§8.2.4 脚本清单完备（scripts/ 实际文件 ⊆ SKILL.md 清单）** | **脚本（交叉比对）** | 人工比对目录与正文清单 |
| **§8.2.6 环境干扰**（漏项补行） | 人工（丙档：环境事实不可编程访问——个人版按人工实测执行，见 §1.4） | 目标宿主实测运行器/网络/版本 |
| §8.3.1 静态禁交互（多语言）/ §8.3.10 确认标志 | 脚本（V8） | grep 关键词表 |
| **§9.1 恶意特征模式**（漏项补行） | 脚本（w_static_lint L-18 机械初筛）+ LLM/人工终判（LL-6；security_scan 语义审计不豁免） | 人工逐文件审查 |
| §9.2 外部端点 / §9.6 敏感信息 | 脚本（URL 提取比对 / secret 正则+熵） | gitleaks / grep |
| **§10.2 宿主专属路径/工具名** | 脚本（w_static_lint L-11 黑名单检索，`--host` 可增补）+ 人工复核 | grep + W-16 |
| §10.3/§10.4 LF / UTF-8 无 BOM | 脚本（A7/X1 仅 SKILL.md + w_static_lint L-12 全包扩扫，二进制跳过） | 字节检查 |
| **§10.6 .gitattributes 固化约定** | 脚本（w_static_lint L-13） | 人工目检 |
| §11.1/§11.2 CJK 启发式 / 命令不翻译 | 脚本（w_static_lint L-14/L-15，[P] 级告警） | 人工目检 |

### 5.2 官方校验器

```bash
agentskills validate <skill_dir>
```

> 勘误（2026-10-03 T 项考证）：官方包为 PyPI `skills-ref`（anthropics/agentskills），**CLI 入口名是 `agentskills`**；npm 同名包系第三方占用（demonstration only），勿经 npx 调用。安装：`pip install skills-ref==0.1.1`（须 Python ≥3.11）。

编写每轮结束 + 交付前各跑一次。不可用时按附录 B 降级清单人工补查并留痕。

### 5.3 LLM 语义评审

**优先调用本地技能 `agent-skill-llm-review`**（安装于 `~/.workbuddy/skills/`，承担阶段检测、提示词调度、双评任务包生成、V12 留痕与汇总）；**技能不可用时按清单手工投喂**（降级路径，不阻塞评审）。按 W 组提示词逐条评审技能文件，按 V12 留痕：

- 每次评审在 `.verification/llm-review-log.md` 记录：日期、提示词编号、模型名与版本、输出证据、判定结论；
- 关键判定（影响 [M] 级条目结论的评审）**双评**：两个独立会话或两个不同模型；评分不一致 → 升级人工裁决。

### 5.4 内容门 B 人工终审

打开《Agent-Skill 人工评审检查清单》W 部分，逐项 PASS/FAIL/N/A 填写并存档到 `.verification/manual-checklist.md`。团队有第二人时，**终审建议交叉执行**（写作者不自审终审项）。

### 5.5 出口判据

静态检查零 [M] FAIL + LLM 评审留痕齐全 + 内容门 B 全 PASS → 进入 E。

---

## 6. 工具脚本接口约定

> 脚本可用任何语言实现，以下为最低接口约定；实现时机可按需补齐，未实现前对应检查项人工执行。

| 脚本 | 调用 | 输出 | 退出码 |
| --- | --- | --- | --- |
| `check_skill.py` | `check_skill.py <skill_dir> [--lines N] [--out 报告]` | 逐项 PASS/FAIL/WARN 报告（stdout 或 --out 落盘） | 0=全过；1=有 [M] FAIL；2=仅 WARN-SKIP |
| `w_static_lint.py` | `w_static_lint.py <skill_dir> [--out 报告] [--host 词1,词2]` | 编写期静态补检 L-1~L-18 逐项报告 | 0=全过；1=FAIL；2=仅 WARN |
| `eval_artifacts_check.py` | `eval_artifacts_check.py <.verification 目录> [--queryset qs.json] [--split train,val] [--min-count N]` | 评测产物校验 Q-1~Q-9 逐项报告 | 0=全过；1=FAIL；2=仅 WARN |
| `naming_precheck.py` | `<skill_dir>` 或 `--name <n> --description <d>` + 多个 `--library <dir>` | 同名命中 / 相似度告警（余弦/Jaccard 阈值可调）/ 通过 | 0=通过；1=同名 FAIL；2=仅 WARN |
| `calc_trigger_rate.py` | `--runs runs.json --queryset queryset.json --out 报告`（specSkill/agent-skill-trigger-eval/scripts/） | 每查询触发率、train/validation 分列、0.5 阈值判定、统计覆盖率 | 0=达标；1=不达标 |

> 注（2026-10-03 同步）：原约定的 `precheck_name_conflict.py`/`trigger_stats.py` 落地时定名为 `naming_precheck.py`/`calc_trigger_rate.py`；工具族其余成员（security_scan/token_budget/eval_discipline/dep_check/deliver_check/inject_test/kw_locator/host_compat/smoke_runner/local_gate）接口见 `specSkill/tools/OPERATIONS.md`，族约定统一为退出码 0/1/2、参数错误一律 exit 1。

---

## 7. E 测试期操作

### 7.1 建查询集

- 数量：**≥12 条**（个人版下限），正例（should_trigger=true）/ 负例各半；高复用技能建议 20 条；
- 每条含：查询文本、should_trigger 标注、真实语境说明（§6.2）；
- **60/40 切分并冻结**：训练集用于改 description，验证集只用于选版（§6.4）；切分文件存 `.verification/iteration-N/`。

### 7.2 触发评测

- 每条查询**新开会话**运行 **≥3 次**（干净上下文 = 新会话即达成）；
- 记录每次是否触发（宿主技能调用日志/会话记录为证据）；
- 触发率统计（calc_trigger_rate.py）：调用次数 ÷ 运行次数，**正例 ≥0.5 且负例不触发**为过（触发门 C 口径按总表 §13）。

### 7.3 质量双跑

- with_skill vs without_skill（或旧版）各跑受影响用例，**全新会话**保证干净上下文；
- 记录：技能路径、prompt、输入、输出目录（§7.2.4）；token 与时长用估算值即可（字符÷4）。

### 7.4 断言纪律（V21）

- 初始用例 2–3 条；**断言必须在首轮输出之后添加**（核对文件时间戳：断言写入时间晚于首轮产出文件）；
- 机械断言（JSON 合法、文件存在、计数）脚本或人工逐条判；语义断言交 LLM（提示词 E-04），PASS 必须附输出证据；
- **V28 写回一致性**：description 优化选定版本写回 frontmatter 后，必须核对落盘内容与选定版本一致（文本 diff 或哈希比对），防止写回丢失/截断/变形；`check_skill.py` 的 frontmatter 段（长度/可解析性）可作辅助复核。

### 7.5 脚本冒烟（V6）

每个捆绑脚本至少实测三项并留痕：`--help` 内容正确（简述/标志/示例/退出码）、缺参报错带用法、dry-run 可用（如适用）。另按 §8.3 动态项：非 TTY 运行不挂起、报错含"错了什么+期望+下一步"、结构化输出可程序化解析、连跑两次幂等、大输入限量、沙箱前后 diff 无隐式副作用。

### 7.6 人工复核

按《人工评审检查清单》E 部分：逐用例对照产出与评分，具体可行动的反馈落盘 `feedback.json`（`text/passed/evidence` 结构）；**空反馈 = 通过**。

### 7.7 出口判据

触发门 C + 质量门 D 逐项 PASS（[M] 级 FAIL 阻断，判定口径见检查清单附录摘要）+ **V28 已执行并留痕**（[S] 级：FAIL 可书面说明理由后放行并记入验收报告，**未执行不得进入 M0**）→ 记 `.iteration-baseline`（V29）→ 进入 M0。

---

## 8. M 挂载期操作

### 8.1 M0 发现加载冒烟

1. **V3 注册冒烟**：挂载后确认宿主技能列表可见、name/description 读取无误；
2. **V4 共存冒烟**（有相邻技能时）：构造边界查询，验证触发不串扰；
3. **V23 fail-loud 测试**（单宿主口径）：复制技能目录为**临时副本**，向副本注入非法 frontmatter（缺 `name`、坏缩进），挂载副本，确认宿主**报错而非静默跳过**；不触碰原目录。

### 8.2 M1 终检与实测

1. 复跑 `check_skill.py`（A 门 + V8 复扫 + V17 预算）；
2. **V5 依赖实测**：在目标宿主环境实测运行器可用（uvx/npx/bunx 版本）、网络可达、运行时版本与 compatibility 声明一致；
3. **V13 审计执行单**：按附录 A.3 模板出单（挂载第三方技能/素材时必做）；
4. **V15 许可核对**：license 字段简短、完整条款在随包 LICENSE 文件、第三方素材许可留档；
5. 出具**验收报告**（附录 A.2）：全门结论 + [S] 级放行理由 + V27 豁免留档（如有）。

---

## 9. R 运行期操作

### 9.1 运行日志（替代自动遥测）

每次使用技能后在 `.verification/run-log.md` 追加一行（模板 A.4）：日期、任务、是否误触发/漏触发、脚本是否失败、成本异常（体感）、异常观察。**每周回顾一次**：模式化问题 → 触发 9.2。

### 9.2 纠错沉淀（V10 + V26）

1. 每次人工纠正 → 判断是否值得写入 Gotchas（LLM 辅助归纳，提示词 R-01；人工拍板）；
2. **V26 隔离判定**：逐案例累积型内容**不得堆入 SKILL.md 正文**，入 Gotchas 精简条目或 `references/`（写明加载时机）；
3. **V27 行数漂移检查**：每次回流后重跑 `check_skill.py`，≥240 行预警 → 执行拆分（人工/LLM 辅助，外移到 references/ 并告知用户外移清单与加载条件），≥300 行必须拆分；确无可外移项时 H 裁决豁免，**留档三项：豁免理由 + 行数证据 + 无可外移项论证**，记入验收报告。

---

## 10. 常见问题

**Q1：没有 CI，怎么保证修订后不漏检？**
修订（尤其改 description）前后必跑 `check_skill.py`；把"改了什么 → 触发哪个回归"对照表（SOP §8）贴进个人流程。托管 GitHub 可加单文件 workflow 自动跑同一脚本。

**Q2：双评会不会很贵？**
双评只要求**影响 [M] 级结论的关键判定**（安全审计、内容门相关语义评审、语义断言评分）。普通 [S]/[P] 评审单评即可。

**Q3：触发评测 12 条够吗？**
个人自用技能 12 条可接受；若技能将被他人复用或触发面复杂，回到 20 条。

**Q4：脚本还没写怎么办？**
每个脚本的检查项在手册 §5.1 都列出了判定内容，可先按清单人工执行；脚本实现后逐步替换。

**Q5：skills-ref 官方校验器不可用怎么办？**
按附录 B 降级清单人工补查并留痕；降级期间 V17 预算门与 V8 安全扫描为最低不可省略项。

---

## 附录 A 模板

### A.1 设计说明（design.md）

```markdown
# 设计说明：<技能名>
日期：YYYY-MM-DD    作者：
## 1. 真实取材来源清单（§5.1.4）
- 来源 1：<任务轨迹/项目文档/事故报告 + 链接或路径>
## 2. 取材计划（§5.1.5）
- 奏效步骤：…   纠正点：…   I/O 格式：…   项目事实：…
## 3. 一句话范围定位（§5.2.1–5.2.3）
本技能________；不做________。
## 4. 相邻技能边界清单
| 相邻技能 | 边界划分 |
## 5. 立项结论
[ ] 三项齐全  [ ] 预检通过  → 立项人签字/确认
```

### A.2 验收报告（acceptance-report.md）

```markdown
# 验收报告：<技能名> v<x.y>
- 日期 / 验收人：
- 格式门 A：PASS/FAIL（末次 check_skill.py 输出摘要）
- 安全扫描 V8：PASS（零命中） / 命中说明
- 预算门 V17：行数 __/300，正文 token __/5000
- 触发门 C / 质量门 D：结论与关键数据（触发率、delta）
- 脚本冒烟 V6：__ 个脚本全过
- 依赖实测 V5：宿主/运行器/版本 结论
- 审计单 V13 / 许可 V15：已出单 [ ]
- 执行方式汇总（口径见本手册 §1.4 与 §5.1.1 对照表）：
  - 脚本=格式门 A（check_skill）+ 静态补检（w_static_lint L 系）+ 评测产物校验（eval_artifacts_check Q 系）+ V8/V2/V11/V17/V21/V28/V29/DEP/EX/V6/V23；
  - 人工兜底=V3/V4 注册与共存冒烟、V5/V22 依赖与环境实测、V13 审计单、V15 许可判断；
  - 个人版降级=V7（不建 CI）、V9/V24（run-log 人工台账）
- [S] 级放行项及理由：
- V27 豁免（如有）：豁免理由 + 行数证据 + 无可外移项论证
- 结论：通过 / 不通过
```

### A.3 安装审计执行单（audit-sheet.md）

```markdown
# 安装审计执行单（V13）
被审计对象：<技能/素材名 + 来源>
1. frontmatter 与声称一致？  2. scripts/ 行为逐个审查结论？
3. 外部请求目标清单与用途一致性？  4. 依赖清单与运行器？
5. 外部路径引用？  6. 第三方素材许可合规（V15）？
结论：放行 / 拒绝    审计人 / 日期
```

### A.4 运行日志表（run-log.md）

```markdown
| 日期 | 任务 | 触发正确? | 脚本失败? | 成本异常? | 异常观察 | 处置 |
|---|---|---|---|---|---|---|
```

### B skills-ref 不可用降级清单（对应总表 §10.5，个人版落地）

> 官方校验器不可用时，`check_skill.py` 已覆盖其中大部分机械项；以下为逐项人工补查口径，结果记入 `llm-review-log.md` 同级的 `.verification/validate-fallback.md` 留痕。

| # | 官方校验器覆盖项 | 降级替代 |
| --- | --- | --- |
| 1 | frontmatter 可解析、失败报错 | `check_skill.py` YAML 解析（fail-loud）；人工确认报错未被静默吞掉 |
| 2 | name 规则（小写连字符、≤64、等于目录名） | `check_skill.py` 正则 + 目录比对；人工目检 |
| 3 | description 长度 1–1024、单行 plain scalar | `check_skill.py` 长度检查；人工确认无跨行写法 |
| 4 | license 字段简短、无多行条款 | 人工目检 frontmatter |
| 5 | compatibility ≤500 字符 | `check_skill.py` |
| 6 | metadata 键类型 string→string | `check_skill.py` 类型校验；人工确认无误 |
| 7 | allowed-tools 空格分隔格式 | `check_skill.py`；人工目检 |
| 8 | 目录结构（约定目录、无同义变体） | `check_skill.py`（V14 黑名单） |
| 9 | 未知顶层字段告警 | `check_skill.py` 白名单比对 |
| 10 | （交付前）整体可被宿主加载 | M0 冒烟 V3/V23 兜底——这是降级期间最可靠的端到端验证 |

**纪律**：降级期间每次编写轮次结束与交付前均须跑一遍本清单并留痕；校验器恢复可用后立即补跑 `agentskills validate`（CLI 入口名，见 §5.2 勘误）。
