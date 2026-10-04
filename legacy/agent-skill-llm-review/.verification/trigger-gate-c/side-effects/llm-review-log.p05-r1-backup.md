# LLM 评审日志（V12 留痕）

> 双评 ⚑ 权威范围：W-02、W-04、W-05、W-08、W-15、E-04、E-06、R-02。
> 同一会话内跑两遍不构成双评，不得标"是"。

| 日期 | 提示词编号 | 模型名+版本 | 输出证据（结论摘要/引用） | 判定 | 是否双评 |
| --- | --- | --- | --- | --- | --- |
| 2026-10-01 | W-02 | GLM-5.3-Flash(独立会话A) | [包A] 评委A(包A): description做什么+何时用齐备/第三人称/范围不窄不宽/触发信息全落description/单行无跨行, 五子维全PASS, 证据=SKILL.md L28 description全文 | PASS | 是 |
| 2026-10-01 | W-02 | GLM-5.3-Flash(独立会话B) | [包B] 评委B(包B): 五子维全PASS与A包独立一致, 证据=B-task L28 description功能句+触发句+边界句齐备 | PASS | 是 |
| 2026-10-01 | W-04 | GLM-5.3-Flash(独立会话A) | [包A] 评委A(包A): 正文仅八节核心指令/提示词与双评规则已外移references/变体拆分带命中条件/加载时机明确; 注意: references不复述正文一项因包内未附references正文为有限证据, 待M1人工补证 | PASS | 是 |
| 2026-10-01 | W-04 | GLM-5.3-Flash(独立会话B) | [包B] 评委B(包B): 四子维PASS独立一致; 唯一可精简项=L33版本历史行(约200字非运行必需,不构成FAIL); references不复述正文为有限证据待M1补证 | PASS | 是 |
| 2026-10-01 | W-15 | GLM-5.3-Flash(独立会话A) | [包A] 评委A(包A): 四脚本仅标准库本地读写/无网络无eval无混淆/防护性语义/无外访与声明一致/allowed-tools无需声明; 属初筛, M1-2人工终审待做 | PASS | 是 |
| 2026-10-01 | W-15 | GLM-5.3-Flash(独立会话B) | [包B] 评委B(包B): 独立一致PASS; 子项5 allowed-tools对照因包内无白名单标记需人工裁决(初筛无超用途授权), M1终审待做 | PASS | 是 |
| 2026-10-02 | W-05 | GLM-5.3-Flash(独立会话A) | [包A] 评委A(包A): 逐段核查SKILL.md L24-103无通识/默认行为复述; 事实决策分层=§1能做/不能做硬边界(L36-42); 压缩写法=§5规则3一句规则+反例(L76); 瑕疵=L70英文重复段冗余不判FAIL; 注意: 取材来源清单未随包,属有限证据,待M1人工补证 | PASS | 是 |
| 2026-10-02 | W-05 | GLM-5.3-Flash(独立会话B) | [包B] 评委B(包B): 与A包独立一致PASS; 主体为V12/⚑双评/阶段映射等项目特定知识; 瑕疵=L32版本历史较长+L70英文重复段(不判FAIL); 取材来源清单未随包,有限证据待M1补证 | PASS | 是 |
| 2026-10-02 | W-08 | GLM-5.3-Flash(独立会话A) | [包A] 评委A(包A): 逐操作评审4脚本+正文,全PASS评级均低; plan_dual_review唯一覆盖写限时间戳留痕目录内(L254/284)+盲评realpath判重; record_review追加写不覆盖(L395)+注入清洗(L377-383); detect/summarize全程只读; 无高危无防护/无低危过重 | PASS | 是 |
| 2026-10-02 | W-08 | GLM-5.3-Flash(独立会话B) | [包B] 评委B(包B): 与A包独立一致PASS; 4项操作风险评级均低,防护相称; SKILL.md§1不写回被评审技能提供制度兜底; 非缺陷建议: record_review.py未校验--skill-dir存在性,建议与plan_dual_review对齐加isdir校验(不改判定) | PASS | 是 |
| 2026-10-02 | W-01 | GLM-5.3-Flash | frontmatter仅name/description/compatibility标准字段(L2-4)无宿主私有字段; metadata键不适用; compatibility存运行必要信息非滥用; Python3.10+与宿主声明均必要(V16)四子维PASS | PASS | 否 |
| 2026-10-02 | W-03 | GLM-5.3-Flash | compatibility(L4)声明Python3.10+仅标准库; 核实4脚本import仅os/sys/argparse/datetime/json/random/re全标准库与声明一致; 无网络需求与W-15双评结论一致; 无第三方依赖故无运行器需求; 无漏声明 | PASS | 否 |
| 2026-10-02 | W-06 | GLM-5.3-Flash | §1边界/§2工作流/§3映射表/§4加载时机/§5双评规则/§6留痕/§7Scripts/§8Gotchas分区明确(L11-80); 高频操作(工作流+映射+双评规则)详细/低频(D-01可选辅助)从简(L34); 无游离于声明范围外内容; 瑕疵=L9版本历史约200字偏长属变更记录不判FAIL | PASS | 否 |
| 2026-10-02 | W-07 | GLM-5.3-Flash | 刚性语句清单: §1硬边界5条各有理由与后果标注(L14-19); §5同一会话两遍不构成双评有V12定义依据(L53); 勿攒批有留痕即时性理由(L27); §8勿据建议跳终审/盲评映射勿接触均有依据(L76/78); 无ALWAYS/NEVER滥用, 均祈使句直接指示, 未过度限制正常路径 | PASS | 否 |
| 2026-10-02 | W-09 | GLM-5.3-Flash | record_review可设默认参数均有合理默认: --dual默认不适用/--package默认空(record_review.py:51-53); 正文无让LLM反问用户自行决定事项, 工作流6步明确(L23-28); 方法泛化: 所有脚本以--skill-dir参数化通用于任意目标技能目录, 非绑定一次性场景 | PASS | 否 |
| 2026-10-02 | W-10 | GLM-5.3-Flash | Gotchas 5条(L76-80)均具体含触发场景与正确做法: 建议≠完成给出口判据+人工签认/W-02分歧给双原始输出贴证据+写明采纳理由/盲评映射只在汇总还原时打开/secret命中即停止投喂上报/自身修改映射到对应双评项; 模板为真实文件assets/llm-review-log-template.md(Glob证实存在)非文字描述; 留痕字段说明有V12必要性非凑结构; Gotchas位于§8末尾 | PASS | 否 |
| 2026-10-02 | W-11 | GLM-5.3-Flash | 预审: description触发词(评审技能/跑W组语义检查/对断言评分/做盲评/诊断轨迹/归纳Gotchas)与evals正例id1-6一一对应; 负例id8-10由不替代check_skill.py/人工终审/门禁裁决显式排除(L3尾句); 与相邻技能skill-authoring(编写规范库)/skill-creator(创建指导)/base(生成基座)语义边界可辨, 本技能专司评审执行, 串扰风险低; 最终以E阶段触发回归实测为准 | PASS | 否 |
| 2026-10-02 | W-12 | GLM-5.3-Flash | evals.json 12条达个人版下限(note L4已声明6正/6负); 正例id1-6均有真实语境感如id1按生命周期验证方案跑W组记得留痕; 负例id8-11为相邻域near-miss(机械检查行数/S类静态检查/H类终审/M1验收报告)非随意负例; 正例无模糊提示, id12今天天气属刻意无关闲聊负例 | PASS | 否 |
| 2026-10-02 | W-13 | GLM-5.3-Flash | 断言=should_trigger布尔+prompt_id归属双重判定, 判定依据明确(是否触发且路由到标注的提示词组)可验证; 无效果要好类模糊断言; 不依赖精确措辞匹配不脆弱; 范围恰当仅覆盖触发与路由不过宽不过窄; id2-6另附prompt_id上下文佐证 | PASS | 否 |
| 2026-10-02 | W-14 | GLM-5.3-Flash | 四脚本(detect_stage84行/record_review80行/plan_dual_review128行/summarize_reviews83行)职责专属(V12留痕格式/任务包生成)非重复造轮子; 前置声明与实际一致(compatibility称仅标准库,import核实相符); 复杂逻辑全在脚本, 正文§7仅一行用法; 错误消息三段式含错了什么+用法+下一步如detect_stage.py:40缺少参数提示/record_review退出码2区分双评警告/summarize_reviews:37日志缺失给下一步 | PASS | 否 |
| 2026-10-02 | W-16 | GLM-5.3-Flash | 术语一致: 双评/留痕(V12)/任务包/⚑/阶段代号D-W-E-M-R全文同名无近义漂移(L13-80); 表达机器可读优先: 命令均代码块且参数明确(§7 L63-72), 指令明确优于含糊描述; 可移植性: 无宿主专属路径/工具名语义残留, 命令用通用python scripts/相对路径, frontmatter无宿主私有字段 | PASS | 否 |
