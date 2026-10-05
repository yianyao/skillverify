# AGENTS.md —— 本仓库的工作约定与已踩过的坑

> 给**改这个工具的人**（含 AI 协作者）看。技能作者与流水线使用者看这四份：
> 《技能编写指南.md》（技能怎么写）、《验证流程指南.md》（流水线怎么装配）、
> 《操作手册.md》（新手照着做）、《迁移与部署指南.md》（换机器/上宿主）。
> 想知道"旧体系那套方案（237 条）我们覆盖了多少、漏了什么、凭什么这么决定"：
> 看《覆盖对照-生命周期验证方案.md》。
> 机器专属信息（解释器绝对路径、沙箱等）在 `AGENTS.local.md`（不提交），见文末。

## 一、这是什么

`skillverify`：宿主无关的 Agent Skill 全生命周期验证套件（纯标准库、强制 UTF-8）。
十一个命令：`spec` / `lint` / `evals` / `review` / `discover` / `check` / `mount` / `audit` / `watch` / `deliver` / `hook`。
`legacy/`（旧体系 237 条方案 + 旧技能语料）**已移出本仓库**，归档在仓库外
（仓库外的姊妹目录 `..\skillSpec-legacy-archive`），不再参与构建、测试与发布。
因此：① 规则出处一律写**文档级引用**（如「旧体系《Agent-Skill 生命周期验证方案》v1.3 §8.3.10」），
**不许**再出现 `legacy/<路径>` 这种仓库内引用（有守卫查）；② `--dogfood` 变成「可选本地语料」，默认 `legacy/`，目录不在就跳过。

## 二、跑起来

```powershell
python -m tests.run_all              # 14 个套件（默认 13），约 2 分钟（离线）
python -m tests.run_all --dogfood    # 可选：把本地语料（默认 legacy/，不在就跳过）拉进来跑
python -m tests.run_all --install    # 再跑打包真装检查（需要网络，约 1 分钟）
python -m tests.test_lint            # 也可以单跑某一套
```

解释器路径与 UTF-8 环境变量见 `AGENTS.local.md`。
Python 下限**按命令分**：`pyproject` 写 `>=3.10`（`spec`/`lint`/`evals`/`review` 在 3.10 可用）；
`discover`/`check`/`watch`/`deliver`/`hook` 需要 **≥3.11**（用 `tomllib` 解析 `hosts.toml`）。
推荐统一用 3.11+，省得记哪条命令要哪个版本。

## 三、不许破坏的不变量（每条都有测试守着）

1. **运行时零第三方依赖**：`pyproject.toml` 的 `dependencies` 必须为空（测试里查）。
2. **强制 UTF-8（无 BOM）与 LF**：写文件用 `encoding="utf-8", newline="\n"`。
3. **代码里不得出现宿主名**：宿主布局一律走 `data/hosts.toml`，有测试作为不变量。
4. **判定分级不许混淆**：`FAIL` 阻断 ｜ `WARN` 人工甄别 ｜ `SKIP` = **本项未执行**（计入退出码 2）
   ｜ `INFO` = 不适用（不影响退出码）。"没执行"永远不许伪装成"通过"。
5. **改文档要连测试一起想**：三份文档的命令是被真跑的，改命令就要同步改行尾期望退出码；
  新增文件后《仓库结构说明.md》会因"漏列"而让测试变红（这是刻意的，防止文档与代码脱节）。
6. **stdout 只放报告，进度/落盘提示走 stderr**：否则 `--json` 会被污染（踩过：`review material`、
   `_emit` 的"报告已落盘"）。`--quiet` 会连 JSON 一起静音，机读场景不要加它。
7. **运行时数据必须随包分发**：`skillverify/data/hosts.toml` 与 `data/review-prompts.json`
   要在 `pyproject.toml` 的 `package-data` 里；漏了 `discover`/`review` 直接失效，
   而且**在源码目录里跑永远发现不了**——必须构建 wheel 才看得出（`--install` 会查）。
