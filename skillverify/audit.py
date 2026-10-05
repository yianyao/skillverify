"""audit —— 外来技能审计（供应链的个人子集）。

**场景**：技能是从网上/别人那里拿来的，用之前想知道"它是什么、能干什么、跟上次比变了没有"。
`spec`/`lint`/`evals` 技术上都能指向任意目录，但它们是**分阶段的技术报告**，
不是"要不要用它"这个决定所需要的那张单子。审计把已有结论组合成一张单子，另加三件
只有"外来技能"才需要的东西：**来源可追溯**、**内容指纹（下次比对）**、**名字近似提示**。

**明确不做**（写清楚，免得被当成"审计过了就安全"）：
- 不做**行为审计**：不跑它的脚本、不模拟它的触发、不判断它是否真的会做坏事；
- 不做**信任分级**：机械层判定不了"信任"。审计单里留一栏给人填（来源与信任级别），
  工具只保证"同一份内容"与"内容变了"这两件事可被机械地认出来；
- 不做**依赖链哈希自校验**：技能间依赖的完整性交给 git；这里只对**技能内容**取指纹。

判定口径与其它阶段一致：`FAIL` 阻断（例如发现脚本里有硬编码密钥，沿用 lint 的结论）、
`WARN` 需人工甄别（名字近似、内容与上次不同）、`INFO` 不适用（无 git、无脚本等）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .encoding import read_json, write_text
from .lint import lint_skill, load_context
from .lint import deps, scripts, security
from .lint.shared import LintContext
from .report import FAIL, INFO, PASS, SKIP, WARN, Report, Result, Rule
from .spec import check_spec
from .watch import fingerprint

#: 旧体系方案（语料已归档到仓库外，这里只作**文档级**引用，不依赖任何本地路径）
_LEGACY = "旧体系《Agent-Skill 生命周期验证方案》v1.3（供应链：安装前审计）"

#: 审计单的落点（相对 trace_dir）
AUDIT_DIR = "audit"

#: 运行台账（可选）：人工记录运行期观测，替代自动遥测
RUN_LOG_NAME = "run-log.md"
#: 台账超过这么多天没更新就给个提醒（不是错误：技能可能就是不常用）
RUN_LOG_STALE_DAYS = 30


RULES: dict[str, Rule] = {
    "AUDIT-001": Rule(
        "AUDIT-001",
        "已记录技能内容指纹（下次可比对）",
        "HOUSE",
        _LEGACY,
        "审计记录里带内容指纹，才能回答「这与上次审计的是同一份吗」",
    ),
    "AUDIT-002": Rule(
        "AUDIT-002",
        "与上次审计相比内容一致",
        "HOUSE",
        _LEGACY,
        "内容变了就要重看一遍：别人可以在你审计之后替换技能内容",
    ),
    "AUDIT-003": Rule(
        "AUDIT-003",
        "技能名与库内其它技能不构成近似（防混淆/仿冒）",
        "HOUSE",
        _LEGACY,
        "名字近似会让 Agent 或人选错技能。确认是同一个技能的不同版本，就删掉多余的那份",
    ),
    "AUDIT-004": Rule(
        "AUDIT-004",
        "来源可追溯（git 远端与提交）",
        "HOUSE",
        _LEGACY,
        "外来技能最好记下从哪来、哪一版。没有 git 信息时人工在审计单里写清来源",
    ),
    "AUDIT-005": Rule(
        "AUDIT-005",
        "能力清单：脚本 / 网络端点 / 破坏性操作 / 密钥 / 依赖",
        "HOUSE",
        _LEGACY,
        "清单来自各族的**结构化扫描**；看到不认识的网络端点或破坏性操作就要人工确认。"
        "清单为空说明这是纯文档技能（记 INFO），而不是「已审过」",
    ),
    "AUDIT-006": Rule(
        "AUDIT-006",
        f"运行台账里不许有「没处置的异常」且不许长期未更新（>{RUN_LOG_STALE_DAYS} 天）",
        "HOUSE",
        "旧体系 V9/V24 的个人版降级方案（人工 run-log.md 台账 + 每周回顾，不建自动埋点）",
        f"把异常观察的处置写清楚（接受/整改 + 依据）；长期没更新就说明原因或恢复观测。"
        f"台账模板见 examples/{RUN_LOG_NAME}，放在中央留痕目录而不是技能包里",
    ),
}

#: 名字近似的判据：编辑距离不超过这个值，或去掉分隔符后完全相同
MAX_NAME_DISTANCE = 1


def check_run_log(trace_dir: Path, skill: str | None = None) -> Result:
    """AUDIT-006：运行台账的机械部分——**异常有没有处置、台账是不是长期没更新**。

    来历：运行期观测（触发误报/漏报、脚本失败率、异常外部请求）没法自动化，旧体系的答案是
    「人工台账 + 每周回顾」。工具能做的只有一件事：**盯着这张表别变成摆设**——
    异常观察写了却没人处置、或者几周没动过，都要说出来。
    台账模板见 `examples/run-log.md`；放在中央留痕目录（不是技能包里）。
    """
    path = trace_dir / RUN_LOG_NAME
    if not path.is_file():
        return _res(RULES["AUDIT-006"], INFO,
                    f"未提供运行台账（可选）：放一份 {RUN_LOG_NAME}（模板见 examples/）"
                    f"就会检查「异常是否处置」与「是否长期未更新」")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return _res(RULES["AUDIT-006"], WARN, f"{RUN_LOG_NAME} 读不出来：{exc}")

    rows: list[tuple[int, list[str]]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 8 or not cells[0] or set(cells[0]) <= set("-: "):
            continue
        if cells[0] == "日期":
            continue
        rows.append((lineno, cells))
    if not rows:
        return _res(RULES["AUDIT-006"], WARN,
                    f"{RUN_LOG_NAME} 里没有可解析的台账行（表头见 examples/run-log.md）")

    empty_marks = ("", "—", "-", "待定", "无")
    unhandled: list[str] = []
    parsed_rows = 0
    seen_dates: list[str] = []
    for lineno, cells in rows:
        date, row_skill, _task, trigger, _script, _cost, anomaly, action = cells[:8]
        if skill and row_skill and skill not in row_skill:
            continue
        parsed_rows += 1
        seen_dates.append(date)
        if anomaly not in empty_marks and action in empty_marks:
            unhandled.append(f"{RUN_LOG_NAME}:{lineno}（异常观察没写处置）")
        if ("误触发" in trigger or "漏触发" in trigger) and action in empty_marks:
            unhandled.append(f"{RUN_LOG_NAME}:{lineno}（触发问题没写处置）")

    newest, unparsable = newest_ledger_date(seen_dates)
    stale = ""
    if newest is not None:
        from datetime import date as _date

        age = (_date.today() - newest).days
        if age > RUN_LOG_STALE_DAYS:
            stale = f"最近一条是 {newest.isoformat()}（{age} 天前）"

    if unhandled:
        return _res(RULES["AUDIT-006"], WARN, "台账里有没处置的条目：" + "；".join(unhandled[:4]))
    if stale:
        return _res(RULES["AUDIT-006"], WARN,
                    f"运行台账 {stale}：超过 {RUN_LOG_STALE_DAYS} 天没更新——"
                    f"要么技能没人用（可接受），要么观测停了（该恢复）")
    if unparsable:
        # 有台账行、但一条日期都认不出来 → 陈旧检查**未执行**：必须说出来，
        # 不能因为"没算出 stale"就当作通过（早先 strptime 抛错被吞掉，就是这个效果）。
        head = "；".join(unparsable[:3]) + ("…" if len(unparsable) > 3 else "")
        return _res(RULES["AUDIT-006"], WARN,
                    f"台账有 {parsed_rows} 条但日期都认不出来（{head}）："
                    f"陈旧检查**未执行**——请按 `YYYY-MM-DD` 写日期（模板见 examples/{RUN_LOG_NAME}）")
    return _res(RULES["AUDIT-006"], PASS, f"运行台账 {parsed_rows} 条，异常均已处置")


def newest_ledger_date(texts: list[str]):
    """返回 (最新日期, 认不出来的原始值列表)。

    **独立成函数是为了能被直接断言**：这里曾经写成"把所有日期当字符串取最大，
    再 strptime 解析"，于是 `"2026-9-5" > "2026-10-05"`（逐字符比 `9` 与 `1`），
    一条该报陈旧的台账会被静默判成新鲜；而"哪种写法更大"取决于今天是几月，
    靠集成用例很难稳定地复现——所以把这条逻辑做成纯函数，用固定输入断言。
    """
    parsed: list[tuple[object, str]] = []
    bad: list[str] = []
    for text in texts:
        day = _parse_ledger_date(text)
        if day is None:
            bad.append(text)
        else:
            parsed.append((day, text))
    if not parsed:
        return None, bad
    return max(parsed, key=lambda item: item[0])[0], bad


def _parse_ledger_date(text: str):
    """台账里的日期：接受 `YYYY-MM-DD`、`YYYY-M-D`、`YYYY/M/D`；认不出返回 None。

    **为什么不能直接拿字符串比大小**：本机实测过 `"2026-9-5" > "2026-10-05"` 为真
    （逐字符比 `9` 与 `1`），于是一条该报"30 天没更新"的台账被静默判成新鲜。
    """
    from datetime import date as _date

    cleaned = (text or "").strip().replace("/", "-")
    parts = cleaned.split("-")
    if len(parts) != 3:
        return None
    try:
        return _date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def _res(rule: Rule, status: str, evidence: str = "") -> Result:
    return Result(rid=rule.rid, title=rule.title, status=status, level=rule.level,
                  evidence=evidence,
                  remediation=rule.remediation if status in (FAIL, WARN) else "")


# --------------------------------------------------------------------------- #
# 名字近似
# --------------------------------------------------------------------------- #


def _normalized_name(name: str) -> str:
    return name.lower().replace("-", "").replace("_", "").replace(".", "")


def edit_distance(left: str, right: str) -> int:
    """Levenshtein 距离（短字符串够用；纯标准库）。"""
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, lch in enumerate(left, 1):
        current = [i]
        for j, rch in enumerate(right, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (lch != rch)))
        previous = current
    return previous[-1]


def name_lookalikes(name: str, others: list[str]) -> list[tuple[str, int]]:
    """找出与 `name` 近似的其它技能名（区分大小写/分隔符的"同名"也算）。"""
    target = _normalized_name(name)
    hits: list[tuple[str, int]] = []
    for other in others:
        if other == name:
            continue
        candidate = _normalized_name(other)
        if candidate == target:
            hits.append((other, 0))
            continue
        distance = edit_distance(target, candidate)
        if distance <= MAX_NAME_DISTANCE:
            hits.append((other, distance))
    return sorted(hits, key=lambda item: (item[1], item[0]))


# --------------------------------------------------------------------------- #
# 记录（指纹比对）
# --------------------------------------------------------------------------- #


@dataclass
class AuditRecord:
    """一次审计的留痕。"""

    skill: str
    path: str
    fingerprint: str
    verdict: str
    generated_at: str
    source: dict = field(default_factory=dict)
    capabilities: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "skill": self.skill,
            "path": self.path,
            "fingerprint": self.fingerprint,
            "verdict": self.verdict,
            "generated_at": self.generated_at,
            "source": self.source,
            "capabilities": self.capabilities,
        }


def load_previous(trace_dir: Path, skill: str) -> dict | None:
    path = trace_dir / AUDIT_DIR / f"{skill}.json"
    if not path.is_file():
        return None
    data, error = read_json(path)
    return data if isinstance(data, dict) and not error else None


def write_record(trace_dir: Path, record: AuditRecord, markdown: str) -> list[Path]:
    """写审计单：`<trace_dir>/audit/<技能名>.md`（人读）与 `.json`（机器比对）。"""
    out = trace_dir / AUDIT_DIR
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{record.skill}.json"
    md_path = out / f"{record.skill}.md"
    write_text(json_path, json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n")
    write_text(md_path, markdown if markdown.endswith("\n") else markdown + "\n")
    return [json_path, md_path]


# --------------------------------------------------------------------------- #
# 能力清单（把各阶段结论汇总成一节）
# --------------------------------------------------------------------------- #


def capabilities(ctx: LintContext | None) -> dict:
    """从各族的**结构化事实**汇总「这个技能能干什么」；`ctx is None` → 空字典。

    早先这里是 `r.evidence.split("：", 1)[-1]`——从**证据文本**里抠数据。那正是本项目在
    deliver 里批评并改掉的反模式：措辞一改就静默解析出垃圾。而且映射还错了一层：
    「网络端点」取自 `SEC-006`（URL 携带凭据参数），真正的端点扫描是 `SEC-007`。
    现在事实由各族的 `facts(ctx)` 提供，两边共用同一处扫描实现。
    """
    if ctx is None:
        return {}
    security_facts = security.facts(ctx)
    script_facts = scripts.facts(ctx)
    dep_facts = deps.facts(ctx)
    return {
        "脚本": list(script_facts.scripts),
        "网络端点": list(security_facts.endpoints),
        "破坏性/有状态操作": [f"{rp}: {'、'.join(kinds)}"
                              for rp, kinds in script_facts.destructive],
        "疑似硬编码密钥": list(security_facts.strong_secrets),
        "外部依赖": list(dep_facts.third_party) + list(dep_facts.inline),
    }


def git_source(skill_dir: Path) -> dict:
    """尽力找出来源（远端与当前提交）。找不到就空着，由人填写。"""
    import subprocess

    source: dict = {}
    try:
        inside = subprocess.run(["git", "-C", str(skill_dir), "rev-parse", "--show-toplevel"],
                                capture_output=True, text=True, timeout=10)
        if inside.returncode == 0:
            root = inside.stdout.strip()
            source["仓库"] = root
            for key, args in (("远端", ["git", "-C", root, "remote", "get-url", "origin"]),
                              ("提交", ["git", "-C", root, "rev-parse", "HEAD"])):
                proc = subprocess.run(args, capture_output=True, text=True, timeout=10)
                if proc.returncode == 0 and proc.stdout.strip():
                    source[key] = proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return source


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #


def audit_skill(skill_dir: Path, *, trace_dir: Path, others: list[str] | None = None,
                run_scripts: bool = False, now: str | None = None) -> tuple[Report, AuditRecord]:
    """审计一个技能：组合 spec + lint 结论，并补上来源/指纹/名字近似/能力清单。"""
    from datetime import datetime

    skill_dir = skill_dir.resolve()
    report = Report(target=str(skill_dir), stage="audit")
    doc, spec_report = check_spec(skill_dir)
    ctx, _lint_doc = load_context(skill_dir, run_scripts=run_scripts)
    lint_report = lint_skill(skill_dir, run_scripts=run_scripts)
    for res in spec_report.results:
        report.add(res)
    for res in lint_report.results:
        report.add(res)

    name = doc.name or skill_dir.name
    digest = fingerprint(skill_dir)
    report.add(_res(RULES["AUDIT-001"], PASS, f"{name} 内容指纹 {digest[:16]}（完整值见记录）"))
    # 运行台账的机械部分：异常有没有处置、台账是不是长期没更新（AUDIT-006）
    report.add(check_run_log(trace_dir, name))

    previous = load_previous(trace_dir, name)
    if previous is None:
        report.add(_res(RULES["AUDIT-002"], INFO, "这是第一次审计该技能，没有可比的上一份"))
    elif previous.get("fingerprint") == digest:
        report.add(_res(RULES["AUDIT-002"], PASS,
                        f"与上次审计（{previous.get('generated_at', '?')}）内容一致"))
    else:
        report.add(_res(RULES["AUDIT-002"], WARN,
                        f"内容与上次审计（{previous.get('generated_at', '?')}）**不同**："
                        f"{str(previous.get('fingerprint'))[:16]} → {digest[:16]}；"
                        f"别人可以在你审计之后替换内容，请重新过一遍"))

    lookalikes = name_lookalikes(name, list(others or []))
    if lookalikes:
        detail = "、".join(f"{other}（距离 {distance}）" for other, distance in lookalikes[:5])
        report.add(_res(RULES["AUDIT-003"], WARN, f"与库内技能名近似：{detail}"))
    elif others:
        report.add(_res(RULES["AUDIT-003"], PASS, f"与库内 {len(others)} 个技能名无近似"))
    else:
        report.add(_res(RULES["AUDIT-003"], INFO, "库内没有其它技能可比对名字"))

    source = git_source(skill_dir)
    if source.get("远端") or source.get("提交"):
        report.add(_res(RULES["AUDIT-004"], PASS,
                        "来源：" + "；".join(f"{k}={v}" for k, v in source.items())))
    else:
        report.add(_res(RULES["AUDIT-004"], INFO,
                        "未找到 git 来源信息（外来技能常见）；请在审计单里人工写明来源"))

    caps = capabilities(ctx)
    summary = "；".join(f"{key} {len(value)} 项" + (f"（{', '.join(value[:3])}）" if value else "")
                        for key, value in caps.items())
    if ctx is None:
        # 前置检查失败 → 能力清单**没生成**：记 SKIP（覆盖有洞），不许假装拿到了事实
        report.add(_res(RULES["AUDIT-005"], SKIP,
                        "未执行：lint 前置检查失败（先修好 spec 阶段的问题）"))
    elif any(caps.values()):
        report.add(_res(RULES["AUDIT-005"], PASS, summary))
    else:
        # 全空是**有意义**的结论（纯文档技能），但不该记 PASS——"清单已生成"是恒真的，
        # 恒真的判定等于没判定（本项目的老教训）。
        report.add(_res(RULES["AUDIT-005"], INFO,
                        "不适用：纯文档技能，没有脚本/网络端点/破坏性操作/依赖可列"))

    stamp = now or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    record = AuditRecord(skill=name, path=str(skill_dir), fingerprint=digest,
                         verdict=report.verdict(), generated_at=stamp,
                         source=source, capabilities=caps)
    return report, record


def audit_markdown(record: AuditRecord, report: Report, lookalikes_note: str = "") -> str:
    """生成审计单（人读）。含一栏留给人填的"来源与信任级别"。"""
    lines = [
        f"# 审计单：{record.skill}",
        "",
        f"- 路径：`{record.path}`",
        f"- 时间：{record.generated_at}",
        f"- 结论：**{record.verdict}**（{report.counts()}）",
        f"- 内容指纹：`{record.fingerprint}`",
        f"- 来源（自动）：{record.source or '未自动获取到'}",
        "",
        "> 这张单子是**机械结论的汇总**，不是安全背书：本工具不跑技能脚本、不模拟触发，",
        "> 也不判断技能的真实行为。它只保证「这是同一份内容」与「内容变了」可被认出来。",
        "",
        "## 来源与信任级别（人工填写）",
        "",
        "- 从哪来：",
        "- 信任级别（自研 / 已读过的第三方 / 未读过的第三方）：",
        "- 复核人 / 日期：",
        "",
        "## 能力清单（自动汇总）",
        "",
    ]
    for key, value in record.capabilities.items():
        lines.append(f"- **{key}**（{len(value)}）：" + ("、".join(f"`{v}`" for v in value[:8])
                                                       if value else "无"))
    lines += [
        "",
        "> 各类的**口径**（避免误读）：网络端点 = **代码文件**里出现、且未在 frontmatter 声明的主机；",
        "> 破坏性/有状态操作 = 脚本里的删除/覆盖/移动等形态（含是否声明防护旗标）；",
        "> 疑似密钥 = 高置信度特征命中（如私钥头、云厂商密钥前缀）；",
        "> 外部依赖 = Python 脚本导入的第三方模块。它们都来自**结构化扫描**，不是从报告文字里猜的。",
    ]
    lines += ["", "## 判定明细", "", "| 规则 | 判级 | 证据 |", "|---|---|---|"]
    for res in report.sorted_results():
        if res.status == INFO:
            continue
        lines.append(f"| `{res.rid}` {res.title} | {res.status} | {res.evidence[:160]} |")
    if lookalikes_note:
        lines += ["", lookalikes_note]
    return "\n".join(lines)


__all__ = ["AUDIT_DIR", "MAX_NAME_DISTANCE", "RULES", "AuditRecord", "audit_markdown",
           "audit_skill", "capabilities", "edit_distance", "git_source", "load_previous",
           "name_lookalikes", "write_record"]
