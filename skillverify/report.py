"""report —— 统一结果模型与输出渲染。

设计要点：
1. **一条规则对应一条结果**，结果里必须带"来源"（官方条款 / 项目收紧），
   否则无法区分"官方要求"与"我们的额外纪律"——这是旧体系最容易失真的地方。
2. 判定只有五种：PASS / WARN / FAIL / SKIP / INFO。
   - FAIL 阻断；WARN 需人工书面甄别；
   - SKIP = **本项未执行**（覆盖有洞，须说明原因），一律计入退出码 2——
     "没检查"不允许看起来像"通过"；
   - INFO = **不适用**或纯记录，无合规含义，不影响退出码。把"不适用"记 INFO
     而不是 SKIP，退出码才保得住信号量（否则每个纯文档技能都会因一堆"不适用"
     恒返回 2，最终没人再看退出码）。
3. 退出码统一：0=全 PASS（含 INFO）、1=有 FAIL、2=无 FAIL 但有 WARN/SKIP。
4. 人读 Markdown 与机读 JSON 同源，避免两套口径漂移。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Iterable

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
SKIP = "SKIP"
INFO = "INFO"

#: 结果严重度顺序（用于稳定排序）
_ORDER = {FAIL: 0, WARN: 1, SKIP: 2, INFO: 3, PASS: 4}

#: 规则强度分级——不得把项目收紧伪装成官方要求
MUST = "MUST"  # 官方硬约束（官方校验器会报错）
SHOULD = "SHOULD"  # 官方建议/指导（官方工具不执法）
HOUSE = "HOUSE"  # 本项目收紧的额外纪律


@dataclass
class Rule:
    """规则元数据。"""

    rid: str
    title: str
    level: str  # MUST / SHOULD / HOUSE
    source: str  # 出处（官方 URL 或官方校验器行为）
    remediation: str = ""  # 修复指引


@dataclass
class Result:
    """单条规则的判定结果。"""

    rid: str
    title: str
    status: str
    level: str
    evidence: str = ""
    remediation: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class Report:
    """一次检查的完整报告。"""

    target: str
    stage: str
    results: list[Result] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)

    def add(self, result: Result) -> None:
        self.results.append(result)

    def add_rule(self, rule: Rule, status: str, evidence: str = "") -> None:
        self.results.append(
            Result(
                rid=rule.rid,
                title=rule.title,
                status=status,
                level=rule.level,
                evidence=evidence,
                remediation=rule.remediation if status in (FAIL, WARN) else "",
            )
        )

    # ---- 汇总 ----

    def counts(self) -> dict[str, int]:
        out = {PASS: 0, WARN: 0, FAIL: 0, SKIP: 0, INFO: 0}
        for res in self.results:
            out[res.status] = out.get(res.status, 0) + 1
        return out

    def exit_code(self) -> int:
        c = self.counts()
        if c[FAIL]:
            return 1
        if c[WARN] or c[SKIP]:
            return 2
        return 0

    def verdict(self) -> str:
        code = self.exit_code()
        if code == 0:
            return "PASS"
        if code == 1:
            return "FAIL"
        return "WARN"

    def sorted_results(self) -> list[Result]:
        return sorted(self.results, key=lambda r: (_ORDER.get(r.status, 9), r.rid))

    # ---- 渲染 ----

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "stage": self.stage,
            "verdict": self.verdict(),
            "exit_code": self.exit_code(),
            "counts": self.counts(),
            "meta": self.meta,
            "results": [r.to_dict() for r in self.sorted_results()],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        c = self.counts()
        lines = [
            f"# skillverify 报告 · {self.stage} 阶段",
            "",
            f"- 对象: {self.target}",
        ]
        for key, value in self.meta.items():
            lines.append(f"- {key}: {value}")
        lines += [
            f"- 总结论: **{self.verdict()}**"
            f"（PASS={c[PASS]} WARN={c[WARN]} FAIL={c[FAIL]} SKIP={c[SKIP]} INFO={c[INFO]}）",
            "",
            "| 规则 | 级别 | 判定 | 说明 | 证据 / 修复 |",
            "|---|---|---|---|---|",
        ]
        for res in self.sorted_results():
            detail = res.evidence or ""
            if res.remediation:
                detail = f"{detail} → 修复: {res.remediation}" if detail else f"修复: {res.remediation}"
            detail = detail.replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {res.rid} | {res.level} | {res.status} | {res.title} | {detail} |"
            )
        lines += [
            "",
            "> 级别含义：MUST=官方硬约束（官方校验器会报错）；"
            "SHOULD=官方建议（官方工具不执法）；HOUSE=本项目额外收紧。",
            "> 判定含义：SKIP=本项**未执行**（覆盖有洞）；INFO=**不适用**或纯记录。"
            "两者都不代表已通过。",
            "> 退出码：0=全 PASS（含 INFO），1=有 FAIL，2=无 FAIL 但有 WARN/SKIP。",
            "",
        ]
        return "\n".join(lines)


def merge(reports: Iterable[Report], target: str, stage: str) -> Report:
    """把多个报告合并成一个（用于多模块汇总）。"""
    out = Report(target=target, stage=stage)
    for rep in reports:
        out.results.extend(rep.results)
        out.meta.update(rep.meta)
    return out


# --------------------------------------------------------------------------- #
# 库级报告（`skillverify check`：一批技能 + 库级结论）
# --------------------------------------------------------------------------- #


@dataclass
class LibraryEntry:
    """库里的一个技能及其报告。"""

    skill: str
    scope: str  # project / user / explicit
    path: str
    report: Report

    def counts(self) -> dict[str, int]:
        return self.report.counts()

    def to_dict(self) -> dict:
        return {
            "skill": self.skill,
            "scope": self.scope,
            "path": self.path,
            "verdict": self.report.verdict(),
            "exit_code": self.report.exit_code(),
            "counts": self.counts(),
            "results": [r.to_dict() for r in self.report.sorted_results()],
        }


@dataclass
class LibraryReport:
    """一批技能的汇总报告。

    为什么单独一个类而不是 `merge()` 一个 Report：库级问题的**归属不同**——
    库级结果（如"同名技能出现在多个根"）不属于任何单个技能，混进某个技能的
    结果列表会让"这个技能哪里有问题"读不出来。
    """

    stage: str
    target: str
    entries: list[LibraryEntry] = field(default_factory=list)
    results: list[Result] = field(default_factory=list)  # 库级结果（DISC-* 等）
    meta: dict[str, str] = field(default_factory=dict)

    def add_entry(self, entry: LibraryEntry) -> None:
        self.entries.append(entry)

    def add(self, result: Result) -> None:
        self.results.append(result)

    def all_results(self) -> list[Result]:
        out = list(self.results)
        for entry in self.entries:
            out.extend(entry.report.results)
        return out

    def counts(self) -> dict[str, int]:
        out = {PASS: 0, WARN: 0, FAIL: 0, SKIP: 0, INFO: 0}
        for res in self.all_results():
            out[res.status] = out.get(res.status, 0) + 1
        return out

    def skill_verdicts(self) -> dict[str, int]:
        out = {PASS: 0, WARN: 0, FAIL: 0}
        for entry in self.entries:
            out[entry.report.verdict()] = out.get(entry.report.verdict(), 0) + 1
        return out

    def exit_code(self) -> int:
        c = self.counts()
        if c[FAIL]:
            return 1
        if c[WARN] or c[SKIP]:
            return 2
        return 0

    def verdict(self) -> str:
        code = self.exit_code()
        return "PASS" if code == 0 else ("FAIL" if code == 1 else "WARN")

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "stage": self.stage,
            "verdict": self.verdict(),
            "exit_code": self.exit_code(),
            "counts": self.counts(),
            "skill_verdicts": self.skill_verdicts(),
            "meta": self.meta,
            "library_results": [r.to_dict() for r in self.results],
            "skills": [e.to_dict() for e in self.entries],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        c = self.counts()
        sv = self.skill_verdicts()
        lines = [
            f"# skillverify 报告 · {self.stage} 阶段（整库）",
            "",
            f"- 对象: {self.target}",
        ]
        for key, value in self.meta.items():
            lines.append(f"- {key}: {value}")
        lines += [
            f"- 技能数: {len(self.entries)}"
            f"（PASS={sv[PASS]} WARN={sv[WARN]} FAIL={sv[FAIL]}）",
            f"- 总结论: **{self.verdict()}**"
            f"（全部结果 PASS={c[PASS]} WARN={c[WARN]} FAIL={c[FAIL]} "
            f"SKIP={c[SKIP]} INFO={c[INFO]}）",
            "",
            "## 技能清单",
            "",
            "| 技能 | 作用域 | 路径 | 判定 | PASS | WARN | FAIL | SKIP | INFO |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for entry in sorted(self.entries, key=lambda e: (e.skill, e.path)):
            k = entry.counts()
            lines.append(
                f"| {entry.skill} | {entry.scope} | {entry.path} | {entry.report.verdict()} "
                f"| {k[PASS]} | {k[WARN]} | {k[FAIL]} | {k[SKIP]} | {k[INFO]} |"
            )

        if self.results:
            lines += ["", "## 库级结果", "", "| 规则 | 级别 | 判定 | 说明 | 证据 / 修复 |", "|---|---|---|---|---|"]
            for res in sorted(self.results, key=lambda r: (_ORDER.get(r.status, 9), r.rid)):
                detail = res.evidence or ""
                if res.remediation:
                    detail = f"{detail} → 修复: {res.remediation}" if detail else f"修复: {res.remediation}"
                lines.append(
                    f"| {res.rid} | {res.level} | {res.status} | {res.title} "
                    f"| {detail.replace('|', chr(92) + '|').replace(chr(10), ' ')} |"
                )

        notable = [
            (entry, res)
            for entry in self.entries
            for res in entry.report.sorted_results()
            if res.status in (FAIL, WARN, SKIP)
        ]
        lines += ["", "## 需关注的判定（FAIL / WARN / SKIP）", ""]
        if not notable:
            lines.append("无：所有技能的每条规则均为 PASS 或「不适用」(INFO)。")
        else:
            lines += [
                "| 技能 | 规则 | 级别 | 判定 | 说明 | 证据 / 修复 |",
                "|---|---|---|---|---|---|",
            ]
            for entry, res in notable:
                detail = res.evidence or ""
                if res.remediation:
                    detail = f"{detail} → 修复: {res.remediation}" if detail else f"修复: {res.remediation}"
                detail = detail.replace("|", chr(92) + "|").replace("\n", " ")
                lines.append(
                    f"| {entry.skill} | {res.rid} | {res.level} | {res.status} "
                    f"| {res.title} | {detail} |"
                )
            lines.append("")
            lines.append(
                "> 只看 FAIL/WARN/SKIP 是为了让大库的报告仍可读；某个技能的完整逐条判定请对该技能单独跑 "
                "`skillverify spec` / `skillverify lint`。"
            )

        lines += [
            "",
            "> 级别含义：MUST=官方硬约束（官方校验器会报错）；"
            "SHOULD=官方建议（官方工具不执法）；HOUSE=本项目额外收紧。",
            "> 判定含义：SKIP=本项**未执行**（覆盖有洞）；INFO=**不适用**或纯记录。"
            "两者都不代表已通过。",
            "> 退出码：0=全 PASS（含 INFO），1=有 FAIL，2=无 FAIL 但有 WARN/SKIP。",
            "",
        ]
        return "\n".join(lines)
