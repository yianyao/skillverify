# 安装审计执行单（V13）+ E4 安全门全表核对

- **对象技能**：agent-skill-llm-review（v1.3，SKILL.md SHA256 `f368295e…`，双盘一致）
- **审计类型**：自研技能交付审计（非第三方；V13 单仍按 §9.10 全项出具）
- **审计日期**：2026-10-02　**执行**：主会话 K 层（静态）+ 120 次子代理实测佐证（动态）
- **审计工具**：gate-m/check_m1s.py（本次专项，14 项静态检查）+ 内联脚本（E4 补充项）

## 一、V13 §9.10 全项核对

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| 1 | frontmatter 一致性 | PASS | name=目录名，description/compatibility 解析正常；A3/A11 PASS |
| 2 | scripts 行为审计 | PASS | 4 脚本均为本地文件 IO（read/append/写 .verification），无网络（requests/urllib/socket/subprocess 零引用）、无删除/覆盖被评审技能文件逻辑；V6 冒烟（--help/缺参退出码/坏目录退出码）全部符合文档声明 |
| 3 | 外部请求目标 | PASS | §9.2 端点提取 = none（SKILL.md + references + scripts 全量） |
| 4 | 依赖 | PASS | compatibility 声明"仅标准库"，实测零第三方 import；Python 3.13.12 ≥ 3.10（V5） |
| 5 | 外部路径引用 | PASS | §10.1 脚本内无 ~/$HOME/盘符硬编码（clean） |
| 6 | 第三方素材许可（V15） | **已裁决关闭（2026-10-02 人工裁决：不加 license）** | 全技能无 license 字段、无 LICENSE 文件。技能为自研原创内容、无第三方素材引入，交付风险低；人工裁决本技能**限定内部使用、不添加 license**。⚠ 若未来对外发布/进入市场，须先补 license 字段 + 随包 LICENSE 文件并复跑 V15 |

## 二、E4 安全门（§9.1–§9.10）全表核对

| 条目 | 结果 | 证据/说明 |
|---|---|---|
| §9.1 恶意代码（静态） | PASS | 无混淆/编码执行/eval(requests) 特征；语义侧由 120 次子代理实测与历轮 L 评审佐证 |
| §9.2 不可信端点 | PASS | 端点提取 = none，与 compatibility"无网络需求"一致 |
| §9.3 授权最小化 | PASS | 无 allowed-tools 白名单声明（不需要）；脚本仅读写技能自身 .verification 目录 |
| §9.4 防护（注入面） | PASS | 脚本输入均为 CLI 参数；record_review 对 HEADER 冒号/换行有防护（v1.2 修复项） |
| §9.5 安装审计 | PASS | 本单即审计记录，随包留档 |
| §9.6 敏感信息 | PASS | secret 正则库扫描（key=value/sk-/ghp_/AKIA/私钥块）零命中 |
| §9.7 用途一致性 | PASS | name/description 与实际行为（评审调度/双评包/留痕/汇总）一致；120 次触发实测无"最少惊讶"违例（已知局限 P09 类为召回偏低，非越界行为） |
| §9.8 危险指令 | PASS（白名单） | 3 处命中均在 w-prompts.md 评审检测词表内（提示评审员检查被测对象用的关键词），非技能自身行为 |
| §9.9 数据处理 | PASS | 仅写技能 .verification/ 留痕文件，无遥测外发 |
| §9.10 第三方素材 | PASS | 无第三方素材引入（V15 OPEN 项仅涉及许可证声明本身） |

## 三、E4 判定

**PASS（0 项 [M] FAIL，0 项 OPEN）**。V15 经人工裁决（2026-10-02）关闭：不加 license、限定内部使用；如未来对外发布须重新评估并补录。

## 附：随单留档的杂散产物台账（M0 期间）

- `side-effects/V4-r1r2-weekly-report-archiver-skill/`：V4 共存冒烟中子代理真实创建并安装的测试技能（含 zip），已整体移出用户技能目录留证——V4 串扰测试的副产物，非交付内容。
