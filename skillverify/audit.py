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
from .lint import lint_skill
from .report import FAIL, INFO, PASS, WARN, Report, Result, Rule
from .spec import check_spec
from .watch import fingerprint

_LEGACY = "legacy/Agent-Skill-生命周期验证方案.md（供应链：安装前审计）"

#: 审计单的落点（相对 trace_dir）
AUDIT_DIR = "audit"

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
        "能力清单已生成（脚本/网络/破坏性/密钥/依赖）",
        "HOUSE",
        _LEGACY,
        "审计单里的能力清单来自各阶段结论；看到不认识的网络端点或破坏性操作就要人工确认",
    ),
}

#: 名字近似的判据：编辑距离不超过这个值，或去掉分隔符后完全相同
MAX_NAME_DISTANCE = 1


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


def capabilities(skill_dir: Path, report: Report) -> dict:
    """从已有阶段结论里汇总"这个技能能干什么"。"""
    scripts = sorted(p.name for p in (skill_dir / "scripts").rglob("*")
                     if p.is_file()) if (skill_dir / "scripts").is_dir() else []
    network = sorted({r.evidence.split("：", 1)[-1].split()[0]
                      for r in report.results if r.rid == "SEC-006" and r.status == FAIL})
    destructive = sorted({r.evidence.split("：", 1)[-1].strip()[:60]
                          for r in report.results
                          if r.rid == "SCRIPT-005" and r.status == WARN})
    secrets = sorted({r.evidence.split("：", 1)[-1].strip()[:60]
                      for r in report.results if r.rid == "SEC-001" and r.status == FAIL})
    deps = sorted({r.evidence.split("：", 1)[-1].strip()[:60]
                   for r in report.results if r.rid == "DEP-002" and r.status == FAIL})
    return {
        "脚本": scripts,
        "网络端点": network,
        "破坏性/有状态操作": destructive,
        "疑似硬编码密钥": secrets,
        "外部依赖": deps,
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
    lint_report = lint_skill(skill_dir, run_scripts=run_scripts)
    for res in spec_report.results:
        report.add(res)
    for res in lint_report.results:
        report.add(res)

    name = doc.name or skill_dir.name
    digest = fingerprint(skill_dir)
    report.add(_res(RULES["AUDIT-001"], PASS, f"{name} 内容指纹 {digest[:16]}（完整值见记录）"))

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

    caps = capabilities(skill_dir, report)
    summary = "；".join(f"{key} {len(value)} 项" + (f"（{', '.join(value[:3])}）" if value else "")
                        for key, value in caps.items())
    report.add(_res(RULES["AUDIT-005"], PASS if name else INFO, summary))

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
