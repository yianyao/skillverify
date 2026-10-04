"""discover —— 技能发现与**声明式**宿主适配。

**本模块要解决的唯一问题**：技能放在哪里是**数据**，不是逻辑。
旧体系 `tools/host_compat.py` 把 46 个宿主的知识硬编码成 71 处启发式（还实测误判了
本机宿主），结果是"接入一个新宿主 = 改代码 + 加测试 + 重新发布"。
这里改成读 `hosts.toml`：接入新宿主只加一段声明，**0 行代码改动**。

设计要点（逐条对应验收口径"新 `--root` 模拟新宿主，0 行代码改动可跑通"）：
1. 内置配置是**数据文件**（`skillverify/data/hosts.toml`），代码里不出现任何宿主名。
2. 配置可叠加：内置 < 用户级 < 项目级 < `--config`。列表整体替换而非拼接——
   拼接会让"我想只查这两个根"这种意图无法表达。
3. `--root` 直接给出技能根，完全绕开配置里的根列表（`--host` 仍提供 max_depth 等参数），
   用于"模拟一个我手上还没有的宿主布局"。
4. 未知键**直接报错**而不是忽略：把 `project_root` 误写成单数而静默发现 0 个技能，
   是这类工具最坏的失败模式。
5. 缺目录不算错：项目里通常没有 `~/.某宿主/skills`，跳过即可；但显式 `--root`
   指向的目录不存在要报错（那是明确要求）。
6. 同名技能出现在多个根时记 DISC-001 歧义，**不做静默覆盖**——旧体系正是靠
   "某个根赢了"来掩盖两处不同步的问题。

Python 版本：解析 TOML 用标准库 `tomllib`（3.11+）。`tomllib` 只在真正读配置时导入，
因此 3.10 及更早仍可用 `spec`/`lint` 子命令；读到配置时才给出明确错误。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .report import INFO, WARN, Result, Rule
from .spec import find_skill_md

#: 没有 --host 时使用的档（= 官方跨宿主约定）
DEFAULT_PROFILE = "default"

#: 发现时不下钻的目录（与 lint 的 SKIP_DIRS 刻意各自维护：
#: 那边是"不进清单"，这边是"不递归"，两者会因不同原因变化）
SKIP_DIRS: frozenset[str] = frozenset(
    {".git", ".hg", ".svn", ".agents", ".verification", "node_modules",
     ".venv", "venv", ".idea", ".vscode", "__pycache__", ".mypy_cache",
     ".pytest_cache", ".ruff_cache", ".tox"}
)

#: 允许出现在 hosts.toml 里的键（严格校验，防拼写错误静默失效）
ALLOWED_KEYS = frozenset({"description", "project_roots", "user_roots", "trace_dir", "max_depth"})

RULES: dict[str, Rule] = {
    "DISC-001": Rule(
        "DISC-001",
        "同名技能出现在多个技能根（歧义）",
        "HOUSE",
        "本项目收紧：官方只约定技能内部结构，不规定存放位置",
        "确定哪个根是真源并删掉另一处；两处并存会让不同宿主加载到不同版本",
    ),
    "DISC-002": Rule(
        "DISC-002",
        "显式指定的技能根不可用",
        "HOUSE",
        "本项目收紧：显式 --root 是明确要求，不存在即应报错",
        "核对 --root 路径；若只想用配置里的根，去掉 --root",
    ),
    "DISC-003": Rule(
        "DISC-003",
        "技能根下未发现任何技能",
        "HOUSE",
        "本项目收紧：空库通常是配置写错或布局变了",
        "确认该目录下确实有 <技能名>/SKILL.md；必要时调整 max_depth 或 project_roots",
    ),
}


class ConfigError(Exception):
    """hosts.toml 读取/解析/校验失败（信息须可操作）。"""


# --------------------------------------------------------------------------- #
# 配置模型
# --------------------------------------------------------------------------- #


@dataclass
class HostProfile:
    """一个宿主档的完整参数（已合并 defaults）。"""

    name: str
    description: str = ""
    project_roots: list[str] = field(default_factory=list)
    user_roots: list[str] = field(default_factory=list)
    trace_dir: str = ".agents/skillverify"
    max_depth: int = 1

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "project_roots": list(self.project_roots),
            "user_roots": list(self.user_roots),
            "trace_dir": self.trace_dir,
            "max_depth": self.max_depth,
        }


@dataclass
class Config:
    """合并后的有效配置。"""

    defaults: HostProfile
    hosts: dict[str, HostProfile]
    sources: list[str] = field(default_factory=list)

    def names(self) -> list[str]:
        return sorted(self.hosts)

    def profile(self, name: str | None) -> HostProfile:
        key = name or self.defaults.name
        if key not in self.hosts:
            raise ConfigError(
                f"未知宿主档 {key!r}；可用: {', '.join(self.names()) or '（无）'}"
                f"（来源: {', '.join(self.sources)}）"
            )
        return self.hosts[key]

    def to_dict(self) -> dict:
        return {
            "sources": list(self.sources),
            "defaults": self.defaults.to_dict(),
            "hosts": {name: prof.to_dict() for name, prof in sorted(self.hosts.items())},
        }


def builtin_config_path() -> Path:
    """内置配置（随包分发；与代码同源，避免"两份默认值漂移"）。"""
    return Path(__file__).resolve().parent / "data" / "hosts.toml"


def _merge(base: dict, extra: dict, source: str) -> dict:
    """深度合并：表递归合并，其余（含列表）整体替换。"""
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value, source)
        else:
            out[key] = value
    return out


def _read_toml(path: Path) -> dict:
    try:
        import tomllib  # Python 3.11+；刻意延迟导入，使 spec/lint 在旧版本仍可用
    except ModuleNotFoundError as exc:  # pragma: no cover - 取决于运行环境
        raise ConfigError(
            "解析 hosts.toml 需要 Python 3.11+（标准库 tomllib）。"
            "当前解释器过旧；可改用 `skillverify lint <技能目录>` 单独检查。"
        ) from exc
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"配置文件不存在: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"配置文件无法读取: {path}（{exc.strerror or exc}）") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"配置文件 TOML 语法错误: {path}（{exc}）") from exc


def _validate(raw: dict, source: str) -> None:
    section = raw.get("defaults")
    if section is not None and not isinstance(section, dict):
        raise ConfigError(f"{source}: [defaults] 必须是表")
    hosts = raw.get("hosts", {})
    if not isinstance(hosts, dict):
        raise ConfigError(f"{source}: [hosts] 必须是表")
    for name, body in [("defaults", section), *hosts.items()]:
        if body is None:
            continue
        if not isinstance(body, dict):
            raise ConfigError(f"{source}: [hosts.{name}] 必须是表")
        unknown = sorted(set(body) - ALLOWED_KEYS)
        if unknown:
            raise ConfigError(
                f"{source}: [hosts.{name}] 出现未知键 {unknown}；"
                f"允许的键: {sorted(ALLOWED_KEYS)}"
            )
        for key in ("project_roots", "user_roots"):
            value = body.get(key)
            if value is not None and not (isinstance(value, list)
                                          and all(isinstance(v, str) for v in value)):
                raise ConfigError(f"{source}: [hosts.{name}].{key} 必须是字符串数组")
        depth = body.get("max_depth")
        if depth is not None and not (isinstance(depth, int) and not isinstance(depth, bool)
                                      and depth >= 1):
            raise ConfigError(f"{source}: [hosts.{name}].max_depth 必须是 ≥1 的整数")


def _profile_from(name: str, body: dict, defaults: HostProfile) -> HostProfile:
    return HostProfile(
        name=name,
        description=str(body.get("description", defaults.description if name != DEFAULT_PROFILE else "")),
        project_roots=list(body.get("project_roots", defaults.project_roots)),
        user_roots=list(body.get("user_roots", defaults.user_roots)),
        trace_dir=str(body.get("trace_dir", defaults.trace_dir)),
        max_depth=int(body.get("max_depth", defaults.max_depth)),
    )


def user_config_path(user_home: Path) -> Path:
    return user_home / ".agents" / "skillverify" / "hosts.toml"


def project_config_path(project: Path) -> Path:
    return project / ".agents" / "skillverify" / "hosts.toml"


def load_config(
    project: Path,
    user_home: Path,
    extra_files: list[Path] | None = None,
    *,
    use_discovered_files: bool = True,
    builtin: Path | None = None,
) -> Config:
    """按覆盖顺序加载配置：内置 < 用户级 < 项目级 < extra_files（按给定顺序）。"""
    sources: list[Path] = [builtin or builtin_config_path()]
    if use_discovered_files:
        for candidate in (user_config_path(user_home), project_config_path(project)):
            if candidate.is_file():
                sources.append(candidate)
    for extra in extra_files or []:
        sources.append(Path(extra))

    merged: dict = {}
    for path in sources:
        raw = _read_toml(path)
        _validate(raw, str(path))
        merged = _merge(merged, raw, str(path))

    defaults_body = dict(merged.get("defaults", {}))
    defaults = _profile_from(DEFAULT_PROFILE, defaults_body, HostProfile(name=DEFAULT_PROFILE))

    hosts: dict[str, HostProfile] = {DEFAULT_PROFILE: defaults}
    for name, body in (merged.get("hosts") or {}).items():
        hosts[name] = _profile_from(name, body, defaults)

    return Config(defaults=defaults, hosts=hosts, sources=[str(p) for p in sources])


def render_config(config: Config) -> str:
    """把有效配置渲染成 TOML 风格文本（`--show-config` 用；只读展示，不做序列化承诺）。"""
    def emit(name: str, prof: HostProfile) -> list[str]:
        lines = [f"[{'defaults' if name == DEFAULT_PROFILE else f'hosts.{name}'}]"]
        if prof.description:
            lines.append(f'description = "{prof.description}"')
        lines.append("project_roots = [" + ", ".join(f'"{r}"' for r in prof.project_roots) + "]")
        lines.append("user_roots = [" + ", ".join(f'"{r}"' for r in prof.user_roots) + "]")
        lines.append(f'trace_dir = "{prof.trace_dir}"')
        lines.append(f"max_depth = {prof.max_depth}")
        return lines

    out = [f"# 有效配置来源（后者覆盖前者）: {' < '.join(config.sources)}", ""]
    out += emit(DEFAULT_PROFILE, config.defaults)
    out.append("")
    for name, prof in sorted(config.hosts.items()):
        if name == DEFAULT_PROFILE:
            continue
        out += emit(name, prof)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# 发现
# --------------------------------------------------------------------------- #


@dataclass
class RootInfo:
    """一个技能根的命中情况（用于"为什么没发现技能"的诊断）。"""

    label: str
    path: Path
    scope: str  # project / user / explicit
    exists: bool
    found: int = 0
    note: str = ""


@dataclass
class SkillRef:
    """一个被发现的技能。"""

    name: str
    path: Path
    scope: str
    root: str  # 显示用的根标签

    def to_dict(self) -> dict:
        return {"name": self.name, "path": str(self.path), "scope": self.scope, "root": self.root}


@dataclass
class Discovery:
    skills: list[SkillRef] = field(default_factory=list)
    roots: list[RootInfo] = field(default_factory=list)
    results: list[Result] = field(default_factory=list)
    profile: HostProfile | None = None
    trace_dir: Path | None = None

    def to_dict(self) -> dict:
        return {
            "profile": self.profile.to_dict() if self.profile else None,
            "trace_dir": str(self.trace_dir) if self.trace_dir else None,
            "skills": [s.to_dict() for s in self.skills],
            "roots": [
                {"label": r.label, "path": str(r.path), "scope": r.scope,
                 "exists": r.exists, "found": r.found, "note": r.note}
                for r in self.roots
            ],
            "results": [r.to_dict() for r in self.results],
        }

    def to_json(self) -> str:
        import json

        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def _resolve(spec: str, base: Path, *, is_user_root: bool) -> Path:
    """把配置里的路径写法解析成绝对路径：~ 前缀 -> base；绝对路径原样；其余相对 base。"""
    text = spec.strip().replace("\\", "/")
    if text.startswith("~"):
        rest = text[1:].lstrip("/")
        return (base / rest) if rest else base
    path = Path(text)
    if path.is_absolute():
        return path
    return base / path


def _iter_skill_dirs(root: Path, max_depth: int) -> list[Path]:
    """在 root 下按深度上限找含 SKILL.md 的目录；找到即不再向下钻。"""
    found: list[Path] = []
    stack: list[tuple[Path, int]] = [(root, 1)]
    while stack:
        current, depth = stack.pop()
        try:
            children = sorted(current.iterdir())
        except OSError:
            continue
        for child in children:
            try:
                if child.is_symlink() or not child.is_dir():
                    continue
            except OSError:
                continue
            if child.name in SKIP_DIRS:
                continue
            if find_skill_md(child) is not None:
                found.append(child)
                continue
            if depth < max_depth:
                stack.append((child, depth + 1))
    return sorted(found)


def discover_skills(
    profile: HostProfile,
    project: Path,
    user_home: Path,
    *,
    roots: list[str] | None = None,
    trace_dir: Path | None = None,
) -> Discovery:
    """按档参数发现技能。不抛异常（配置错误由 load_config 负责）。"""
    project = project.resolve()
    user_home = user_home.resolve()
    planned: list[tuple[str, Path, str]] = []  # (label, path, scope)

    if roots:
        for spec in roots:
            path = _resolve(spec, project, is_user_root=False)
            planned.append((spec, path, "explicit"))
    else:
        for spec in profile.project_roots:
            planned.append((spec, _resolve(spec, project, is_user_root=False), "project"))
        for spec in profile.user_roots:
            planned.append((spec, _resolve(spec, user_home, is_user_root=True), "user"))

    discovery = Discovery(profile=profile)
    discovery.trace_dir = trace_dir or _resolve(profile.trace_dir, project, is_user_root=False)

    seen_paths: set[Path] = set()
    by_name: dict[str, list[SkillRef]] = {}
    for label, path, scope in planned:
        info = RootInfo(label=label, path=path, scope=scope,
                        exists=path.is_dir())
        if not info.exists:
            info.note = "目录不存在"
            if scope == "explicit":
                discovery.results.append(
                    Result(RULES["DISC-002"].rid, RULES["DISC-002"].title, WARN,
                           RULES["DISC-002"].level, f"--root 指向的目录不存在或不是目录: {label}",
                           RULES["DISC-002"].remediation)
                )
            discovery.roots.append(info)
            continue
        for skill_dir in _iter_skill_dirs(path, profile.max_depth):
            resolved = skill_dir.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            ref = SkillRef(name=skill_dir.name, path=resolved, scope=scope, root=label)
            discovery.skills.append(ref)
            by_name.setdefault(ref.name, []).append(ref)
            info.found += 1
        if info.found == 0:
            info.note = f"未发现 <技能名>/SKILL.md（max_depth={profile.max_depth}）"
        discovery.roots.append(info)

    # 歧义：同名技能出现在多个根（绝不静默覆盖）
    for name, refs in sorted(by_name.items()):
        if len(refs) > 1:
            where = "；".join(f"{r.root}（{r.scope}）" for r in refs)
            discovery.results.append(
                Result(RULES["DISC-001"].rid, RULES["DISC-001"].title, WARN,
                       RULES["DISC-001"].level, f"技能 {name} 出现在 {len(refs)} 处: {where}",
                       RULES["DISC-001"].remediation)
            )

    # 有根但一个技能都没发现：通常是配置写错或布局变了
    if discovery.roots and not discovery.skills:
        existing = [r.label for r in discovery.roots if r.exists]
        if existing:
            discovery.results.append(
                Result(RULES["DISC-003"].rid, RULES["DISC-003"].title, INFO,
                       RULES["DISC-003"].level,
                       f"技能根存在但未发现技能: {', '.join(existing)}",
                       RULES["DISC-003"].remediation)
            )

    discovery.skills.sort(key=lambda s: (s.name, str(s.path)))
    return discovery
