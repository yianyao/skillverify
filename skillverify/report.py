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