8. **两份交付文档必须自包含**：不得引用 `handoff/`、`legacy/`、会话文档，不得出现盘符路径。
9. **`legacy/` 已归档出仓库（原先的「冻结语料」不再随仓库分发）**：旧体系语料已归档到仓库外（见 §一）。规则出处写文档级引用，
   **不许**再出现 `legacy/<路径>`（守卫查）；要跑旧语料回归就把语料放回 `legacy/` 或
   用 `--dogfood` 指向的本地目录——但**别把语料提交回来**。
10. **临时目录一律走 `skillverify/tmpdir.py`**（`new_temp_dir` / `temp_dir`），**不许**用
   `tempfile.mkdtemp` / `TemporaryDirectory`——后者按 `mode=0o700` 建目录，在 Windows 沙箱里
   **创建者自己也进不去**（原地实测：`mount` 与 `lint --scripts` 的 dry-run 探针直接抛 `WinError 5`）。
   有 AST 守卫（`tests/test_selfcheck.py::forbidden_tempfile_calls`）挡着，见 §五 第 12 条。
11. **时效性只认显式字段，不许用文件时间推断**：`EVAL-011` 读 `run-inputs.json` 的
   `assertions_added_at`（旧体系 V21 那套 mtime 推断已明确舍弃）；同理 `REV-000` 判"记录过期"
   用**内容指纹**、`WS-004` 用 iteration 编号。改任何"新鲜度"判定时先问：这个事实在文件系统里吗？

## 四、测试里两个"被执行的机制"（改东西前务必知道）

1. **文档里的命令是真跑的**：`tests/test_docs.py` 会执行三份文档里的
   `<!-- runnable -->` 块——《验证流程指南.md`（1 块）、《操作手册.md》（2 块：新建技能 / 已有技能）、
   《迁移与部署指南.md》（1 块），逐条核对实际退出码与行尾 `# N` 标注一致。
   另外它还核对《仓库结构说明.md》与真实文件树一致（不列不存在的、也不漏代码文件）。
   - 块内**整行注释会被忽略**（那里正好用来写"这一步在干什么"）；
   - 行尾注释里的**第一个数字**被当作期望退出码，所以别在行尾注释里写别的数字；
   - 改命令就要同步改期望退出码；新增命令要放进这个块。
2. **注入自测是变异测试**：`tests/test_injection.py` 先造一份全绿基线（参与判定的规则上百条，具体条数看套件输出），
   再对**独立副本**注入 41 处缺陷（39 处单技能 + 2 处库级，见 `LIBRARY_MUTATIONS`），要求「期望规则里至少一条必须报错」且「不许牵连无关规则」。
   - 加新规则时，最好同时加一处覆盖它的变异（`test_coverage` 会检查 17 个规则族全覆盖；
  `AUDIT-*` 由 `tests/test_library.py` 的注入式断言承担，注释里写明了为什么）；
   - 容忍项（`tolerate`）必须写清理由，不要为了让测试变绿。

## 五、踩过的坑（改之前先读，能省一轮返工）

1. **PowerShell here-string 会改坏代码内容**（反引号是转义符、内层引号被吃）。
   症状：`SyntaxError ... Perhaps you forgot a comma?` 指向中文串；更坏的是**内容错了但脚本照跑**。
   → **用 write 工具把补丁写成 `.py` 再执行**。本仓库的历史提交里多处这么做，就是为这个。
2. **中文串里别嵌 ASCII 双引号**，用「」。本仓库代码里大量中文提示语，这条踩过六七次。
3. **模块变包会让 `python -m 包.模块` 失效**（缺 `__main__.py`）。`skillverify/cli/` 拆包时
   正是如此——而 **git hook 的兜底调用就是这个形式**，结果所有提交被拦。
   → 拆包要同时补 `__main__.py`，并把 `packages` 加进 `pyproject.toml`。
