"""material —— 为"评的不是技能文件本身"的提示词产出材料。

**为什么需要它**：30 条提示词里有几条评的是**流程产物或技能集合**而不是单个技能文件——
`E-02`（description 修订前后 diff）、`E-03`（本轮修订方向与依据）、
`E-06`（盲评两版产物）、`E-07`/`E-08`（工作区里的 grading/timing/benchmark 数字）、
`W-11`（相邻技能边界）。这些材料不产出，那几条会永远停在 NA，
而 NA 与"材料没准备"在报告里长得一样。

于是这里做五件事（能算的算、能摘的摘、算不出来的**明说缺什么**）：

| 材料 | 服务的提示词 | 来源 |
|---|---|---|
| `description-diff.md` | E-02 | `git diff <base> -- SKILL.md` |
| `revision-signals.md` | E-03 | 工作区的失败断言 + 人工反馈 + benchmark delta |
| `blind/` | E-06 | 你给的两版产物，随机落到 A/B，映射封存在 `blind/mapping.json` |
| `workspace-digest.md` | E-07、E-08 | 工作区各 iteration 的逐次产物与聚合值 |
| `adjacency.md` | W-11 | 同级技能目录的描述词面重叠（`library` 的同一套词元/重叠口径） |

**判定纪律**：
- 材料生成失败**不是**"不适用"：该记 SKIP 并说明原因（缺 workspace、非 git 仓库、没给两版产物、
  同级目录列不出来），这样"没准备"与"准备好了"在报告里能区分开；
- 但"**同级根本没有别的技能**"是真的不适用 → 记 INFO（没有可比的邻居，不是覆盖洞）；
- 盲评的 A/B 分配**默认随机**（`--blind-seed` 可复现），映射写进单独文件——
  评审者不看映射就能给出结论，这是盲评成立的前提。
"""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
from pathlib import Path

from . import __version__
from .encoding import read_json, write_text
from .library import MIN_TOKENS, overlap as token_overlap, tokens as lib_tokens
from .report import FAIL, INFO, PASS, SKIP, WARN, Result, Rule
from .spec import find_skill_md, load_skill

#: 材料清单的格式版本
MATERIAL_SCHEMA = "skillverify.review-material/1"

RULES: dict[str, Rule] = {
    "MAT-001": Rule(
        "MAT-001",
        "description 修订前后 diff（E-02 的材料）",
        "HOUSE",
        "本项目流程约定：E-02 判断修订是否走偏，缺 diff 就无法判断",
        "在 git 仓库里跑，或用 `--diff-base <引用>` 指定基线；否则手工附两版 description",
    ),
    "MAT-002": Rule(
        "MAT-002",
        "修订信号汇总（E-03 的材料）",
        "HOUSE",
        "E-03 要的是「本轮该往哪改」，依据是失败断言 + 人工反馈 + 性能 delta",
        "先跑一轮评测产生 workspace，或手工把三条信号写进材料目录",
    ),
    "MAT-003": Rule(
        "MAT-003",
        "盲评材料（E-06 的材料）",
        "HOUSE",
        "盲评要求评审者不知道哪版是新的",
        "用 `--blind <旧版目录> <新版目录>` 提供两版产物",
    ),
    "MAT-004": Rule(
        "MAT-004",
        "工作区数字汇总（E-07/E-08 的材料）",
        "HOUSE",
        "模式归因与 delta 解读要看的是一屏数字，不是满目录 JSON",
        "先跑官方评测流程产生 `<技能名>-workspace/iteration-N/`，再用 `--workspace` 指定",
    ),
    "MAT-005": Rule(
        "MAT-005",
        "相邻技能边界清单（W-11 的材料）",
        "HOUSE",
        "旧体系《人工评审检查清单》D-3「相邻技能边界清单已列」（〔纯 H〕）——"
        "本项目把能机械算的那一半（描述词面重叠）产出成材料，裁决仍归人",
        "把同类技能放在**同一层**目录下（`<root>/<技能名>/`），或手工附一份相邻技能清单"
        "（分类嵌套布局只在同级找会漏）",
    ),
}

