"""watch —— 文件监听与增量复跑（开发期即时反馈）。

**为什么是轮询而不是文件系统事件**：宿主无关是硬约束，而文件系统事件 API
（Windows ReadDirectoryChangesW / Linux inotify / macOS FSEvents）各不相同，
第三方库（watchdog）又违背"纯标准库优先"。两人团队的技能库通常只有个位数到几十个
技能，按 `stat` 轮询（默认 1 秒一次）成本可以忽略；**指纹只取 stat 信息，不读内容**。
**边界（说清楚，别当成安全机制）**：stat 指纹**防手滑、不防篡改**——`mtime` 与大小都能被
`os.utime` 之类的调用伪造。它的用途是"改了就跑"，**不是**完整性校验；要完整性证据请用 git
（本项目的历史留痕一律以 git 为单一真源）。

**增量口径**：只复跑"指纹变了"的技能，而不是整库。技能数一多，全库复跑会让
watch 变成噪音源（每次保存都等几秒）。

**默认不执行脚本**：watch 会高频复跑，`--scripts` 在这里意味着每保存一次就执行一遍
技能自带脚本——不仅慢，而且有副作用。故 `watch` 不接受 `--scripts`（要实测脚本契约
就手动跑 `lint --scripts` 或 `deliver --strict`）。

**单轮异常不致命**：某一轮检查出异常时打印并继续下一轮（一个会因为一个坏文件就退出的
watch 没有使用价值），但异常轮次会体现在退出码上。
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, TextIO

from .discover import SKIP_DIRS, HostProfile, SkillRef, discover_skills
from .lint import lint_skill
from .report import FAIL, SKIP, WARN, LibraryEntry, LibraryReport, Report
from .spec import check_spec

#: 单轮报告里最多列出的"需关注"行数（其余只计数），避免刷屏
MAX_NOTABLE_ROWS = 20


@dataclass
class ChangeSet:
    """两轮快照之间的差异。"""

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def describe(self) -> str:
        parts = []
        if self.added:
            parts.append(f"新增 {len(self.added)}: {', '.join(self.added)}")
        if self.changed:
            parts.append(f"变更 {len(self.changed)}: {', '.join(self.changed)}")
        if self.removed:
            parts.append(f"移除 {len(self.removed)}: {', '.join(self.removed)}")
        return "；".join(parts) if parts else "无变化"

    def to_dict(self) -> dict:
        return {"added": self.added, "removed": self.removed, "changed": self.changed}

    def targets(self) -> list[str]:
        """需要复跑的技能（移除的只需报告，无内容可查）。"""
        return sorted({*self.added, *self.changed})


def fingerprint(skill_path: Path) -> str:
    """技能目录的指纹：相对路径 + 大小 + 纳秒级 mtime（**不读文件内容**）。"""
    entries: list[str] = []
    stack = [skill_path]
    while stack:
        current = stack.pop()
        try:
            children = sorted(current.iterdir())
        except OSError:
            continue
        for child in children:
            name = child.name
            if name in SKIP_DIRS:
                continue
            try:
                if child.is_symlink():
                    entries.append(f"{child.relative_to(skill_path).as_posix()}|link")
                    continue
                if child.is_dir():
                    stack.append(child)
                    continue
                stat = child.stat()
            except OSError:
                entries.append(f"{child.relative_to(skill_path).as_posix()}|err")
                continue
            rel = child.relative_to(skill_path).as_posix()
            entries.append(f"{rel}|{stat.st_size}|{stat.st_mtime_ns}")
    entries.sort()
    return hashlib.sha256("\n".join(entries).encode("utf-8", "replace")).hexdigest()[:16]


def snapshot(skills: list[SkillRef]) -> dict[str, str]:
    return {ref.name: fingerprint(ref.path) for ref in skills}


def diff_snapshots(prev: dict[str, str], cur: dict[str, str]) -> ChangeSet:
    changes = ChangeSet()
    for name, digest in cur.items():
        if name not in prev:
            changes.added.append(name)
        elif prev[name] != digest:
            changes.changed.append(name)
    for name in prev:
        if name not in cur:
            changes.removed.append(name)
    changes.added.sort()
    changes.changed.sort()
    changes.removed.sort()
    return changes


def _check_skills(
    refs: list[SkillRef], *, stages: str, script_timeout_s: float
) -> LibraryReport:
    library = LibraryReport(stage="watch", target="")
    for ref in refs:
        results = []
        if stages in ("both", "spec"):
            _doc, rep = check_spec(ref.path)
            results.extend(rep.results)
        if stages in ("both", "lint"):
            rep = lint_skill(ref.path, run_scripts=False, script_timeout_s=script_timeout_s)
            results.extend(rep.results)
        merged = Report(target=str(ref.path), stage="watch")
        merged.results = results
        library.add_entry(
            LibraryEntry(skill=ref.name, scope=ref.scope, path=str(ref.path), report=merged)
        )
    return library


def _render_cycle(
    index: int,
    changes: ChangeSet,
    library: LibraryReport | None,
    *,
    stream: TextIO,
    as_json: bool,
    first: bool = False,
) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    if as_json:
        payload = {
            "cycle": index,
            "first": first,
            "at": stamp,
            "changes": changes.to_dict(),
            "skills": [
                {"skill": e.skill, "verdict": e.report.verdict(), "counts": e.counts()}
                for e in (library.entries if library else [])
            ],
            "notable": [
                {"skill": e.skill, "rid": r.rid, "status": r.status,
                 "level": r.level, "optional": r.optional, "evidence": r.evidence}
                for e in (library.entries if library else [])
                for r in e.report.sorted_results()
                if r.status in (FAIL, WARN, SKIP)
            ],
        }
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        stream.flush()
        return

    if first:
        head = f"首轮全量（{len(library.entries) if library else 0} 个技能）"
    else:
        head = changes.describe()
    stream.write(f"[{stamp}] 第 {index} 轮 · {head}\n")
    if library is None:
        stream.flush()
        return
    notable = [
        (entry, res)
        for entry in library.entries
        for res in entry.report.sorted_results()
        if res.status in (FAIL, WARN, SKIP)
    ]
    for entry, res in notable[:MAX_NOTABLE_ROWS]:
        mark = "（未覆盖）" if res.optional and res.status == SKIP else ""
        stream.write(f"    {res.status:<4} {entry.skill} · {res.rid} · "
                     f"{res.evidence or res.title}{mark}\n")
    if len(notable) > MAX_NOTABLE_ROWS:
        stream.write(f"    …另有 {len(notable) - MAX_NOTABLE_ROWS} 条，"
                     f"详见 `skillverify check` 报告\n")
    verdicts = library.skill_verdicts()
    stream.write(
        f"    本轮复跑 {len(library.entries)} 个技能："
        f"PASS={verdicts['PASS']} WARN={verdicts['WARN']} FAIL={verdicts['FAIL']}\n"
    )
    stream.flush()


def run_watch(
    project: Path,
    user_home: Path,
    profile: HostProfile,
    *,
    roots: list[str] | None = None,
    stages: str = "both",
    interval: float = 1.0,
    cycles: int | None = None,
    script_timeout_s: float = 10.0,
    stream: TextIO | None = None,
    as_json: bool = False,
    on_cycle: Callable[[int, ChangeSet], None] | None = None,
) -> int:
    """轮询技能库并在变化时立即复跑。返回最后一次复跑的退出码（0/1/2）。

    `cycles` 为 None 表示不限轮数（Ctrl-C 退出）；`on_cycle` 仅供测试注入时序。
    """
    out = stream or sys.stdout
    exit_code = 0
    previous: dict[str, str] = {}
    index = 0
    interrupted = False

    if not as_json:
        out.write(
            f"skillverify watch · 宿主档 {profile.name} · 每 {interval:g}s 轮询 · "
            f"阶段 {stages} · Ctrl-C 退出\n"
        )
        out.flush()

    while cycles is None or index < cycles:
        index += 1
        changes = ChangeSet()
        first = index == 1
        try:
            discovery = discover_skills(profile, project, user_home, roots=roots)
            current = snapshot(discovery.skills)
            changes = diff_snapshots(previous, current)
            previous = current

            library: LibraryReport | None = None
            if first or not changes.empty:
                targets = discovery.skills if first else [
                    ref for ref in discovery.skills if ref.name in set(changes.targets())
                ]
                library = _check_skills(
                    targets, stages=stages, script_timeout_s=script_timeout_s
                )
                exit_code = library.exit_code()
                _render_cycle(index, changes, library, stream=out, as_json=as_json,
                              first=first)
            else:
                _render_cycle(index, changes, None, stream=out, as_json=as_json)
        except Exception as exc:  # noqa: BLE001 - 监听器不得因单轮异常退出
            exit_code = 1
            out.write(f"[watch] 第 {index} 轮检查异常（已跳过，继续监听）: "
                      f"{type(exc).__name__}: {exc}\n")
            out.flush()

        if on_cycle is not None:
            on_cycle(index, changes)
        if cycles is not None and index >= cycles:
            break
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            interrupted = True
            break

    if interrupted:
        out.write("[watch] 已停止。\n")
    return exit_code