4. **评测工作区是技能目录的兄弟目录**（`<技能名>-workspace/`），不是它的子目录。
   写测试夹具时路径写错会**静默地什么都没改**（变异自测里 4 处变异因此没跑到）。
5. **变异文本可能自己抵消变异**：给"无参数解析"的脚本写文档字符串时提到了 `sys.argv` / `--help`，
   静态启发式于是正确地不报——变异白做。改脚本夹具时注意不要引入被检查的关键词。
6. **`sys.argv` 也算"参数解析线索"**（`SCRIPT-003`）；不提供 `--help` 由运行期 `SCRIPT-004` 抓。
7. **规则的范围以规则标题为准**：`I18N-001` 只管**代码块内**的命令行（行内 code span 不算）；
   `REF-007` 认为"正文调用示例里出现"也算列出脚本；`HYG-005` 不把 `evals/files/` 当未归置素材。
   改规则前先读实现，别按直觉改判据。
8. **`pip install -e .` 证明不了 `package-data`**：editable 直接用源码树。
   要验证发布物必须**构建 wheel 并检查包内文件**（`tests/test_packaging.py --install` 做的就是这个）。
9. **Windows 上 `venv/Scripts/x`（无扩展名）跑得起来但 `is_file()` 说不存在**；判存在性带 `.exe`。
10. **规则标题里引用的常量必须定义在 `RULES` 字典之前**。踩过 4 次（`LICENSE_FIELD_MAX`、
    `MIN_ASSERTION_OBSERVATIONS`、`RUN_LOG_NAME`、`RUN_LOG_STALE_DAYS`）：常量写在 `_res`
    或检查函数旁边（即 `RULES` **之后**），导入时就 `NameError`。规则标题是对外文案，会引用
    阈值——加规则时先声明常量再写规则。
11. **测试 helper 抛出前要打印捕获的 stdout/stderr**：否则现象是"套件跑到一半安静地没了"
    （本仓库的 `run_cli` 全都这么做）。
12. **沙箱（AppContainer）下 `tempfile.mkdtemp` 建的目录创建者自己进不去**：它按 `mode=0o700`
    落成"仅所有者"的 DACL，而沙箱的访问检查要求 DACL **同时**授予用户 SID 与容器 SID。
    症状：`mount` 的副本探针与 `lint --scripts` 的 dry-run 探针抛 `PermissionError: [WinError 5]`，
    而 `tempfile` 的清理还会二次抛错——**在普通终端里跑永远复现不了**。
    → 一律用 `skillverify/tmpdir.py`（不传 mode，继承父目录 DACL）；有 AST 守卫挡着。
    另：沙箱里**连 shell 都受限**——`sh.exe` 建不出信号管道（`couldn't create signal pipe, Win32 error 5`），
    所以 git hook 的端到端用例跑不了：**先探针、跑不了记 SKIP**，既不伪装成 PASS 也不让它长成假 FAIL
    （`tests/test_automation.py::sh_can_run_hooks`）。
13. **小样本上不要用"比例"当容差**：旧体系那套 `±0.05 比例` 在 12 条样本上，差一条就是 ~8–14%，
    于是像样的夹具被判成偏斜——**后果不是多一行 WARN，而是基线被染脏**：
    注入自测里"切分全在 train"那处变异因此显得"没被抓住"（基线本来就 WARN，变异后没有新增问题）。
    → 判据按**条数**写（`|实得 − 期望| ≤ 1 条`），与样本量无关；夹具本身也要先像个样子
    （正负例交替排列，别把正例全堆在前面再按下标切分）。
14. **合计对不代表分项对**：《覆盖对照》里的逐族规则数长期写着 评测 29 / 评审 13 / 库级·挂载·审计 15，
    合计 131 却刚好正确——于是没人发现分项全错。现在 `tests/test_consistency.py` 会把它与代码对账
    （加规则时要同步改那两处）。同类的还有：套件数、提示词条数、spec 构成。

