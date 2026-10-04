"""lint —— 官方校验器留白的补检（机械层，全部离线、纯标准库）。

**为什么需要这一层**：官方 `agentskills validate` 只查 frontmatter 的 6 个字段与
命名约定（见 spec 模块）。正文内容、行数/token、引用存在性与深度、目录卫生、
脚本契约、依赖声明、编码换行、密钥与危险操作——**官方全部不查**。这一层就是补这些洞。

**判定口径（贯穿本包，务必与 spec 阶段一致）**
- FAIL：客观缺陷，阻断。例：正文指向的引用断链、真实密钥特征、shell 脚本 CRLF。
- WARN：需人工书面甄别的信号，不阻断。例：熵命中、破坏性操作缺防护旗标、未钉版本。
- SKIP：**本项未执行**（覆盖有洞）。一律计入退出码 2——"没检查"绝不允许看起来像"通过"。
  例：有脚本但未开 `--scripts`、文件读不出来。
- INFO：**不适用**，无合规含义，不影响退出码。例：包内没有 scripts/ 目录。
  把"不适用"记 INFO 而不是 SKIP，是为了让退出码保持信号量：
  否则每个纯文档技能都会因一堆"不适用"而恒返回 2，最终没人再看退出码。
- PASS：本项已执行且通过。

**规则强度分级**（`Rule.level`）不得混淆：MUST=官方硬约束（官方校验器会报错）；
SHOULD=官方建议/指导（官方工具不执法）；HOUSE=本项目额外收紧。
"""

from __future__ import annotations

from pathlib import Path

from ..encoding import read_text
from ..report import SKIP, Report, Result, Rule
from ..spec import SkillDocument, load_skill
from . import budget, deps, hygiene, refs, scripts, security
from .inventory import build_inventory
from .shared import LintContext, res

#: 检查族（顺序 = 报告中的族顺序；每族各自拥有不重叠的规则 id 前缀）
_FAMILIES = (refs, budget, hygiene, scripts, deps, security)

#: 前置规则：这些失败时后续检查无从谈起（SKILL.md 缺失/frontmatter 不可解析）
PRECONDITION_RULES = ("SKILL-001", "SKILL-002", "SKILL-003")

#: 合并后的规则总表（导入期即校验 id 唯一，冲突立刻炸掉而不是静默覆盖）
RULES: dict[str, Rule] = {}
for _module in _FAMILIES:
    for _rid, _rule in _module.RULES.items():
        if _rid in RULES:
            raise RuntimeError(f"lint 规则 id 冲突: {_rid}")
        RULES[_rid] = _rule
del _module, _rid, _rule


def _context_from(
    doc: SkillDocument,
    path: Path,
    *,
    run_scripts: bool,
    script_timeout_s: float,
    script_budget_s: float,
) -> LintContext:
    """从已解析的技能文档构造 lint 上下文（前置检查已通过）。"""
    assert doc.skill_md is not None  # 前置通过则必然有 SKILL.md
    text = read_text(doc.skill_md)
    # 内部一律用**绝对路径**：脚本实测的 cwd 是技能根目录，若这里存相对路径，
    # 子进程会把"相对技能根目录的脚本路径"再拼一次 cwd，导致 --help 报"找不到文件"。
    # 报告里的 target 仍保留调用方传入的原样写法（人读友好）。
    root = path.resolve()
    inventory = build_inventory(root)
    return LintContext(
        root=root,
        doc=doc,
        skill_md_rel=doc.skill_md.relative_to(path).as_posix(),
        text=text,
        body=doc.body or "",
        inventory=inventory,
        run_scripts=run_scripts,
        script_timeout_s=script_timeout_s,
        script_budget_s=script_budget_s,
    )


def load_context(
    path: Path,
    *,
    run_scripts: bool = False,
    script_timeout_s: float = 10.0,
    script_budget_s: float = 120.0,
) -> tuple[LintContext | None, SkillDocument]:
    """构造 lint 上下文，返回 `(ctx, doc)`；前置检查失败时 `ctx is None`。

    **为什么暴露它**：`audit` 要的是"事实"（有哪些端点/依赖/破坏性操作），不是"报告"。
    早先它从**证据文本**里抠（`evidence.split("：")`）——正是本项目在 deliver 里批评并改掉的
    反模式：措辞一改就静默解析出垃圾。现在事实由各族的 `facts(ctx)` 提供，两边共用同一处扫描。

    `ctx is None` 时调用方必须记 SKIP（未执行），不许假装拿到了事实。
    """
    doc = load_skill(path)
    if any(e.status == "FAIL" and e.rid in PRECONDITION_RULES for e in doc.errors):
        return None, doc
    return _context_from(doc, path, run_scripts=run_scripts,
                         script_timeout_s=script_timeout_s,
                         script_budget_s=script_budget_s), doc


def lint_skill(
    path: Path,
    *,
    run_scripts: bool = False,
    script_timeout_s: float = 10.0,
    script_budget_s: float = 120.0,
) -> Report:
    """对单个技能目录执行 lint，返回报告（不抛异常）。"""
    report = Report(target=str(path), stage="lint")
    doc = load_skill(path)

    if any(e.status == "FAIL" and e.rid in PRECONDITION_RULES for e in doc.errors):
        reason = next(
            (e.evidence for e in doc.errors if e.rid in PRECONDITION_RULES), "前置检查失败"
        )
        for rule in RULES.values():
            report.add(res(rule, SKIP, f"未执行：{reason}（先修好 spec 阶段的问题）"))
        report.meta["前置检查"] = "失败"
        return report

    ctx = _context_from(doc, path, run_scripts=run_scripts,
                        script_timeout_s=script_timeout_s, script_budget_s=script_budget_s)

    produced: dict[str, Result] = {}
    for module in _FAMILIES:
        for result in module.check(ctx):
            produced.setdefault(result.rid, result)

    for result in produced.values():
        report.add(result)

    # 未产生记录的规则 = 实现遗漏：必须显式暴露，绝不静默 PASS
    missing = [rid for rid in RULES if rid not in produced]
    for rid in missing:
        report.add(res(RULES[rid], SKIP, "实现遗漏：本规则未产生记录（请报 bug）"))

    report.meta["工具版本"] = "skillverify"
    report.meta["规则数"] = str(len(RULES))
    report.meta["扫描文件"] = (
        f"{len(ctx.inventory.files)} 个（二进制 {len(ctx.inventory.binaries)}，"
        f"符号链接未跟随 {len(ctx.inventory.symlinks)}，"
        f"读取失败 {len(ctx.inventory.read_errors)}）"
    )
    report.meta["脚本契约实测"] = (
        f"已执行（{len([r for r in ctx.inventory.files if r.under('scripts')])} 个脚本）"
        if run_scripts
        else "未执行（默认不执行脚本；加 --scripts 开启）"
    )
    return report
