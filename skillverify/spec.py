"""spec —— 官方 Agent Skills 规范校验（对齐 skills-ref 0.1.1 行为）。

**为什么自己实现而不是直接调用官方 CLI**：
本项目要求"装在哪个宿主下都能用"，不能假设目标机器有 Python 包管理器或能联网。
因此官方校验逻辑以纯标准库复刻一份（离线可用），同时提供 `--official` 对账模式
调用官方 `agentskills validate` 做交叉验证。

**复刻依据**（源码级核对，非凭文档臆测）：
- PyPI `skills-ref` 0.1.1 wheel 内 `validator.py` / `entry_points.txt`
- GitHub API 取回的 `tests/test_validator.py`（官方测试用例即规格）
- https://agentskills.io/specification

**刻意保留的"实现比规范文字更宽"之处**（否则会误杀合法技能）：
- `name` 用 `str.isalnum()` 判定，因此**接受任意 Unicode 字母/数字**
  （官方有 i18n 中文/俄文测试背书），并在报告中额外提示 spec 文字口径。
- 比较 name 与目录名之前先 `strip()` + **NFKC 归一化**。
- 官方实现**优先 `SKILL.md`，缺失时接受小写 `skill.md`**。

**短路语义与官方一致**（用于对账时逐条比对）：
路径不存在 → 只报这一条；不是目录 → 只报这一条；缺 SKILL.md → 只报这一条；
frontmatter 解析失败 → 只报解析错误（后续字段检查全不执行）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .encoding import read_text
from .frontmatter import Frontmatter, FrontmatterError, parse_frontmatter
from .report import FAIL, INFO, PASS, SKIP, WARN, Report, Result, Rule, MUST

#: 官方允许的顶层字段（validator.py 的 ALLOWED_FIELDS 逐字复刻）
ALLOWED_FIELDS: frozenset[str] = frozenset(
    {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
)

MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500

_SPEC_URL = "https://agentskills.io/specification"

# --------------------------------------------------------------------------- #
# 规则表
# --------------------------------------------------------------------------- #

RULES: dict[str, Rule] = {
    "SKILL-001": Rule("SKILL-001", "路径存在且为目录", MUST, _SPEC_URL,
                      "传入技能目录（含 SKILL.md 的文件夹）"),
    "SKILL-002": Rule("SKILL-002", "存在 SKILL.md 文件", MUST, _SPEC_URL,
                      "在技能目录下创建 SKILL.md（官方亦接受小写 skill.md）"),
    "SKILL-003": Rule("SKILL-003", "frontmatter 可解析（--- 起止且为合法 YAML 映射）", MUST, _SPEC_URL,
                      "确保文件首行为 ---、有闭合 ---，且内部为 `键: 值` 映射"),
    "SKILL-004": Rule("SKILL-004", "顶层字段白名单（仅允许 6 个官方字段）", MUST,
                      "validator.py ALLOWED_FIELDS",
                      "把自定义字段移入 metadata，或删除；顶层只保留 "
                      "name/description/license/allowed-tools/metadata/compatibility"),
    "SKILL-005": Rule("SKILL-005", "必填字段 name 存在", MUST, _SPEC_URL, "补充 name 字段"),
    "SKILL-006": Rule("SKILL-006", "必填字段 description 存在", MUST, _SPEC_URL,
                      "补充 description 字段（缺失会导致宿主直接跳过该技能）"),
    "SKILL-007": Rule("SKILL-007", f"name 长度 ≤{MAX_NAME}", MUST,
                      "validator.py MAX_SKILL_NAME_LENGTH", f"缩短至 {MAX_NAME} 字符以内"),
    "SKILL-008": Rule("SKILL-008", "name 为小写", MUST, _SPEC_URL, "改为全小写"),
    "SKILL-009": Rule("SKILL-009", "name 不以连字符开头或结尾", MUST, _SPEC_URL,
                      "去掉首尾连字符"),
    "SKILL-010": Rule("SKILL-010", "name 不含连续连字符 --", MUST, _SPEC_URL,
                      "把 -- 改为单个 -"),
    "SKILL-011": Rule("SKILL-011", "name 仅含字母/数字/连字符", MUST, _SPEC_URL,
                      "去掉下划线、空格等非法字符"),
    "SKILL-012": Rule("SKILL-012", "name 与父目录名一致（NFKC 归一化后比较）", MUST, _SPEC_URL,
                      "重命名目录或修改 name 使二者一致"),
    "SKILL-013": Rule("SKILL-013", f"description 长度 ≤{MAX_DESCRIPTION}", MUST,
                      "validator.py MAX_DESCRIPTION_LENGTH", "精简描述"),
    "SKILL-014": Rule("SKILL-014", "description 非空字符串", MUST, _SPEC_URL,
                      "填写描述（空描述会导致宿主跳过该技能）"),
    "SKILL-015": Rule("SKILL-015", f"compatibility 长度 ≤{MAX_COMPATIBILITY}（若存在）", MUST,
                      "validator.py MAX_COMPATIBILITY_LENGTH", "精简兼容性声明"),
    "SKILL-016": Rule("SKILL-016", "compatibility 为字符串（若存在）", MUST, _SPEC_URL,
                      "改为单行字符串"),
    "SPEC-TEXT": Rule("SPEC-TEXT", "name 字符集与 spec 文字口径的差异（仅提示）", INFO,
                      "spec 文字写 a-z0-9-，官方校验器实际接受 Unicode 字母",
                      "若需最大兼容性（部分宿主实现严格），建议改用纯 a-z0-9-"),
}


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #


@dataclass
class SkillDocument:
    """一个技能的解析结果。"""

    directory: Path
    skill_md: Path | None = None
    frontmatter: Frontmatter | None = None
    errors: list[Result] = field(default_factory=list)

    @property
    def name(self) -> str:
        if not self.frontmatter:
            return ""
        value = self.frontmatter.get("name", "")
        return value if isinstance(value, str) else str(value)

    @property
    def description(self) -> str:
        if not self.frontmatter:
            return ""
        value = self.frontmatter.get("description", "")
        return value if isinstance(value, str) else str(value)

    @property
    def body(self) -> str:
        return self.frontmatter.body if self.frontmatter else ""

    @property
    def ok(self) -> bool:
        return not any(e.status == FAIL for e in self.errors)


def find_skill_md(directory: Path) -> Path | None:
    """查找 SKILL.md；官方实现优先大写，缺失时接受小写 skill.md。"""
    for candidate in ("SKILL.md", "skill.md"):
        path = directory / candidate
        if path.is_file():
            return path
    return None


def _fail(rule_id: str, evidence: str) -> Result:
    rule = RULES[rule_id]
    return Result(rule.rid, rule.title, FAIL, rule.level, evidence, rule.remediation)


def _norm(text: str) -> str:
    """与官方一致：先 strip 再 NFKC 归一化。"""
    return unicodedata.normalize("NFKC", text.strip())


def _is_alnum_or_hyphen(char: str) -> bool:
    """官方用 c.isalnum()，因此接受任意 Unicode 字母/数字。"""
    return char.isalnum() or char == "-"


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #


def load_skill(path: Path) -> SkillDocument:
    """加载并解析技能；所有错误以 Result 形式返回，不抛异常。"""
    doc = SkillDocument(directory=path)

    if not path.exists():
        doc.errors.append(_fail("SKILL-001", f"路径不存在: {path}"))
        return doc
    if not path.is_dir():
        doc.errors.append(_fail("SKILL-001", f"不是目录: {path}"))
        return doc

    skill_md = find_skill_md(path)
    if skill_md is None:
        doc.errors.append(_fail("SKILL-002", "技能目录内缺少 SKILL.md"))
        return doc
    doc.skill_md = skill_md

    try:
        text = read_text(skill_md)
        doc.frontmatter = parse_frontmatter(text)
    except FrontmatterError as exc:
        doc.errors.append(_fail("SKILL-003", str(exc)))
        return doc
    except OSError as exc:
        doc.errors.append(_fail("SKILL-003", f"读取失败: {exc}"))
        return doc

    doc.errors.extend(_validate_frontmatter(doc))
    return doc


def _validate_frontmatter(doc: SkillDocument) -> list[Result]:
    """字段级校验；顺序与官方 validator 一致。"""
    fm = doc.frontmatter
    assert fm is not None
    results: list[Result] = []
    data = fm.data

    # 字段白名单
    unexpected = sorted(set(data) - ALLOWED_FIELDS)
    if unexpected:
        allowed = sorted(ALLOWED_FIELDS)
        results.append(
            _fail(
                "SKILL-004",
                f"出现非官方字段: {', '.join(unexpected)}；"
                f"官方仅允许 {allowed}",
            )
        )

    # 必填字段
    if "name" not in data:
        results.append(_fail("SKILL-005", "frontmatter 缺少 name"))
    if "description" not in data:
        results.append(_fail("SKILL-006", "frontmatter 缺少 description"))

    # name 细则
    name_raw = data.get("name")
    if name_raw is not None:
        if not isinstance(name_raw, str) or not name_raw.strip():
            results.append(_fail("SKILL-005", "name 必须是非空字符串"))
        else:
            name = _norm(name_raw)
            if len(name) > MAX_NAME:
                results.append(
                    _fail("SKILL-007", f"name 长度 {len(name)} 超过 {MAX_NAME}: {name!r}")
                )
            if name != name.lower():
                results.append(_fail("SKILL-008", f"name 必须全小写: {name!r}"))
            if name.startswith("-") or name.endswith("-"):
                results.append(_fail("SKILL-009", f"name 不得以连字符开头或结尾: {name!r}"))
            if "--" in name:
                results.append(_fail("SKILL-010", f"name 不得含连续连字符: {name!r}"))
            bad = sorted({ch for ch in name if not _is_alnum_or_hyphen(ch)})
            if bad:
                results.append(
                    _fail(
                        "SKILL-011",
                        f"name 含非法字符 {bad}（仅允许字母/数字/连字符）: {name!r}",
                    )
                )
            if _norm(doc.directory.name) != name:
                results.append(
                    _fail(
                        "SKILL-012",
                        f"目录名 {doc.directory.name!r} 与 name {name!r} 不一致",
                    )
                )
            # spec 文字口径差异提示（INFO，非违规）
            spec_chars = sorted({ch for ch in name if not (ch.isascii() and (ch.isalnum() or ch == "-"))})
            if spec_chars:
                rule = RULES["SPEC-TEXT"]
                results.append(
                    Result(
                        rule.rid,
                        rule.title,
                        INFO,
                        rule.level,
                        f"name 含非 ASCII 字符 {spec_chars}；官方校验器接受（i18n），"
                        f"但 spec 文字口径为 a-z0-9-，严格实现可能拒绝",
                    )
                )

    # description 细则
    desc_raw = data.get("description")
    if desc_raw is not None:
        if not isinstance(desc_raw, str) or not desc_raw.strip():
            results.append(_fail("SKILL-014", "description 必须是非空字符串"))
        elif len(desc_raw) > MAX_DESCRIPTION:
            results.append(
                _fail(
                    "SKILL-013",
                    f"description 长度 {len(desc_raw)} 超过 {MAX_DESCRIPTION}",
                )
            )

    # compatibility 细则
    compat_raw = data.get("compatibility")
    if compat_raw is not None:
        if not isinstance(compat_raw, str):
            results.append(_fail("SKILL-016", "compatibility 必须是字符串"))
        elif len(compat_raw) > MAX_COMPATIBILITY:
            results.append(
                _fail(
                    "SKILL-015",
                    f"compatibility 长度 {len(compat_raw)} 超过 {MAX_COMPATIBILITY}",
                )
            )

    return results


def check_spec(path: Path) -> tuple[SkillDocument, Report]:
    """对单个技能执行官方规范校验，返回（解析结果, 报告）。

    汇总口径：`doc.errors` 里已有的规则用其结果；`SPEC-TEXT` 是提示项，
    未产生记录时直接省略；其余规则若未被执行（前置短路），按前置错误的
    性质记为 SKIP 或 PASS，绝不出现"没报就是过"的错觉。
    """
    doc = load_skill(path)
    report = Report(target=str(path), stage="spec")

    for res in doc.errors:
        report.add(res)
    reported = {res.rid for res in doc.errors}

    # 前置短路：SKILL-001/002/003 任一 FAIL 时，字段级规则根本没跑
    short_circuit = any(
        res.status == FAIL and res.rid in ("SKILL-001", "SKILL-002", "SKILL-003")
        for res in doc.errors
    )

    for rid, rule in RULES.items():
        if rid == "SPEC-TEXT":
            # 仅在确实需要提示时出现，已由 _validate_frontmatter 产生
            continue
        if rid in reported:
            continue
        if short_circuit:
            report.add(Result(rule.rid, rule.title, SKIP, rule.level,
                              "前置检查失败，本项未执行"))
        else:
            report.add_rule(rule, PASS)
    return doc, report


# --------------------------------------------------------------------------- #
# 官方 CLI 对账
# --------------------------------------------------------------------------- #


def find_official_cli() -> str | None:
    """探测官方校验器。命令名以 0.1.1 发布物为准（agentskills），兼容旧名。

    **刻意不写任何宿主专属路径**：旧体系在代码里硬编码了若干宿主目录（71 处），
    一旦换机或换宿主就失效。这里的探测顺序全部与宿主无关：
    1. `SKILLVERIFY_OFFICIAL_CLI` 环境变量（显式指定，最优先）；
    2. PATH 上的命令；
    3. 与本解释器同环境的 Scripts/bin 目录（官方校验器常与该 Python 同装却不在 PATH）。
    """
    override = os.environ.get("SKILLVERIFY_OFFICIAL_CLI", "").strip()
    if override and Path(override).exists():
        return override
    for name in ("agentskills", "skills-ref"):
        found = shutil.which(name)
        if found:
            return found
    exe_dir = Path(sys.executable).resolve().parent
    candidates = [
        exe_dir / "agentskills", exe_dir / "skills-ref",
        exe_dir / "Scripts" / "agentskills.exe", exe_dir / "Scripts" / "skills-ref.exe",
        exe_dir / "Scripts" / "agentskills", exe_dir / "Scripts" / "skills-ref",
        exe_dir.parent / "bin" / "agentskills", exe_dir.parent / "bin" / "skills-ref",
    ]
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return None


def run_official(path: Path, cli: str | None = None) -> Result:
    """调用官方校验器，结果作为一条对账记录（不作为判定依据）。"""
    rule = Rule(
        "SPEC-OFFICIAL",
        "与官方校验器 agentskills validate 对账",
        MUST,
        "PyPI skills-ref 0.1.1",
        "若与本地实现结论不一致，以官方校验器为准并修正本地实现",
    )
    exe = cli or find_official_cli()
    if not exe:
        return Result(rule.rid, rule.title, SKIP, rule.level,
                      "未探测到官方 CLI（可 pip install skills-ref==0.1.1）")
    try:
        proc = subprocess.run(
            [exe, "validate", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Result(rule.rid, rule.title, WARN, rule.level, f"调用失败: {exc}")

    output = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    status = PASS if proc.returncode == 0 else FAIL
    return Result(rule.rid, rule.title, status, rule.level,
                  f"exit={proc.returncode}｜{output.splitlines()[0] if output else '(无输出)'}")