## 六、迁移/分发这个项目时要留意

- `handoff/` 与 `.agents/skillverify/` 是本地会话/留痕目录（已 gitignore），**不是交付物**。
  交付物 = `pyproject.toml` + `skillverify/`（含 `data/`）+ 根目录 5 份文档：
  《技能编写指南.md》（作者向）、《验证流程指南.md》（流程/宿主向）、《操作手册.md》（新手向）、
  《迁移与部署指南.md》（新手向）、《仓库结构说明.md》（开发者向），
  另有开发者向的《覆盖对照-生命周期验证方案.md》与本文件。
- `AGENTS.local.md`、`CLAUDE.local.md` 是机器本地覆盖层（已 gitignore），不要提交。
- 依赖：只用标准库；打包需要联网（构建隔离会取 setuptools）。
- 迁移后自检：`python -m tests.run_all --dogfood --install` 应全绿（14 个套件 = 默认 13 + 打包真装；具体断言数看输出，本文件不写死数字）。
- CI 样例在 `.github/workflows/skillverify.yml`：改门禁口径时同步它。
- 库级检查 `LIB-001/002` 在 `library.py`：预算默认 8000 **是本项目约定**（文档里必须保留这句，
  别写成官方口径）；两条都只记 WARN——预算口径由宿主决定，工具不替宿主阻断。
- `audit` 只做「机械结论的汇总 + 指纹留痕」，**不做信任分级**（审计单里留给人填）；
  改审计单时不要删掉「不是安全背书」那句。
- 评测**执行层不自研**：要真跑就 `evals --run-with <命令>` 委托官方工具/宿主，跑完再校验产物。
- `mount` 只做**仓库侧**挂载前置检查（可发现性 / name·description 可读 / 同名冲突 / fail-loud）；
  「不验证宿主注册表」这句写在命令说明与报告 meta 里，**不要删**——它防的是过度承诺。
- **自检套件的三条语义**（都踩过坑，改 `tests/test_selfcheck.py` 前先读）：
  ① `__all__` 里列出**不算被使用**（只声明导出 ≠ 有人用）；② `import` 语句在「查死导入」时不算引用、
  在「查死定义」时算引用；③ 扫描器**自己的文字**不算引用（否则写一句「某某类已经没人用了」，
  死代码就被自己的说明文字说成活的）。另：文档/提交信息里**不要**直接写出待清理的符号名。
- **能力与事实一律走结构化扫描**：`audit` 的口径来自 `security.facts()` / `scripts.facts()` /
  `deps.facts()`，**不许**再从 `Result.evidence` 文本里 `split("：")` 抠数据——那是本项目在 deliver
  里批评并改掉的反模式（措辞一改就静默解析出垃圾）。审计单里也写明了各类的口径。
- **加固轮的四个约定**（都有断言守着）：
  ① `HYG-006/007` 许可：license 字段宜简短、声明了就该有随包文件（都是 WARN）；
  ② `SEC-008` 隐写：代码里的双向控制符记 FAIL、正文里的零宽字符记 WARN（**故意不含 ZWJ**，emoji 合法）；
  ③ `SCRIPT-009` dry-run：在**临时副本**里试跑并比对目录哈希——只能看到技能目录自身的变化；
  ④ `REV-012` 评委校准：判错校准样本（`data/judge-calibration.json`）则结论不可用；没做记 INFO。
- **豁免通道**：`deliver --accept <规则ID> --because <理由>` 把该规则的阻断项记为「已豁免」并落盘。
  它是 §6.1 要求的出口——但**必须显式 + 有理由**，缺理由直接被拒（绝不静默放过）。
- 新增规则/命令时的固定动作：① 规则要写 level 与出处（官方条款或"本项目收紧"）；
  ② 文档里补上并放进演练块（带期望退出码）；③ 补回归断言；④ 跑一遍死代码与过期措辞扫描。
