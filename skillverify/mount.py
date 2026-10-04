"""mount —— 挂载前置检查（**仓库侧**）。

**它验证什么、不验证什么（先说清楚，避免过度承诺）**

旧体系的挂载期（M0）要求三件事：V3 注册发现冒烟、V4 共存冒烟、V23 跨宿主加载冒烟。
其中**宿主侧**的部分（"宿主技能列表里看得见吗"、卸载/重装、真实触发匹配）本项目**做不到**——
我们没有宿主 API，也没有宿主运行时。所以这里只做**仓库侧**能确定的那一半：

| 检查 | 说明 | 旧方案对应 |
|---|---|---|
| `MOUNT-001` | 技能在**声明的宿主目录**里能被发现（不是"我以为我放进去了"） | V3 的仓库侧 |
| `MOUNT-002` | `SKILL.md` 可解析，`name`/`description` 都读得出来且非空 | V3 的仓库侧 |
| `MOUNT-003` | 同一宿主档内无同名冲突（两份同名技能 → 宿主加载哪份不确定） | V3 的边界 |
| `MOUNT-004` | **fail-loud**：把技能复制到临时目录、注入 3 种结构破坏，逐个断言解析器**报错**而不是静默跳过 | V23 的方法（**对我们的解析器**，不是对宿主） |

`--host` 可选：不指定就**逐个已配置的宿主档**都跑一遍（新接一个宿主时，这正是"零代码接入"的验收）。

**为什么不碰原目录**：V23 自己就写明"复制为临时副本……不触碰原目录"。这里照办：
所有注入都在 `tempfile` 里做，原技能目录全程只读。
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from .discover import Config, Discovery, discover_skills, load_config
from .encoding import read_text
from .frontmatter import FrontmatterError, parse_frontmatter
from .report import FAIL, PASS, SKIP, WARN, Report, Result, Rule

#: 旧方案的出处（本项目承接其**仓库侧**部分）
_LEGACY = "legacy/Agent-Skill-生命周期验证方案.md（V3 注册发现冒烟 / V23 跨宿主加载冒烟）"

RULES: dict[str, Rule] = {
    "MOUNT-001": Rule(
        "MOUNT-001",
        "技能在声明的宿主目录里可被发现",
        "HOUSE",
        _LEGACY,
        "把技能放进该宿主档声明的目录（`hosts.toml` 的 project_roots / user_roots），"
        "或用 `--root` 指定实际位置",
    ),
    "MOUNT-002": Rule(
        "MOUNT-002",
        "SKILL.md 可解析，name/description 可读且非空",
        "HOUSE",
        _LEGACY,
        "补齐 frontmatter 的 name 与 description；无法解析的 frontmatter 宿主会直接跳过该技能",
    ),
    "MOUNT-003": Rule(
        "MOUNT-003",
        "同一宿主档内无同名技能",
        "HOUSE",
        _LEGACY,
        "宿主加载哪一份同名技能是不确定的：删掉多余的那份，或明确保留哪一份",
    ),
    "MOUNT-004": Rule(
        "MOUNT-004",
        "结构损坏的 frontmatter 必须 fail-loud（对临时副本注入后逐个断言）",
        "HOUSE",
        _LEGACY,
        "解析器若静默接受损坏的 frontmatter，技能会在宿主里「消失」却没有任何提示——"
        "请报 bug（这是本工具自身的缺陷）",
    ),
}

#: fail-loud 探针：三种结构破坏（覆盖"没有 frontmatter / 缺必填 / 缩进坏了"）
PROBES: tuple[tuple[str, str, str], ...] = (
    ("没有 frontmatter", "SKILL.md", "# 只有正文\n\n没有 frontmatter 的技能。\n"),
    ("缺必填 name", "SKILL.md", "---\ndescription: 只有描述，没有 name。\n---\n\n# D\n"),
    ("顶层缩进坏了", "SKILL.md",
     "---\nname: probe-skill\ndescription: 缩进坏掉的 frontmatter。\n  裸缩进行: x\n---\n\n# D\n"),
)


def _res(rule: Rule, status: str, evidence: str = "") -> Result:
    return Result(rid=rule.rid, title=rule.title, status=status, level=rule.level,
                  evidence=evidence,
                  remediation=rule.remediation if status in (FAIL, WARN) else "")


@dataclass
class MountTarget:
    """一次挂载前置检查的对象。"""

    skill: Path
    profile: str


def _readable(skill: Path) -> tuple[str, str, str]:
    """返回 (name, description, 错误说明)。"""
    skill_md = None
    for candidate in ("SKILL.md", "skill.md"):
        path = skill / candidate
        if path.is_file():
            skill_md = path
            break
    if skill_md is None:
        return "", "", "目录里没有 SKILL.md"
    try:
        doc = parse_frontmatter(read_text(skill_md))
    except FrontmatterError as exc:
        return "", "", f"frontmatter 解析失败：{exc}"
    name = doc.get("name")
    desc = doc.get("description")
    name = name.strip() if isinstance(name, str) else ""
    desc = desc.strip() if isinstance(desc, str) else ""
    if not name:
        return "", desc, "frontmatter 里的 name 缺失或为空"
    return name, desc, ""


def check_fail_loud(skill_name: str) -> Result:
    """V23 的方法：对**临时副本**注入结构破坏，断言解析器逐个报错。"""
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="skillverify-mount-") as tmp:
        probe_root = Path(tmp) / skill_name
        probe_root.mkdir(parents=True)
        for label, filename, content in PROBES:
            (probe_root / filename).write_text(content, encoding="utf-8", newline="")
            name, _desc, error = _readable(probe_root)
            accepted = bool(name) and not error
            if accepted:
                failures.append(f"{label}：被静默接受了（name={name!r}）")
    if failures:
        return _res(RULES["MOUNT-004"], FAIL,
                    "损坏的 frontmatter 未被拦下：" + "；".join(failures))
    return _res(RULES["MOUNT-004"], PASS,
                f"{len(PROBES)} 种结构破坏全部 fail-loud（在临时副本上验证，未触碰原目录）")


def check_profile(profile_name: str, config: Config, project: Path, user_home: Path,
                  *, skill: str | None = None) -> list[Result]:
    """对**一个宿主档**做仓库侧挂载前置检查。"""
    out: list[Result] = []
    try:
        profile = config.profile(profile_name)
    except ConfigError as exc:
        return [_res(RULES["MOUNT-001"], FAIL, f"宿主档 {profile_name!r} 不可用：{exc}")]

    discovery: Discovery = discover_skills(profile, project, user_home)
    found = {ref.name: ref for ref in discovery.skills}
    where = f"[{profile_name}]"

    if skill is not None:
        ref = found.get(skill)
        if ref is None:
            out.append(_res(RULES["MOUNT-001"], FAIL,
                            f"{where} 在声明的宿主目录里没找到技能 {skill!r}"
                            f"（共发现 {len(found)} 个：{sorted(found)[:5]}）"))
            out.append(_res(RULES["MOUNT-002"], SKIP, f"{where} 未执行：技能未找到"))
            out.append(_res(RULES["MOUNT-003"], SKIP, f"{where} 未执行：技能未找到"))
            return out
        out.append(_res(RULES["MOUNT-001"], PASS, f"{where} 在 {ref.scope} 作用域下被发现：{ref.path}"))
        targets = [ref]
    else:
        if not discovery.skills:
            # 没放技能不是"技能的问题"，但对"挂载前置检查"这个动作来说就是没东西可查
            out.append(_res(RULES["MOUNT-001"], WARN,
                            f"{where} 声明的目录里没有任何技能（检查了 {len(discovery.roots)} 个根）"))
            out.append(_res(RULES["MOUNT-002"], SKIP, f"{where} 未执行：没有技能"))
            out.append(_res(RULES["MOUNT-003"], SKIP, f"{where} 未执行：没有技能"))
            return out
        out.append(_res(RULES["MOUNT-001"], PASS,
                        f"{where} 发现 {len(discovery.skills)} 个技能"))
        targets = list(discovery.skills)

    # MOUNT-002：name/description 可读
    unreadable: list[str] = []
    for ref in targets:
        name, desc, error = _readable(ref.path)
        if error:
            unreadable.append(f"{ref.name}: {error}")
        elif not desc:
            unreadable.append(f"{ref.name}: description 为空（宿主不会加载没有描述的技能）")
    out.append(_res(RULES["MOUNT-002"], FAIL if unreadable else PASS,
                    f"{where} " + ("；".join(unreadable) if unreadable
                                   else f"{len(targets)} 个技能的 name/description 均可读")))

    # MOUNT-003：同名冲突
    counts: dict[str, list[str]] = {}
    for ref in discovery.skills:
        counts.setdefault(ref.name, []).append(str(ref.path))
    dupes = {name: paths for name, paths in counts.items() if len(paths) > 1}
    out.append(_res(RULES["MOUNT-003"], WARN if dupes else PASS,
                    f"{where} 同名技能出现在多处：" + "；".join(
                        f"{n} → {', '.join(p)}" for n, p in dupes.items())
                    if dupes else f"{where} {len(counts)} 个技能名互不冲突"))

    return out


def run_mount(project: Path, user_home: Path, config: Config, *, host: str | None = None,
              skill: str | None = None, all_hosts: bool = False) -> Report:
    """做挂载前置检查。

    默认只查**当前生效的宿主档**：配置里那些兼容档（为别的宿主预留的布局）
    并不是你在用的，拿它们报「技能不在声明目录里」纯属噪声。
    要逐个档验收（例如新接一个宿主）就显式 `--all-hosts` 或 `--host <档名>`。
    """
    if host:
        names = [host]
        scope = host
    elif all_hosts:
        names = sorted(config.hosts)
        scope = "全部宿主档"
    else:
        names = [config.profile(None).name]
        scope = f"当前生效档 {names[0]}"
    report = Report(target=f"{project}（{scope}）", stage="mount")
    if not names:
        report.add(_res(RULES["MOUNT-001"], FAIL, "配置里没有任何宿主档可检查"))
        return report
    any_skill = False
    for name in names:
        results = check_profile(name, config, project, user_home, skill=skill)
        any_skill = any_skill or any(r.rid == "MOUNT-001" and r.status == PASS for r in results)
        for res in results:
            report.add(res)
    # fail-loud 与宿主档无关（探针用的是临时副本）→ 全局只做一次
    report.add(check_fail_loud(skill or "probe-skill"))
    report.meta["检查的宿主档"] = "、".join(names)
    report.meta["检查内容"] = "仓库侧：可发现性 / name·description 可读 / 同名冲突 / fail-loud"
    report.meta["不检查"] = "宿主注册表与真实触发匹配（本工具没有宿主 API；见命令说明）"
    return report


def load(project: Path, user_home: Path, *, extra_configs: list[Path] | None = None,
         no_config: bool = False) -> Config:
    """按 CLI 语义加载配置（与 discover 完全同一条路径，避免两套合并规则）。"""
    return load_config(project, user_home, extra_files=extra_configs,
                       use_discovered_files=not no_config)


__all__ = ["RULES", "PROBES", "MountTarget", "check_fail_loud", "check_profile", "load",
           "run_mount"]
