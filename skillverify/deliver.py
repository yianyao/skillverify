"""deliver —— 交付门禁、交付记录与 git hook。

**`check` 与 `deliver` 的区别（这是本模块存在的理由）**：
- `check` 是**日常检查**：有 WARN/SKIP 也照常返回，给人看。
- `deliver` 是**交付门禁**：要求"没有 FAIL，且没有未覆盖项"。
  交付意味着"我说这份东西我查过了"——允许带着没查的项交付，就是把
  "覆盖有洞"洗成"通过"，正是旧体系最容易失真的地方。

门禁口径（逐条明示，避免"看起来严"）：
- **FAIL 阻断**。
- **WARN 不阻断**，但必须逐条列进交付记录（对应"需人工书面甄别"，
  记录即书面痕迹）。
- **SKIP 分两类**：`optional=True`（未开启 `--scripts`、解释器不可用、
  时间预算用尽——不是技能自身缺陷）默认不阻断，但逐条列入"未覆盖项"；
  其余 SKIP（读取失败、无法判定语言等）**阻断**。
- `--strict`：连 `optional` 的未覆盖项也阻断。发行前跑一次 `--strict`。

**故障开放 vs 故障关闭（hook 的取舍）**：hook 找不到可执行的 skillverify 时
**不阻断提交**，只打印醒目告警。理由：一个会把你锁死在"改不动也提交不了"状态的
门禁，对两人团队比漏检更糟；`SKILLVERIFY_HOOK_STRICT=1` 可改为故障关闭。
`git commit --no-verify` 始终可绕过——这是 git 的既有语义，不假装能防住。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .encoding import read_json
from .discover import Discovery, SkillRef
from .report import FAIL, SKIP, WARN, LibraryReport

#: hook 文件里的标记行（用于识别"这个 hook 是我们装的"，从而可安全覆盖）
HOOK_MARKER = "skillverify-hook"
HOOK_VERSION = "v1"

#: 交付记录格式版本（改结构必须升版本，否则历史记录无法解释）
RECORD_SCHEMA = "skillverify.delivery/1"


# --------------------------------------------------------------------------- #
# git 交互（只读查询，除 hook 安装外不改动仓库）
# --------------------------------------------------------------------------- #


def _git(project: Path, args: list[str], timeout: float = 30.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(project), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout or "").strip()


def is_git_repo(project: Path) -> bool:
    return _git(project, ["rev-parse", "--is-inside-work-tree"])[0] == 0


def repo_root(project: Path) -> Path | None:
    code, out = _git(project, ["rev-parse", "--show-toplevel"])
    return Path(out) if code == 0 and out else None


def staged_paths(project: Path) -> list[str] | None:
    """已暂存（含新增/修改/改名）的文件，路径相对仓库根；非 git 仓库返回 None。"""
    code, out = _git(project, ["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    if code != 0:
        return None
    return [line.strip() for line in out.splitlines() if line.strip()]


def git_info(project: Path) -> dict:
    """交付记录里的版本锚点：提交号、分支、是否有未提交改动。"""
    info: dict[str, object] = {}
    root = repo_root(project)
    if root is None:
        return {"repo": None}
    info["repo"] = str(root)
    code, out = _git(project, ["rev-parse", "HEAD"])
    info["commit"] = out if code == 0 else None
    code, out = _git(project, ["rev-parse", "--abbrev-ref", "HEAD"])
    info["branch"] = out if code == 0 else None
    code, out = _git(project, ["status", "--porcelain"])
    info["dirty"] = bool(out) if code == 0 else None
    return info


def filter_staged_skills(
    project: Path, discovery: Discovery
) -> tuple[list[SkillRef], list[str], str | None]:
    """按 git 暂存内容筛出受影响的技能。

    返回 (受影响的技能, 与技能无关的暂存文件, 无法判定时的原因)。
    路径归属用**目录前缀**判断，不看文件名——技能内的任何文件（含 assets/）
    改动都应触发该技能复检。
    """
    paths = staged_paths(project)
    if paths is None:
        return list(discovery.skills), [], "非 git 仓库（--staged 退化为全量）"
    root = repo_root(project) or project
    root = root.resolve()

    affected: list[SkillRef] = []
    unrelated: list[str] = []
    resolved_skills = [(s, s.path.resolve()) for s in discovery.skills]
    for rel in paths:
        full = (root / rel)
        try:
            full_resolved = full.resolve()
        except OSError:
            full_resolved = full
        hit = None
        for skill, skill_path in resolved_skills:
            if full_resolved == skill_path or skill_path in full_resolved.parents:
                hit = skill
                break
        if hit is not None:
            if hit not in affected:
                affected.append(hit)
        else:
            unrelated.append(rel)
    return affected, unrelated, None


# --------------------------------------------------------------------------- #
# 门禁
# --------------------------------------------------------------------------- #


@dataclass
class DeliveryGate:
    """交付门禁结论。"""

    passed: bool
    strict: bool
    blockers: list[str] = field(default_factory=list)      # MUST 修：FAIL
    waivers: list[str] = field(default_factory=list)       # 已豁免（显式 + 有理由）
    uncovered: list[str] = field(default_factory=list)     # 未覆盖（optional SKIP）
    warnings: list[str] = field(default_factory=list)      # 需书面甄别
    checked_skills: int = 0

    def to_dict(self) -> dict:
        return {
            "result": "pass" if self.passed else "fail",
            "strict": self.strict,
            "checked_skills": self.checked_skills,
            "blockers": list(self.blockers),
            "uncovered": list(self.uncovered),
            "warnings": list(self.warnings),
            "waivers": list(self.waivers),
        }

    def summary(self) -> str:
        state = "通过" if self.passed else "未通过"
        return (
            f"交付门禁{state}：技能 {self.checked_skills} 个；"
            f"阻断项 {len(self.blockers)}；未覆盖项 {len(self.uncovered)}；"
            f"待书面甄别 {len(self.warnings)}"
            + ("（strict 模式：未覆盖项同样阻断）" if self.strict else "")
        )


def evaluate(library: LibraryReport, *, strict: bool = False) -> DeliveryGate:
    """按上述口径算门禁结论。判定只看 status/optional，不看证据文本。"""
    gate = DeliveryGate(passed=True, strict=strict, checked_skills=len(library.entries))
    for entry in library.entries:
        for res in entry.report.results:
            item = f"{entry.skill} · {res.rid} · {res.evidence or res.title}"
            if res.status == FAIL:
                gate.blockers.append(item)
            elif res.status == SKIP:
                if res.optional and not strict:
                    gate.uncovered.append(item)
                else:
                    gate.blockers.append(
                        item if not res.optional else f"{item}（strict：要求全项覆盖）"
                    )
            elif res.status == WARN:
                gate.warnings.append(item)
    for res in library.results:  # 库级结果（如 DISC-001 歧义）
        item = f"(库级) {res.rid} · {res.evidence or res.title}"
        if res.status == FAIL:
            gate.blockers.append(item)
        elif res.status == SKIP:
            gate.blockers.append(item)
        elif res.status == WARN:
            gate.warnings.append(item)
    gate.passed = not gate.blockers
    return gate


def apply_waivers(gate: DeliveryGate, rids: list[str], because: str,
                  *, by: str = "") -> tuple[DeliveryGate, list[str]]:
    """把指定规则的阻断项降级为「已豁免」，返回 (gate, 豁免明细)。

    **为什么需要这个出口**：机械层会有误报（尤其 SHOULD 级），而两人团队不该只有
    「修好」一条路——方案 §6.1 原本就要求「[S] 级书面说明后放行」。
    但豁免必须**显式 + 有理由 + 落盘**：绝不静默放过，记录里能查到是谁、为什么放过的。
    """
    wanted = {rid.strip() for rid in rids if rid.strip()}
    kept: list[str] = []
    waived: list[str] = []
    for item in gate.blockers:
        parts = item.split("·")
        rid = parts[1].strip() if len(parts) > 1 else ""
        if rid in wanted:
            suffix = f"；豁免人：{by}" if by else ""
            waived.append(f"{item}（豁免理由：{because}{suffix}）")
        else:
            kept.append(item)
    gate.blockers = kept
    gate.waivers = waived
    gate.passed = not kept
    return gate, waived


def workspace_fingerprints(skill_path: Path) -> dict[str, str]:
    """技能并列工作区里每个 iteration 的指纹（用于发现「历史 iteration 被覆盖」）。

    工作区是**兄弟目录**（`<技能名>-workspace/`）；没有就返回空字典。
    """
    from .watch import fingerprint

    for candidate in (skill_path.parent / f"{skill_path.name}-workspace",):
        if not candidate.is_dir():
            continue
        out: dict[str, str] = {}
        for child in sorted(candidate.iterdir()):
            if child.is_dir() and child.name.startswith("iteration-"):
                out[child.name] = fingerprint(child)
        return out
    return {}


def _reviewers(trace_dir: Path | None, skills: list[str]) -> dict:
    """从评审记录里取出每个技能的 Judge 身份（模型/人名）——出问题时要能定位「谁判的」。"""
    if trace_dir is None:
        return {}
    out: dict = {}
    for skill in skills:
        data, error = read_json(trace_dir / "review" / f"{skill}.json")
        if error or not isinstance(data, dict):
            continue
        out[skill] = {key: data.get(key) for key in ("reviewer", "tier", "generated_at", "verdict")}
    return out


def rules_hash() -> str:
    """当前规则集的指纹：交付记录必须能证明"是哪套规则判的"。"""
    from .lint import RULES as LINT_RULES
    from .spec import RULES as SPEC_RULES

    payload = []
    for rules in (SPEC_RULES, LINT_RULES):
        for rid in sorted(rules):
            rule = rules[rid]
            payload.append(f"{rule.rid}|{rule.level}|{rule.title}|{rule.source}")
    digest = hashlib.sha256("\n".join(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"


# --------------------------------------------------------------------------- #
# 交付记录
# --------------------------------------------------------------------------- #


def build_record(
    library: LibraryReport,
    gate: DeliveryGate,
    *,
    project: Path,
    scope: str,
    command: str,
    discovery: Discovery,
    unrelated: list[str] | None = None,
) -> dict:
    return {
        "schema": RECORD_SCHEMA,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "tool_version": __version__,
        "rules_hash": rules_hash(),
        "python": platform.python_version(),
        "project": str(project),
        "host_profile": discovery.profile.name if discovery.profile else None,
        "trace_dir": str(discovery.trace_dir) if discovery.trace_dir else None,
        "scope": scope,
        "command": command,
        "git": git_info(project),
        # 出问题时最难回答的是「是技能退化了，还是环境变了」——所以把判定环境一并记下来。
        # Judge 身份（模型/人名）来自评审记录；没有评审记录时为空。
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "tool_version": __version__,
            "rules_hash": rules_hash(),
        },
        "reviewers": _reviewers(discovery.trace_dir, [e.skill for e in library.entries]),
        "workspaces": {e.skill: workspace_fingerprints(Path(e.path)) for e in library.entries},
        "gate": gate.to_dict(),
        "counts": library.counts(),
        "skills": [
            {
                "skill": e.skill,
                "scope": e.scope,
                "path": e.path,
                "verdict": e.report.verdict(),
                "counts": e.counts(),
                "notable": [
                    {"rid": r.rid, "status": r.status, "level": r.level,
                     "optional": r.optional, "evidence": r.evidence}
                    for r in e.report.sorted_results()
                    if r.status in (FAIL, WARN, SKIP)
                ],
            }
            for e in library.entries
        ],
        "library_results": [r.to_dict() for r in library.results],
        "unrelated_staged": sorted(unrelated or []),
    }


def compare_with_previous(latest_json: Path, record: dict) -> dict:
    """与上一轮交付记录比对，返回 {"found": bool, ...} 的对比结果。

    比的是**结论是否退步**，而不是"文件有没有变"：
    上一轮 pass → 本轮 fail、或阻断项/未覆盖项变多，都是值得当场说出来的信号。
    """
    from .encoding import read_json

    if not latest_json.is_file():
        return {"found": False, "note": "这是第一条交付记录，没有可比的上一轮"}
    previous, error = read_json(latest_json)
    if error or not isinstance(previous, dict):
        return {"found": False, "note": f"上一轮记录不可读（{error or '形状不符'}）"}
    old_gate = previous.get("gate") or {}
    new_gate = record.get("gate") or {}
    old = {"result": old_gate.get("result"), "blockers": len(old_gate.get("blockers") or []),
           "uncovered": len(old_gate.get("uncovered") or []),
           "warnings": len(old_gate.get("warnings") or [])}
    new = {"result": new_gate.get("result"), "blockers": len(new_gate.get("blockers") or []),
           "uncovered": len(new_gate.get("uncovered") or []),
           "warnings": len(new_gate.get("warnings") or [])}
    # A7：工作区 iteration 的历史被改动/覆盖（deliver 只管交付记录历史，工作区是另一回事）
    rewritten: list[str] = []
    old_ws = previous.get("workspaces") or {}
    for skill, iters in (record.get("workspaces") or {}).items():
        for name, digest in (iters or {}).items():
            before = (old_ws.get(skill) or {}).get(name)
            if before and before != digest:
                rewritten.append(f"{skill}/{name}")

    rank = {"pass": 0, "warn": 1, "fail": 2}
    worse_by_result = rank.get(str(new["result"]), 0) > rank.get(str(old["result"]), 0)
    worse = worse_by_result or new["blockers"] > old["blockers"]
    better = (rank.get(str(new["result"]), 0) < rank.get(str(old["result"]), 0)
              and new["blockers"] <= old["blockers"])
    changed_skills: list[str] = []
    old_skills = {s.get("skill"): s.get("verdict") for s in (previous.get("skills") or [])
                  if isinstance(s, dict)}
    for item in record.get("skills") or []:
        if not isinstance(item, dict):
            continue
        name, verdict = item.get("skill"), item.get("verdict")
        if name in old_skills and old_skills[name] != verdict:
            changed_skills.append(f"{name}: {old_skills[name]} → {verdict}")
    return {
        "found": True,
        "at": previous.get("generated_at"),
        "history_rewritten": rewritten,
        "before": old,
        "after": new,
        "worse": worse,
        "better": better,
        "changed_skills": changed_skills,
        "note": (("工作区历史被改动：" + "、".join(rewritten) + "。") if rewritten else "")
                + ("与上一轮相比**退步**：" if worse else
                 ("与上一轮相比有改善：" if better else "与上一轮相比无实质变化："))
                + f"{old['result']} → {new['result']}（阻断项 {old['blockers']} → {new['blockers']}，"
                  f"未覆盖 {old['uncovered']} → {new['uncovered']}）",
    }


def attach_previous(trace_dir: Path, record: dict) -> dict:
    """在**输出/落盘之前**把与上一轮的比对附到记录上，并返回比对结果。

    必须早于 `--json` 的输出：否则机器消费方（CI）读到的记录里没有对比，
    "这次改动把它改坏了"这个信号就只有人肉看 latest.md 才能发现。
    """
    # 只读比对：**不建目录**（"没东西可查就不留痕"是既有约定，比对不该有副作用）
    latest_json = trace_dir / "deliver" / "latest.json"
    record["previous"] = compare_with_previous(latest_json, record)
    return record["previous"]


def write_record(trace_dir: Path, record: dict, markdown: str) -> list[Path]:
    """写交付记录：latest.json / latest.md + 追加一行到 history.jsonl。

    **为什么 history 是 JSONL 而不是一堆时间戳文件**：两人团队不会去清理
    按次生成的目录，几个月后就是几百个文件；追加一行既可 grep 又不会堆积。
    """
    deliver_dir = trace_dir / "deliver"
    deliver_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # V29 的仓库侧：**写入前**先与上一轮比对，把"变好还是变坏"写进记录。
    # 历史不丢（history.jsonl 追加），但 latest.json 会被覆盖——覆盖前留下对比，
    # 才能看出"这次改动把它改坏了"，否则旧结论一被覆盖就再也无从比较。
    latest_json = deliver_dir / "latest.json"
    if "previous" not in record:          # 调用方已算过就不重复算
        record["previous"] = compare_with_previous(latest_json, record)

    latest_json = deliver_dir / "latest.json"
    latest_json.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8", newline="\n",
    )
    written.append(latest_json)

    latest_md = deliver_dir / "latest.md"
    latest_md.write_text(markdown if markdown.endswith("\n") else markdown + "\n",
                         encoding="utf-8", newline="\n")
    written.append(latest_md)

    history = deliver_dir / "history.jsonl"
    line = {
        "generated_at": record["generated_at"],
        "scope": record["scope"],
        "result": record["gate"]["result"],
        "skills": record["gate"]["checked_skills"],
        "blockers": len(record["gate"]["blockers"]),
        "uncovered": len(record["gate"]["uncovered"]),
        "warnings": len(record["gate"]["warnings"]),
        "commit": (record.get("git") or {}).get("commit"),
        "rules_hash": record["rules_hash"],
    }
    with history.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    written.append(history)
    return written


# --------------------------------------------------------------------------- #
# git hook
# --------------------------------------------------------------------------- #


def hooks_dir(project: Path) -> Path:
    """hooks 目录（用 `git rev-parse --git-path hooks`，兼容 worktree 与 core.hooksPath）。"""
    code, out = _git(project, ["rev-parse", "--git-path", "hooks"])
    if code == 0 and out:
        path = Path(out)
        return path if path.is_absolute() else (project / path)
    root = repo_root(project) or project
    return root / ".git" / "hooks"


def hook_path(project: Path) -> Path:
    return hooks_dir(project) / "pre-commit"


def _sh_path(path: Path) -> str:
    """转成 Git Bash 能交给 Windows Python 的路径写法（正斜杠）。"""
    return str(path).replace("\\", "/")


def hook_content(python: str, checkout: Path, *, fail_closed: bool = False) -> str:
    """生成 pre-commit hook（POSIX sh：git 在 Windows 上也用自带 sh 执行 hook）。"""
    sep = ";" if os.name == "nt" else ":"
    strict_exit = "exit 1" if fail_closed else "exit 0"
    return f"""#!/bin/sh
