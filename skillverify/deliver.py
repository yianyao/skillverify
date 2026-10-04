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


def write_record(trace_dir: Path, record: dict, markdown: str) -> list[Path]:
    """写交付记录：latest.json / latest.md + 追加一行到 history.jsonl。

    **为什么 history 是 JSONL 而不是一堆时间戳文件**：两人团队不会去清理
    按次生成的目录，几个月后就是几百个文件；追加一行既可 grep 又不会堆积。
    """
    deliver_dir = trace_dir / "deliver"
    deliver_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

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
    PYTHONPATH="$CHECKOUT${{PYTHONPATH:+{sep}$PYTHONPATH}}"
    export PYTHONPATH
    exec "$PY" -m skillverify.cli deliver --staged --quiet
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
    return path, action


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
