# skillverify —— Agent Skill 生命周期验证套件

[![CI](https://github.com/yianyao/skillverify/actions/workflows/skillverify.yml/badge.svg)](https://github.com/yianyao/skillverify/actions/workflows/skillverify.yml)

> 让 Agent Skill 在**任何宿主**上都能被验证：官方规范 → 机械补检 → 评测资产 → 语义评审 → 交付门禁，
> 一条流水线全覆盖。宿主无关、纯标准库、零第三方依赖。

## 为什么需要它

[Agent Skills](https://agentskills.io) 是开放规范，官方校验器 `skills-ref` 只查 frontmatter 的 6 个字段。
而一个技能真正要回答的问题是：

- 写得对不对？—— 引用会不会断、脚本会不会卡、依赖有没有钉版本、有没有夹带密钥；
- 会不会被触发？—— description 写窄了漏触、写宽了误触；
- 干活行不行？—— 有没有质量证据（A/B 对照、断言、判分）；
- 能不能交付？—— 上面这些没查完，谁来拦。

`skillverify` 把这四问做成一条**五层验证流水线**：

| 层 | 命令 | 查什么 | 官方覆盖吗 |
| --- | --- | --- | --- |
| 官方规范 | `spec` | frontmatter 6 字段与命名约定（离线对齐官方行为，可加 `--official` 与官方工具对账） | 是 |
| 机械补检 | `lint` | 引用、上下文预算、目录卫生、脚本契约实测、依赖钉版本、安全（密钥／下载即执行／隐藏字符）、编码——47 条规则 | 否，官方留白 |
| 评测资产 | `evals` | 官方 `evals/evals.json`（输出质量）＋ `evals/trigger-queryset.json`（会不会被触发）与运行产物的机械对账 | 质量给了约定没给工具；触发根本不覆盖 |
| 语义评审 | `review` | 32 条带判据的评审提示词（描述质量、可验证性、破坏性操作防护…），三种执行方式产出同一 schema | 否，留白 |
| 交付门禁 | `deliver` | 汇总以上全部结论：FAIL 阻断、WARN 可人工签认、豁免必须书面留痕 | 否，留白 |

另有 7 个辅助命令：`discover`（整库发现）、`check`（一键全量）、`mount`（挂载前置检查）、
`audit`（外来技能审计＋内容指纹）、`watch`（开发期监听）、`hook`（提交门禁）、`describe`（机读命令面契约）。

## 设计纪律（这套工具的底线）

- **宿主无关**：宿主的目录布局是数据（`hosts.toml`）不是代码，接入新宿主 0 行代码改动；代码里不出现任何宿主名。
- **纯标准库**：运行时零第三方依赖，Python ≥3.11 全功能（3.10 可用 `spec`/`lint`/`evals`/`review`）。
- **"没查"不许伪装成"过了"**：SKIP（未执行）与 WARN 计入退出码 2，与 PASS、与"不适用"（INFO）严格区分。
- **强制 UTF-8**：Windows 的 GBK 控制台曾把旧工具链直接打崩，这里从 IO 层根治。
- **fail-loud**：解析器遇到损坏输入必须报错——用注入探针对着自己的解析器验证。
- **豁免要留痕**：门禁的每条豁免必须配书面理由并写进交付记录；人工裁决绑定证据指纹，证据一变自动失效。

## 安装

```bash
pip install skillverify                    # PyPI 安装（推荐）
uvx skillverify --version                  # 免安装直接跑（uv）
git clone https://github.com/yianyao/skillverify && cd skillverify
python -m pip install -e .                 # 源码可编辑安装
```

## 五分钟上手

```bash
skillverify discover --show-config                    # 它认哪些技能目录、合并了哪些配置
skillverify lint .agents/skills/<你的技能> --scripts   # 机械补检 + 真跑技能自带脚本实测契约
skillverify evals .agents/skills/<你的技能>            # 评测资产与运行产物校验
skillverify check --trace                             # 整库总检，报告落中央留痕目录
skillverify hook install                              # 提交门禁（pre-commit 自动跑交付检查）
skillverify deliver --strict                          # 交付门禁：连"未执行"都阻断，发行前跑一次
```

退出码：**0** 全过 ／ **1** 有 FAIL ／ **2** 有 WARN 或"未执行"——`2` 不是出错，是"还有事没做完"的诚实信号。

## 评测怎么做

技能作者写两份"卷子"：`evals/evals.json`（质量：prompt＋期望＋断言）与
`evals/trigger-queryset.json`（触发：正负例各 8–10 条，负例以近似误触为主）。
**执行一律委托外部 runner**（官方 skill-creator、你的宿主、或 `examples/` 里的模板脚本），
本工具负责校验资产与产物——A/B 对照、判分汇总、触发率阈值、运行声明（隔离方式与输入哈希）
全部有机械对账，没隔离的轮次会被标成"参考级证据"而不是增益。

## 换机器 / 部署

《迁移与部署指南.md》讲清三件事：**要带哪些文件**（纯标准库，复制即走）、**不要带哪些**
（本机留痕与本机配置）、**换机器收尾三件事**（hook 重装、用户级配置、操作台快照重建）。
接到 CI 只需一行：

```yaml
- uses: yianyao/skillverify@v0.1.0
  with:
    skills-root: "."
    strict: "true"
```

## 本地操作台（可选）

`console/` 把「哪条流程、每个节点要什么数据、有哪些参数、产出什么」做成可点击、可校验的本地页面：
静态模式双击即用（断网可用），起执行桥后可在页面里直接执行白名单命令
（仅监听 127.0.0.1、逐参数校验、全程审计）。详见 `console/README.md`；
不需要就整个目录删掉，零侵入。

## 文档

| 文档 | 内容 |
| --- | --- |
| 《验证流程指南.md》 | 全命令参考与退出码语义 |
| 《操作手册.md》 | 按场景的完整操作序列（评测／评审／门禁） |
| 《迁移与部署指南.md》 | 搬工具、搬技能、接 CI、发 PyPI |
| 《技能编写指南.md》 | 写技能时的规范与最佳实践 |
| 《仓库结构说明.md》 | 每个文件是干什么的 |
| `console/README.md` | 操作台的构建与执行桥 |

## 测试与质量纪律

`python -m tests.run_all` 一条命令跑全部回归：官方规范的注入自测（数十处变异必须逐处报错且不牵连）、
机械规则逐条覆盖、评测资产对账、语义评审校验、文档演练块**真跑**、操作台产物防漂移、
执行桥安全端到端（真实起桥后发敌意请求）。文档与代码的一致性由专门套件持续看管——
文档说法与代码行为冲突时，以代码为准并视为守卫该扩面的信号。

## License

[MIT](LICENSE)