#: 提示词 id → 它需要的材料文件（供 `review pack` 与文档引用）
MATERIAL_FOR_PROMPT: dict[str, str] = {
    "E-02": "description-diff.md",
    "E-03": "revision-signals.md",
    "E-06": "blind/",
    "E-07": "workspace-digest.md",
    "E-08": "workspace-digest.md",
    "W-11": "adjacency.md",
}


def _res(rule: Rule, status: str, evidence: str = "") -> Result:
    return Result(rid=rule.rid, title=rule.title, status=status, level=rule.level,
                  evidence=evidence,
                  remediation=rule.remediation if status in (FAIL, WARN) else "")


def _header(serves: str, source: str) -> str:
    return (
        f"<!-- 材料文件；服务于语义评审提示词：{serves} -->\n"
        f"# 材料：{serves}\n\n"
        f"- 来源：{source}\n"
        f"- 生成工具：skillverify {__version__}（`review material`）\n"
        f"- 用法：连同技能目录一起交给评审者；本文件只提供事实，不含结论。\n\n"
        "---\n\n"
    )


# --------------------------------------------------------------------------- #
# 各项材料
# --------------------------------------------------------------------------- #


def _git(project: Path, args: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(["git", "-C", str(project), *args], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return proc.returncode, (proc.stdout or "").strip()


def build_description_diff(skill_dir: Path, out: Path, diff_base: str | None) -> Result:
    """E-02：description 的修订前后 diff。"""
    skill_md = skill_dir / "SKILL.md"
    base = diff_base or "HEAD"
    code, _out = _git(skill_dir, ["rev-parse", "--is-inside-work-tree"])
    if code != 0:
        return _res(RULES["MAT-001"], SKIP,
                    f"未生成：{skill_dir} 不是 git 仓库（无法取 diff）；"
                    f"请手工把修订前后两版 description 贴进材料")
    code, diff = _git(skill_dir, ["diff", base, "--", "SKILL.md"])
    if code != 0:
        return _res(RULES["MAT-001"], SKIP,
                    f"未生成：`git diff {base} -- SKILL.md` 失败（基线引用是否存在？）")
    if not diff.strip():
        # 没有 diff 本身就是一条事实：工作树与基线一致
        return _res(RULES["MAT-001"], SKIP,
                    f"未生成：与 {base} 相比 SKILL.md 没有改动"
                    f"（若修订已提交，请用 `--diff-base <上次提交>`）")
    write_text(out, _header("E-02", f"git diff {base} -- SKILL.md") + "```diff\n" + diff + "\n```\n")
    return _res(RULES["MAT-001"], PASS,
                f"已生成 {out.name}（与 {base} 的 diff，{len(diff.splitlines())} 行）")


def _iterations(workspace: Path) -> list[Path]:
    if not workspace.is_dir():
        return []
    found = [p for p in sorted(workspace.iterdir())
             if p.is_dir() and re.match(r"^iteration-\d+$", p.name)]
    return sorted(found, key=lambda p: int(p.name.split("-")[1]))


def _read_json(path: Path) -> object | None:
    data, _error = read_json(path)
    return data


def build_workspace_digest(skill_dir: Path, out: Path, workspace: Path | None) -> Result:
    """E-07/E-08：把工作区里满目录的 JSON 摘成一屏数字。"""
    ws = workspace or (skill_dir.parent / f"{skill_dir.name}-workspace")
    iterations = _iterations(ws)
    lines = ["## 逐轮聚合（benchmark.json）", "",
             "| 轮次 | 配置 | pass_rate mean±sd | time_seconds mean±sd | tokens mean±sd |",
             "|---|---|---|---|---|"]
    detail: list[str] = ["## 逐次产物（grading.json / timing.json）", ""]
    runs = 0
    for it in iterations:
        bench = _read_json(it / "benchmark.json")
        summary = (bench or {}).get("run_summary", {}) if isinstance(bench, dict) else {}
        if isinstance(summary, dict):
            for arm in ("with_skill", "without_skill", "old_skill"):
                block = summary.get(arm)
                if not isinstance(block, dict):
                    continue

                def stat(metric: str) -> str:
                    value = block.get(metric)
                    if not isinstance(value, dict):
                        return "-"
                    mean, sd = value.get("mean"), value.get("stddev")
                    if mean is None:
                        return "-"
                    return f"{mean}±{sd}" if sd is not None else f"{mean}"

                lines.append(f"| {it.name} | {arm} | {stat('pass_rate')} "
                             f"| {stat('time_seconds')} | {stat('tokens')} |")
            delta = summary.get("delta")
            if isinstance(delta, dict) and delta:
                lines.append(f"| {it.name} | delta | {delta.get('pass_rate', '-')} "
                             f"| {delta.get('time_seconds', '-')} | {delta.get('tokens', '-')} |")
        for eval_dir in sorted(p for p in it.iterdir() if p.is_dir() and p.name.startswith("eval-")):
            for arm in ("with_skill", "without_skill", "old_skill"):
                arm_dir = eval_dir / arm
                if not arm_dir.is_dir():
                    continue
                grading = _read_json(arm_dir / "grading.json")
                timing = _read_json(arm_dir / "timing.json")
                results = (grading or {}).get("assertion_results") if isinstance(grading, dict) else None
                n = len(results) if isinstance(results, list) else 0
                n_pass = sum(1 for r in results or [] if isinstance(r, dict) and r.get("passed") is True)
                tokens = timing.get("total_tokens") if isinstance(timing, dict) else None
                ms = timing.get("duration_ms") if isinstance(timing, dict) else None
                detail.append(f"- {it.name}/{eval_dir.name}/{arm}: "
                              f"{n_pass}/{n} 通过；tokens={tokens}；duration_ms={ms}")
                runs += 1

    if not iterations:
        return _res(RULES["MAT-004"], SKIP,
                    f"未生成：没找到评测工作区（{ws}）；E-07/E-08 需要 "
                    f"`<技能名>-workspace/iteration-N/` 下的 grading/timing/benchmark")
    body = _header("E-07、E-08", str(ws)) + "\n".join(lines) + "\n\n" + \
        (f"（共 {runs} 份逐次产物）\n\n" if runs else "（未找到逐次产物）\n\n") + \
        "\n".join(detail) + "\n"
    # 逐次产物可能很多，这里只保留前 200 行，并显式说明截断了
    body_lines = body.splitlines()
    if len(body_lines) > 400:
        body = "\n".join(body_lines[:400]) + f"\n\n（逐次产物明细过长，已截断；共 {runs} 份，详见工作区）\n"
    write_text(out, body)
    return _res(RULES["MAT-004"], PASS,
                f"已生成 {out.name}（{len(iterations)} 轮迭代，逐次产物 {runs} 份）")


def build_revision_signals(skill_dir: Path, out: Path, workspace: Path | None) -> Result:
    """E-03：把"该往哪改"的三条信号摘出来（失败断言 / 人工反馈 / 性能 delta）。"""
    ws = workspace or (skill_dir.parent / f"{skill_dir.name}-workspace")
    iterations = _iterations(ws)
    failed: list[str] = []
    feedback: list[str] = []
    perf: list[str] = []
    for it in iterations:
        for eval_dir in sorted(p for p in it.iterdir() if p.is_dir() and p.name.startswith("eval-")):
            for arm in ("with_skill", "old_skill"):
                grading = _read_json(eval_dir / arm / "grading.json")
                results = (grading or {}).get("assertion_results") if isinstance(grading, dict) else None
                for item in results or []:
                    if isinstance(item, dict) and item.get("passed") is False:
                        failed.append(f"- {it.name}/{eval_dir.name}/{arm}："
                                      f"{item.get('text')} —— {item.get('evidence')}")
        bench = _read_json(it / "benchmark.json")
        summary = (bench or {}).get("run_summary", {}) if isinstance(bench, dict) else {}
        delta = summary.get("delta") if isinstance(summary, dict) else None
        if isinstance(delta, dict) and delta:
            perf.append(f"- {it.name} delta：pass_rate {delta.get('pass_rate', '-')}、"
                        f"time_seconds {delta.get('time_seconds', '-')}、"
                        f"tokens {delta.get('tokens', '-')}")
    fb = _read_json(ws / "feedback.json")
    if isinstance(fb, dict):
        for key, value in fb.items():
            if isinstance(value, str) and value.strip():
                feedback.append(f"- {key}：{value}")
        if not feedback:
            feedback.append("- （人工反馈均为空，表示复核无异议）")

    if not iterations and not feedback:
        return _res(RULES["MAT-002"], SKIP,
                    f"未生成：既没有工作区（{ws}）也没有 feedback.json——"
                    f"E-03 需要失败断言 / 人工反馈 / 性能 delta 中的至少一类")

    body = _header("E-03", str(ws)) + "\n".join([
        "## 一、失败的断言（含证据）", "", *(failed or ["- （无失败断言）"]), "",
        "## 二、人工反馈（非空条目才是问题）", "", *(feedback or ["- （没有 feedback.json）"]), "",
        "## 三、性能与增益 delta", "", *(perf or ["- （没有 benchmark.json）"]), "",
    ])
    write_text(out, body)
    return _res(RULES["MAT-002"], PASS,
                f"已生成 {out.name}（失败断言 {len(failed)} 条、反馈 {len(feedback)} 条、"
                f"delta {len(perf)} 条）")


def build_blind(
    skill_dir: Path, out_dir: Path, left: Path | None, right: Path | None, seed: int | None
) -> Result:
    """E-06：把两版产物随机落到 blind-A / blind-B，映射封存。"""
    if left is None or right is None:
        return _res(RULES["MAT-003"], SKIP,
                    "未生成：没有给两版产物（用 `--blind <旧版> <新版>`）")
    for path in (left, right):
        if not path.exists():
            return _res(RULES["MAT-003"], SKIP, f"未生成：{path} 不存在")
    rng = random.Random(seed if seed is not None else None)
    order = [left, right]
    rng.shuffle(order)
    out_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    for letter, source in zip(("blind-A", "blind-B"), order):
        target = out_dir / letter
        if target.exists():
            shutil.rmtree(target)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.mkdir(parents=True)
            shutil.copy2(source, target / source.name)
        mapping[letter] = str(source)
    write_text(out_dir / "README.md", _header(
        "E-06", f"{left} 与 {right}（随机分配）") + (
        "本目录下是两版产物，已随机记为 `blind-A/` 与 `blind-B/`。\n\n"
        "**评审时不要打开 `mapping.json`**——盲评的意义就在于不知道哪版是新的。\n"
        "给出结论后，再由另一个人核对 mapping 并写入回写文件。\n"))
    write_text(out_dir / "mapping.json", json.dumps(
        {"schema": MATERIAL_SCHEMA + "/blind", "mapping": mapping,
         "note": "评审者不得在给结论前查看本文件"}, ensure_ascii=False, indent=2) + "\n")
    return _res(RULES["MAT-003"], PASS,
                f"已生成 {out_dir.name}/（blind-A 与 blind-B 已随机分配，映射封存在 mapping.json）")


def _skill_card(path: Path) -> tuple[str, str]:
    """读一个技能的 name 与 description（`load_skill` 不抛异常，读不出就是空串）。"""
    doc = load_skill(path)
    return doc.name.strip(), doc.description.strip()


def sibling_skills(skill_dir: Path) -> list[Path]:
    """**同级**目录里的其它技能（`<root>/<技能名>/SKILL.md` 布局）。

    局限（会写进材料，不藏着）：只在同级找。分类嵌套（`<root>/<类别>/<技能>/`）或库横跨
    多个根时会漏——那种布局请手工补一份清单；全库预算与重叠提示另有 `LIB-001`/`LIB-002` 管。
    """
    out: list[Path] = []
    for path in sorted(skill_dir.parent.iterdir()):
        if not path.is_dir() or path.resolve() == skill_dir.resolve():
            continue
        if find_skill_md(path) is not None:
            out.append(path)
    return out


def build_adjacency(skill_dir: Path, out: Path) -> Result:
    """W-11 的材料：相邻技能边界清单（词面重叠排序 + 留给人填的「边界裁决」栏）。

    只提供事实：重叠系数是**词面**重叠（与 `LIB-002` 同一套词元与系数），不是语义相似度；
    「这个场景该归谁」由 W-11 判。**不判缺陷**（重叠高≠有错，可能是该合并，也可能是分工清晰）。
    """
    try:
        neighbors = sibling_skills(skill_dir)
    except OSError as exc:
        return _res(RULES["MAT-005"], SKIP,
                    f"未生成：无法列出同级目录 {skill_dir.parent}（{exc}）")
    if not neighbors:
        return _res(RULES["MAT-005"], INFO,
                    f"不适用：{skill_dir.parent} 下没有别的技能目录"
                    f"（本材料只在同级找邻居；分类嵌套或多根布局请手工提供清单）")

    this_name, this_desc = _skill_card(skill_dir)
    this_tokens = lib_tokens(this_desc)
    rows: list[tuple[float, str, str, list[str], str]] = []
    for path in neighbors:
        name, desc = _skill_card(path)
        if len(this_tokens) < MIN_TOKENS or len(lib_tokens(desc)) < MIN_TOKENS:
            rows.append((0.0, name or path.name, path.name, [], f"—（词元不足 {MIN_TOKENS}）"))
            continue
        score, shared = token_overlap(this_tokens, lib_tokens(desc))
        rows.append((score, name or path.name, path.name, shared, f"{score:.2f}"))
    rows.sort(key=lambda row: (-row[0], row[1]))

    lines = [
        _header("W-11（触发撰写原则）", f"同级技能目录 {skill_dir.parent}"),
        "## 本技能\n\n",
        f"- 名称：`{this_name or skill_dir.name}`\n",
        f"- description：{this_desc or '（读不出 description）'}\n\n",
        f"## 相邻技能（{len(rows)} 个，按描述词面重叠从高到低）\n\n",
        "| 邻居 | 词面重叠 | 共同词元 | 边界裁决（请填写：该场景归谁 / 无串扰） |\n",
        "|---|---|---|---|\n",
    ]
    for _score, name, dirname, shared, score_txt in rows:
        common = "、".join(f"`{t}`" for t in shared[:8]) or "（无共同词元）"
        lines.append(f"| `{name}`（`{dirname}/`） | {score_txt} | {common} |  |\n")
    lines.append(
        "\n## 怎么用这份清单\n\n"
        "- 词面重叠 = 交集 / 较小集合（ASCII 词 + CJK 字符 bigram），**不是语义相似度**：\n"
        "  高重叠只说明「值得逐个比对」，串扰与否归 W-11 判；\n"
        "- 「边界裁决」栏请逐行填：要么写明该场景由哪个技能承接，要么写「无串扰」——\n"
        "  空着就说明这一行没人评估过；\n"
        f"- 局限：只在**同级目录**里找邻居（分类嵌套或多根布局会漏）；"
        f"词元少于 {MIN_TOKENS} 的描述不参与计分（列出来只为让你知道它存在）；"
        f"全库预算与全库重叠提示由 `LIB-001`/`LIB-002` 负责。\n")
    write_text(out, "".join(lines))
    top = rows[0]
    return _res(RULES["MAT-005"], PASS,
                f"已生成 {out.name}（{len(rows)} 个邻居；最像的是 `{top[1]}`，"
                f"词面重叠 {top[4]}）")


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #


def build_materials(
    skill_dir: Path,
    *,
    out_dir: Path | None = None,
    workspace: Path | None = None,
    diff_base: str | None = None,
    blind: tuple[Path | None, Path | None] = (None, None),
    blind_seed: int | None = None,
):
    """产出全部材料，返回 (Report, 写出的文件列表)。"""
    from .report import Report

    skill_dir = Path(skill_dir).resolve()
    out = Path(out_dir) if out_dir else (skill_dir.parent / f"{skill_dir.name}-review-material")
    out.mkdir(parents=True, exist_ok=True)
    report = Report(target=str(skill_dir), stage="material")
    written: list[Path] = []

    results = [
        build_description_diff(skill_dir, out / "description-diff.md", diff_base),
        build_revision_signals(skill_dir, out / "revision-signals.md", workspace),
        build_workspace_digest(skill_dir, out / "workspace-digest.md", workspace),
        build_adjacency(skill_dir, out / "adjacency.md"),
        build_blind(skill_dir, out / "blind", blind[0], blind[1], blind_seed),
    ]
    for res in results:
        report.add(res)
    for path in sorted(out.rglob("*")):
        if path.is_file():
            written.append(path)
    report.meta["材料目录"] = str(out)
    report.meta["材料文件数"] = str(len(written))
    report.meta["服务的提示词"] = "、".join(sorted(MATERIAL_FOR_PROMPT))
    return report, written