# {HOOK_MARKER} {HOOK_VERSION} —— 由 `skillverify hook install` 生成，请勿手工编辑。
# 想临时跳过：git commit --no-verify
# 想卸载：删除本文件
set -u

if [ "${{SKILLVERIFY_SKIP:-0}}" = "1" ]; then
    echo "{HOOK_MARKER}: SKILLVERIFY_SKIP=1，跳过交付门禁" >&2
    exit 0
fi

if command -v skillverify >/dev/null 2>&1; then
    exec skillverify deliver --staged --quiet
fi

PY="{_sh_path(Path(python))}"
CHECKOUT="{_sh_path(checkout)}"
if [ -x "$PY" ]; then
    # 用 `-c` + sys.path.insert 而不是 `-m` + PYTHONPATH：嵌入式发行版（带 `._pth`）会
    # **忽略 PYTHONPATH**，那种写法会让兜底静默失效（hook 只打印告警就放行，等于空转）。
    exec "$PY" -c "import sys; sys.path.insert(0, r'$CHECKOUT'); \
from skillverify.cli import main; raise SystemExit(main(['deliver', '--staged', '--quiet']))"
fi

echo "{HOOK_MARKER}: 未找到可执行的 skillverify（已安装的解释器: $PY）" >&2
echo "{HOOK_MARKER}: 本次提交**未**经过交付门禁。安装方式见项目文档。" >&2
if [ "${{SKILLVERIFY_HOOK_STRICT:-0}}" = "1" ]; then
    echo "{HOOK_MARKER}: SKILLVERIFY_HOOK_STRICT=1，按故障关闭处理。" >&2
    {strict_exit}
