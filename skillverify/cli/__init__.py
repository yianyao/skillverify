"""cli —— skillverify 命令行入口（装配层）。

约定（全族统一，便于任何宿主/CI 消费）：
- 退出码：0=全 PASS；1=有 FAIL；2=无 FAIL 但有 WARN/SKIP。
- 报告默认打到 stdout；`--out` 可落盘；`--json` 输出机读结构（`deliver` 输出交付记录本身）。
- 参数错误一律 stderr + 用法 + 退出码 1（不撞 WARN 码 2）。

实现分放在 `common.py`（共用工具）与 `commands.py`（各命令），本文件只负责把
参数解析器装配起来并分发。
"""

from __future__ import annotations

import sys

from .. import __version__
from ..encoding import force_utf8_stdio
from ..library import DEFAULT_METADATA_BUDGET, DEFAULT_OVERLAP
from .commands import (
    cmd_audit,
    cmd_check,
    cmd_mount,
    cmd_deliver,
    cmd_discover,
    cmd_evals,
    cmd_hook,
    cmd_lint,
    cmd_review,
    cmd_spec,
    cmd_watch,
)
from .common import PROG, _ArgParser, _add_common, _add_discovery_options

def build_parser() -> _ArgParser:
    parser = _ArgParser(
        prog=PROG,
        description="Agent Skill 生命周期验证套件（个人小团队版，宿主无关）",
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<命令>")

    p_spec = sub.add_parser(
        "spec",
        help="官方规范校验（frontmatter 6 字段白名单与命名约定）",
        description=(
            "按官方 Agent Skills 规范校验单个技能。离线实现，行为对齐 "
            "skills-ref 0.1.1；加 --official 可与官方 CLI 对账。"
        ),
    )
    p_spec.add_argument("path", help="技能目录（含 SKILL.md）")
    p_spec.add_argument("--official", action="store_true",
                        help="额外调用官方 agentskills validate 对账")
    _add_common(p_spec)
    p_spec.set_defaults(func=cmd_spec)

    p_lint = sub.add_parser(
        "lint",
        help="官方留白的补检（引用/预算/卫生/脚本契约/依赖/安全/编码）",
        description=(
            "对单个技能做官方校验器不覆盖的检查。默认只做静态检查，"
            "不执行任何脚本；--scripts 会以 `--help` 与一个非法参数调用技能自带脚本，"
            "用于实测脚本契约（存在副作用风险，故须显式开启）。"
        ),
    )
    p_lint.add_argument("path", help="技能目录（含 SKILL.md）")
    p_lint.add_argument(
        "--scripts", action="store_true",
        help="执行技能自带脚本以实测 --help/错误路径/幂等（默认关闭）",
    )
    p_lint.add_argument(
        "--script-timeout", type=float, default=10.0, metavar="秒",
        help="单个脚本的超时上限（默认 10 秒）",
    )
    _add_common(p_lint)
    p_lint.set_defaults(func=cmd_lint)

    p_evals = sub.add_parser(
        "evals",
        help="评测资产校验（官方 evals.json + 评测工作区产物）",
        description=(
            "校验官方评测约定：evals/evals.json 的形状，以及并列工作区 "
            "`<技能名>-workspace/iteration-N/eval-*/{with_skill,without_skill|old_skill}/"
            "{outputs,timing.json,grading.json}` 与 benchmark.json / feedback.json。"
            "没有评测资产时记 WARN 并说明（「没有 evals」不该和「evals 全绿」长得一样）。"
        ),
    )
    p_evals.add_argument("path", help="技能目录（含 SKILL.md）")
    p_evals.add_argument("--workspace", metavar="目录",
                         help="评测工作区（默认找并列的 <技能名>-workspace/）")
    p_evals.add_argument("--iteration", type=int, metavar="N",
                         help="只校验 iteration-N（默认校验全部）")
    p_evals.add_argument("--run-with", metavar="命令", default=None,
                         help="委托执行评测：在技能目录里跑这条命令（例如官方评测器的入口），"
                              "跑完再校验产物。命令由你给出——本工具不猜官方评测器的参数")
    p_evals.add_argument("--run-timeout", type=float, default=1800.0, metavar="秒",
                         help="委托执行的超时下限（默认 1800 秒）")
    _add_common(p_evals)
    p_evals.set_defaults(func=cmd_evals)

    p_disc = sub.add_parser(
        "discover",
        help="列出技能发现结果（声明式宿主适配，不做检查）",
        description=(
            "按 hosts.toml 声明的技能根发现技能，并打印每个根的命中情况。"
            "接入新宿主只需在 hosts.toml 里加一段 [hosts.<名>]，无需改代码；"
            "也可以用 --root 直接指定技能根来模拟任意布局。"
        ),
    )
    _add_discovery_options(p_disc)
    p_disc.add_argument("--show-config", action="store_true",
                        help="只打印合并后的有效配置（含来源顺序），不做发现")
    _add_common(p_disc)
    p_disc.add_argument("--metadata-budget", type=int, default=DEFAULT_METADATA_BUDGET,
                         metavar="字符数",
                         help=f"库内所有技能 name+description 的总量预算（默认 "
                              f"{DEFAULT_METADATA_BUDGET}，本项目约定、非官方硬线；"
                              f"按你宿主实测的上限改）")
    p_disc.add_argument("--desc-overlap", type=float, default=DEFAULT_OVERLAP, metavar="比例",
                         help=f"描述词面重叠的告警阈值（默认 {DEFAULT_OVERLAP}；"
                              f"只提示、不阻断）")
    p_disc.set_defaults(func=cmd_discover)

    p_audit = sub.add_parser(
        "audit",
        help="外来技能审计：组合各阶段结论成一张单子，并留下内容指纹供下次比对",
        description=(
            "给**外来技能**（网上/别人给的）出一张「要不要用它」的单子：来源、能力清单"
            "（脚本/网络端点/破坏性操作/疑似密钥/依赖）、判定明细、内容指纹，"
            "以及与你库内其它技能的名字近似提示。再审计时会比对指纹，提示内容是否被换过。"
            "\n\n"
            "**明确不做**：不跑技能脚本（除 `--scripts`）、不模拟触发、不做信任分级"
            "（那需要人判断——审计单里留了一栏给人填）。"
        ),
    )
    p_audit.add_argument("target", metavar="技能目录或技能名",
                         help="要审计的技能目录；也可以是 `discover` 能发现的技能名")
    p_audit.add_argument("--project", default=".", metavar="目录", help="项目根（默认当前目录）")
    p_audit.add_argument("--user-home", metavar="目录", help="解析 ~ 的基准目录")
    p_audit.add_argument("--config", action="append", metavar="文件", help="额外的 hosts.toml")
    p_audit.add_argument("--no-config", action="store_true", help="只用内置配置")
    p_audit.add_argument("--root", action="append", metavar="目录",
                         help="技能根（可重复；用于找库内其它技能比对名字）")
    p_audit.add_argument("--host", metavar="档名", help="使用的宿主档")
    p_audit.add_argument("--scripts", action="store_true",
                         help="以 `--help` 调用技能自带脚本（默认不执行——审计外来技能尤其慎用）")
    p_audit.add_argument("--record", action="store_true",
                         help="把审计单落盘到 <trace_dir>/audit/（供下次比对指纹）")
    p_audit.add_argument("--out", metavar="文件", help="把报告写到文件")
    p_audit.add_argument("--json", action="store_true", help="输出机读 JSON")
    p_audit.add_argument("--quiet", action="store_true", help="不打印审计单正文")
    p_audit.set_defaults(func=cmd_audit)

    p_mount = sub.add_parser(
        "mount",
        help="挂载前置检查（仓库侧）：可发现性 / name·description 可读 / 同名冲突 / fail-loud",
        description=(
            "上宿主**之前**在仓库侧能确定的那几件事：技能是否真的落在该宿主档声明的目录里、"
            "SKILL.md 是否可解析且 name/description 都读得出来、同一宿主档内有没有同名冲突，"
            "以及把三种结构损坏的 frontmatter 注入**临时副本**后解析器是否 fail-loud（不触碰原目录）。"
            "\n\n"
            "**不验证**宿主注册表与真实触发匹配：本工具没有宿主 API，也没有宿主运行时。"
            "宿主侧那部分请在目标宿主里人工确认（见《操作手册.md》）。"
        ),
    )
    p_mount.add_argument("--host", metavar="档名",
                         help="只检查该宿主档（默认逐个检查配置里的全部宿主档）")
    p_mount.add_argument("--all-hosts", action="store_true",
                         help="逐个检查配置里的**全部**宿主档（新接宿主时用它验收；"
                              "默认只查当前生效的那个档）")
    p_mount.add_argument("--skill", metavar="技能名",
                         help="只检查这个技能（默认检查每个宿主档里发现的全部技能）")
    p_mount.add_argument("--project", default=".", metavar="目录", help="项目根（默认当前目录）")
    p_mount.add_argument("--user-home", metavar="目录", help="解析 ~ 的基准目录（默认当前用户主目录）")
    p_mount.add_argument("--config", action="append", metavar="文件",
                         help="额外的 hosts.toml（可重复，按给定顺序覆盖）")
    p_mount.add_argument("--no-config", action="store_true",
                         help="忽略用户级/项目级配置，只用内置配置")
    p_mount.add_argument("--out", metavar="文件", help="把报告写到文件")
    p_mount.add_argument("--json", action="store_true", help="输出机读 JSON")
    p_mount.add_argument("--quiet", action="store_true", help="不打印报告正文")
    p_mount.set_defaults(func=cmd_mount)

    p_check = sub.add_parser(
        "check",
        help="对整库批量执行 spec + lint 并输出汇总",
        description=(
            "发现技能后逐个跑官方规范校验与补检，输出整库汇总报告。"
            "未发现任何技能时返回 1——「什么都没检查」不允许看起来像通过。"
        ),
    )
    _add_discovery_options(p_check)
    p_check.add_argument("--stages", choices=("all", "both", "spec", "lint", "evals", "review"),
                         default="both",
                         help="跑哪些阶段（默认 both = spec+lint，日常快查；"
                              "all = 再加评测资产与语义评审记录）")
    p_check.add_argument("--workspace", metavar="目录",
                         help="评测工作区（默认找并列的 <技能名>-workspace/）")
    p_check.add_argument("--iteration", type=int, metavar="N",
                         help="只校验 iteration-N（默认全部）")
    p_check.add_argument("--metadata-budget", type=int, default=DEFAULT_METADATA_BUDGET,
                         metavar="字符数",
                         help=f"库内所有技能 name+description 的总量预算（默认 "
                              f"{DEFAULT_METADATA_BUDGET}，本项目约定、非官方硬线；"
                              f"按你宿主实测的上限改）")
    p_check.add_argument("--desc-overlap", type=float, default=DEFAULT_OVERLAP, metavar="比例",
                         help=f"描述词面重叠的告警阈值（默认 {DEFAULT_OVERLAP}；"
                              f"只提示、不阻断）")
    p_check.add_argument("--scripts", action="store_true",
                         help="执行技能自带脚本以实测脚本契约（默认关闭，存在副作用风险）")
    p_check.add_argument("--script-timeout", type=float, default=10.0, metavar="秒",
                         help="单个脚本的超时上限（默认 10 秒）")
    p_check.add_argument("--skip-review", action="store_true",
                         help="跳过语义评审记录检查（显式跳过会留痕为未覆盖项）")
    p_check.add_argument("--official", action="store_true",
                         help="额外调用官方 agentskills validate 对账")
    p_check.add_argument("--trace", action="store_true",
                         help="把报告写入配置里的中央留痕目录（trace_dir）")
    _add_common(p_check)
    p_check.set_defaults(func=cmd_check)

    p_watch = sub.add_parser(
        "watch",
        help="监听技能库变化并即时复跑（开发期即时反馈）",
        description=(
            "轮询技能库（默认 1 秒一次，纯标准库，不依赖平台专属事件 API），"
            "只复跑指纹变化的技能。默认不执行技能自带脚本——高频复跑下反复执行脚本"
            "既慢又有副作用；要实测脚本契约请手动跑 `lint --scripts`。"
        ),
    )
    _add_discovery_options(p_watch)
    p_watch.add_argument("--stages", choices=("both", "spec", "lint"), default="both",
                         help="跑哪些阶段（默认 spec+lint；评测资产不随敲代码变化，"
                              "要看评测资产请用 `check --stages evals`）")
    p_watch.add_argument("--interval", type=float, default=1.0, metavar="秒",
                         help="轮询间隔（默认 1 秒，最小 0.01）")
    p_watch.add_argument("--cycles", type=int, metavar="N",
                         help="跑 N 轮后退出（默认不限轮数）")
    p_watch.add_argument("--once", action="store_true", help="等价于 --cycles 1")
    p_watch.add_argument("--script-timeout", type=float, default=10.0, metavar="秒",
                         help="单个脚本的超时上限（默认 10 秒）")
    p_watch.add_argument("--json", action="store_true",
                         help="每轮输出一行 JSON（便于管道消费）")
    p_watch.set_defaults(func=cmd_watch)

    p_deliver = sub.add_parser(
        "deliver",
        help="交付门禁：0 FAIL 且 0 未覆盖项，并写交付记录",
        description=(
            "交付门禁比 `check` 严：FAIL 阻断；WARN 不阻断但逐条记入交付记录；"
            "SKIP 里属「未开启的可选批次/环境能力不足」的记未覆盖项（默认不阻断，"
            "`--strict` 时阻断），其余 SKIP 一律阻断。"
            "通过或未通过都会写交付记录到中央留痕目录。"
        ),
    )
    _add_discovery_options(p_deliver)
    p_deliver.add_argument("--staged", action="store_true",
                           help="只检查 git 暂存内容涉及的技能（pre-commit 用）")
    p_deliver.add_argument("--strict", action="store_true",
                           help="连「未覆盖项」也阻断（发行前跑一次）")
    p_deliver.add_argument("--accept", action="append", metavar="规则ID", default=None,
                           help="把该规则的阻断项记为「已豁免」（必须配 --because 写明理由；"
                                "会写进交付记录，绝不静默放过）")
    p_deliver.add_argument("--because", metavar="理由", default=None,
                           help="豁免理由（与 --accept 同用）")
    p_deliver.add_argument("--stages", choices=("all", "both", "spec", "lint", "evals", "review"),
                           default="all",
                           help="跑哪些阶段（默认 all = spec+lint+evals+review：交付要考虑"
                                "该技能已有的全部资产与评审结论；both = spec+lint）")
    p_deliver.add_argument("--scripts", action="store_true",
                           help="实测脚本契约（与 check 的 --scripts 同义：以 --help 等调用"
                                "技能自带脚本）。不开启时 SCRIPT 族规则记「未执行」，"
                                "--strict 门禁会被它们拦住")
    p_deliver.add_argument("--workspace", metavar="目录",
                           help="评测工作区（默认找并列的 <技能名>-workspace/）")
    p_deliver.add_argument("--iteration", type=int, metavar="N",
                           help="只校验 iteration-N（默认全部）")
    p_deliver.add_argument("--script-timeout", type=float, default=10.0, metavar="秒",
                           help="单个脚本的超时上限（默认 10 秒）")
    p_deliver.add_argument("--no-record", action="store_true",
                           help="不写交付记录（--json 仍会输出记录内容）")
    p_deliver.add_argument("--skip-review", action="store_true",
                           help="跳过语义评审记录检查（默认参与；显式跳过会留痕）")
    p_deliver.add_argument("--verbose", action="store_true",
                           help="把未覆盖项与待甄别项也逐条打到 stderr")
    p_deliver.add_argument("--json", action="store_true",
                           help="输出交付记录本身（含门禁结论）而非人读报告")
    p_deliver.add_argument("--out", help="报告落盘路径（.md，或按 --json 输出 .json）")
    p_deliver.add_argument("--quiet", action="store_true", help="不打印报告正文")
    p_deliver.set_defaults(func=cmd_deliver)

    p_hook = sub.add_parser(
        "hook",
        help="安装/查看 pre-commit 交付门禁",
        description=(
            "在 git 仓库里安装 pre-commit hook，提交时自动执行 "
            "`skillverify deliver --staged`。已存在他人 hook 时不改动，"
            "`--force` 会先备份再覆盖。"
        ),
    )
    hook_sub = p_hook.add_subparsers(dest="hook_action", metavar="<动作>")
    for action, help_text in (("install", "安装/更新 pre-commit hook"),
                              ("status", "查看 hook 状态")):
        p = hook_sub.add_parser(action, help=help_text)
        p.add_argument("--project", default=".", metavar="目录", help="仓库目录（默认当前目录）")
        if action == "install":
            p.add_argument("--force", action="store_true",
                           help="覆盖已存在的他人 hook（先备份为 .bak）")
            p.add_argument("--fail-closed", action="store_true",
                           help="找不到 skillverify 时阻断提交（默认故障开放，只告警）")
        p.set_defaults(func=cmd_hook)
    p_hook.set_defaults(func=cmd_hook, hook_action=None)

    p_review = sub.add_parser(
        "review",
        help="语义评审：提示词目录 / 任务包 / 回写汇总 / 独立技能包",
        description=(
            "机械检查之外的判断交给语义评审：提示词目录（旧体系 29 条 + 本项目新增，"
            "含指令注入 W-17），每条带 PASS/FAIL 判据与证据要求。"
            "三档执行器产出同一 schema——档 1 任意 CLI（把任务包喂给它）、"
            "档 2 会话任务包（任意 LLM 或人填写）、档 3 人工兜底（手写同一 JSON）。"
        ),
    )
    review_sub = p_review.add_subparsers(dest="review_action", metavar="<动作>")

    r_prompts = review_sub.add_parser("prompts", help="列出/渲染提示词目录（含判据）")
    r_prompts.add_argument("--family", action="append", metavar="D|W|E|R",
                           help="只显示某家族（可重复）")
    r_prompts.add_argument("--prompts", metavar="id1,id2", help="只显示指定 id")
    r_prompts.add_argument("--json", action="store_true", help="输出机读 JSON")
    r_prompts.add_argument("--out", help="落盘路径")
    r_prompts.add_argument("--quiet", action="store_true", help="不打印正文")
    r_prompts.set_defaults(func=cmd_review)

    r_pack = review_sub.add_parser("pack", help="生成语义评审任务包（含回写模板）")
    r_pack.add_argument("path", help="被评审的技能目录")
    r_pack.add_argument("--prompts", metavar="id1,id2", help="只评指定 id（默认全部条目）")
    r_pack.add_argument("--family", action="append", metavar="D|W|E|R",
                        help="只评某家族（可重复）")
    r_pack.add_argument("--out", metavar="目录",
                        help="任务包输出目录（默认 <技能>-review/）")
    r_pack.add_argument("--split", action="store_true",
                        help="每条提示词一个 Markdown 文件（便于一条一个 LLM 调用）")
    r_pack.set_defaults(func=cmd_review)

    r_collect = review_sub.add_parser("collect", help="校验回写并汇总进中央记录")
    r_collect.add_argument("files", nargs="*", help="回写 JSON 文件（可多个）")
    r_collect.add_argument("--dir", metavar="目录", help="汇总该目录下的全部 *.json")
    r_collect.add_argument("--skill-dir", metavar="目录",
                           help="被评审的技能目录（用于记录内容指纹与覆盖范围）")
    r_collect.add_argument("--no-store", action="store_true", help="只校验，不写中央记录")
    r_collect.add_argument("--json", action="store_true", help="输出机读 JSON")
    r_collect.add_argument("--out", help="报告落盘路径")
    r_collect.add_argument("--quiet", action="store_true", help="不打印报告正文")
    _add_discovery_options(r_collect)
    r_collect.set_defaults(func=cmd_review)

    r_run = review_sub.add_parser(
        "run",
        help="档 1 执行器：把提示词喂给任意命令，收回同一 schema 的回写",
        description=(
            "逐条把提示词送上 runner 的 stdin，从 stdout 取回 JSON 结论，组装成与"
            "档 2（会话任务包）/档 3（人工）**完全相同**的回写，再走同一条 collect 校验。"
            "runner 失败（非零退出/超时/输出不可解析）不会被写成 NA——那会把工具故障"
            "伪装成「本项不适用」；失败条目直接不产出并以非零退出码报出来。"
        ),
    )
    r_run.add_argument("path", help="被评审的技能目录")
    r_run.add_argument("--runner", metavar="命令",
                       help="评审命令（读 stdin、把 JSON 打到 stdout）；以你的权限执行")
    r_run.add_argument("--prompts", metavar="W-01,W-13", help="只跑指定提示词（默认全部条目）")
    r_run.add_argument("--timeout", type=float, default=180.0, metavar="秒",
                       help="单条提示词超时（默认 180 秒）")
    r_run.add_argument("--allow-partial", action="store_true",
                       help="部分条目失败时只记 WARN（默认记 FAIL 并返回非零）")
    r_run.add_argument("--out", metavar="目录", help="把回写落到该目录（便于复核 runner 产出）")
    r_run.add_argument("--collect", action="store_true",
                       help="顺带跑 collect，把结论写进中央记录")
    _add_discovery_options(r_run)   # --collect 需要留痕目录（与 collect 动作同一套定位方式）
    r_run.add_argument("--json", action="store_true", help="输出机读 JSON")
    r_run.add_argument("--quiet", action="store_true", help="不打印报告正文")
    r_run.set_defaults(func=cmd_review)

    r_material = review_sub.add_parser(
        "material",
        help="生成语义评审所需材料（E-02 描述 diff / E-03 修订信号 / E-06 盲评 / "
             "E-07·E-08 工作区数字 / W-11 相邻技能边界清单）",
        description=(
            "有几条提示词评的不是技能文件本身，而是流程产物或技能集合。本命令把它们摘成材料文件，"
            "生成不了就记 SKIP 并说明缺什么——让「材料没准备」与「准备好了」在报告里能区分开。"
            "相邻技能边界清单只在**同级目录**里找邻居（分类嵌套布局会漏）。"
        ),
    )
    r_material.add_argument("path", help="被评审的技能目录")
    r_material.add_argument("--out", metavar="目录",
                            help="材料输出目录（默认 <技能名>-review-material/）")
    r_material.add_argument("--workspace", metavar="目录",
                            help="评测工作区（默认找并列的 <技能名>-workspace/）")
    r_material.add_argument("--diff-base", metavar="引用",
                            help="description diff 的基线引用（默认 HEAD）")
    r_material.add_argument("--blind", nargs=2, metavar=("A", "B"),
                            help="盲评用的两版产物（目录或文件），随机落到 blind-A/blind-B")
    r_material.add_argument("--blind-seed", type=int,
                            help="盲评 A/B 的分配种子（默认随机；给了就可复现）")
    r_material.add_argument("--json", action="store_true", help="输出机读 JSON")
    r_material.add_argument("--quiet", action="store_true", help="不打印报告正文")
    r_material.set_defaults(func=cmd_review)

    r_status = review_sub.add_parser("status", help="查看各技能的评审记录与新鲜度")
    r_status.add_argument("--out", help="落盘路径")
    r_status.add_argument("--quiet", action="store_true", help="不打印正文")
    _add_discovery_options(r_status)
    r_status.set_defaults(func=cmd_review)

    r_skill = review_sub.add_parser("skill", help="生成「语义评审」独立技能包")
    r_skill.add_argument("--out", metavar="目录", help="输出目录（默认为当前目录）")
    r_skill.add_argument("--name", default="skillverify-review", help="技能名（默认 skillverify-review）")
    r_skill.set_defaults(func=cmd_review)

    p_review.set_defaults(func=cmd_review, review_action=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