fi
{strict_exit}
"""


def install_hook(project: Path, *, force: bool = False, fail_closed: bool = False
                 ) -> tuple[Path, str]:
    """安装/更新 pre-commit hook。返回 (路径, 动作说明)。

    - 已存在且带我们的标记 → 直接更新（幂等）。
    - 已存在但不是我们的 → 默认拒绝改动；`force=True` 时先备份为 `.bak` 再覆盖。
    """
    if not is_git_repo(project):
        raise RuntimeError(f"不是 git 仓库: {project}（hook 只能装在 git 仓库里）")
    path = hook_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)

    action = "已安装"
    if path.exists():
        existing = path.read_text(encoding="utf-8", errors="replace")
        if HOOK_MARKER not in existing:
            if not force:
                raise RuntimeError(
                    f"{path} 已存在且不是 skillverify 的 hook；未做任何改动。"
                    f"确认可覆盖后加 --force（会先备份为 {path.name}.bak）"
                )
            backup = path.with_name(path.name + ".bak")
            shutil.copy2(path, backup)
            action = f"已覆盖（原 hook 备份为 {backup.name}）"
        else:
            action = "已更新"

    checkout = Path(__file__).resolve().parent.parent
    path.write_text(hook_content(sys.executable, checkout, fail_closed=fail_closed),
                    encoding="utf-8", newline="\n")
    try:  # POSIX 上需要可执行位
        path.chmod(path.stat().st_mode | 0o111)
    except OSError:
        pass

    # 装完**当场验一次兜底命令**：嵌入式/`._pth` 解释器上它可能压根导不进来，
    # 那时 hook 会静默空转（fail-open 是声明的取舍，但"装了就等于没装"必须当场说出来）。
    ok, why = probe_hook_fallback(sys.executable, checkout, cwd=project)
    if not ok:
        action += (f"；**注意**：兜底命令在这台机器上不可用（{why}）——"
                   f"若你的 PATH 里没有 skillverify，提交将不会被门禁检查")
    return path, action


def probe_hook_fallback(python: str, checkout: Path, *, cwd: Path | None = None,
                        timeout_s: float = 30.0) -> tuple[bool, str]:
    """测一次 hook 的兜底命令（与生成出来的 hook 同形），返回 (是否可用, 原因)。

    与 hook 里那段保持**同形**很重要：测别的形式等于没测。
    `cwd` 也要贴近真实：git 跑 hook 时的 cwd 是**被提交的那个项目**，不是本工具的 checkout——
    所以"在 checkout 目录里能 import"证明不了兜底可用（那里的 cwd 本来就在 sys.path 上）。
    """
    code = ("import sys; sys.path.insert(0, r'%s'); "
            "from skillverify.cli import main; print('ok')" % checkout)
    try:
        proc = subprocess.run([python, "-c", code], capture_output=True, text=True,
                              cwd=str(cwd) if cwd else None,
                              encoding="utf-8", errors="replace", timeout=timeout_s)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"无法执行 {python}（{exc}）"
    if proc.returncode == 0 and "ok" in (proc.stdout or ""):
        return True, ""
    detail = ((proc.stderr or proc.stdout or "").strip().splitlines() or ["无输出"])[-1]
    return False, detail[:120]


def hook_status(project: Path) -> tuple[str, Path]:
    """返回 (状态, 路径)。状态 ∈ 未安装 / 已安装(当前版本) / 已安装(版本不同) / 被他人占用。"""
    path = hook_path(project)
    if not path.exists():
        return "未安装", path
    text = path.read_text(encoding="utf-8", errors="replace")
    if HOOK_MARKER not in text:
        return "被他人占用（不是 skillverify 的 hook）", path
    if HOOK_MARKER + " " + HOOK_VERSION in text:
        return f"已安装（{HOOK_VERSION}，当前版本）", path
    return "已安装（版本与当前不同，建议重装）", path
