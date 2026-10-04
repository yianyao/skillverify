#!/usr/bin/env python3
"""dep_check.py — Agent Skill 依赖检测五项（§8.1.2 版本固定 + §8.2.1–§8.2.4 自包含脚本）。

落实《Agent-Skill 生命周期验证方案》W-S 手段表四行（承载方式：独立脚本——
手段全 S 机械可判，沿"一工具一门"惯例；检查项编号 DEP-1~5 为工具本地编号，
V1–V29 已被 V 系列占用，映射关系在各行标题显式标注）：

  DEP-1 [§8.1.2 M] 外部工具调用版本固定：npx/bunx/uvx/pipx/pip/uv/deno/go run
          调用的包规格须带精确版本（pkg@1.2.3 / pkg==1.2.3 / npm:x@1.2.3）；
          代码文件命中 FAIL / SKILL.md（文档口径）命中 WARN
  DEP-2 [§8.2.1 M] 内联依赖声明：scripts/ 捆绑脚本第三方依赖必须内联声明——
          Python PEP 723 "# /// script" 块 / Deno npm:/jsr: 版本化导入 /
          Bun 版本化导入（pkg@1.2.3）/ Ruby bundler/inline；缺失或不完整 FAIL
  DEP-3 [§8.2.2 M] 禁独立 manifest：requirements.txt / package.json / Gemfile /
          go.mod 等在场 → FAIL（pyproject.toml/setup.cfg 常为工具配置 → WARN
          人工甄别）；references/assets 内命中视为示例夹具 → WARN
  DEP-4 [§8.2.3 S] 版本说明符固定：PEP 723 dependencies 裸包名 / npm:/jsr: 范围
          说明符（^ ~ > < *）/ Ruby gem 未钉版本（§8.2.5 P）/ 缺 requires-python
          → WARN（[S] 级，书面说明可放行）
  DEP-5 [§8.2.4 M] 脚本清单完备：scripts/ 实际文件名 ⊆ SKILL.md 列出清单
          （文件名子串在场即认列出），缺列 FAIL；SKILL.md 列出不存在的脚本
          → WARN（清单陈旧提示）

口径声明（机械初筛局限，均写入证据）：
- Ruby 标准库无机械清单——require 非相对路径一律视为 gem 依赖（保守口径，
  误报人工甄别）；Python 用 sys.stdlib_module_names（3.10+）机械判定
- PEP 723 块用正则抽取 dependencies/requires-python（TOML 子集口径，不做全量
  TOML 解析——tomllib 为 3.11+，本项目按 3.10 兼容）
- 运行器扫描为行级词法，代码注释行（# 开头）跳过；docstring（Python 三引号）/
  JS 块注释/示例内命令可能误报，证据带 文件:行号 供人工甄别
- §8.2.6（Gemfile/node_modules 环境干扰）为 [P] 语义项：DEP-3 命中 Gemfile 时
  证据内附带提示，正式判定归人工复测

退出码: 0=全 PASS（SKIP 不计警告，对齐 check_skill A1 口径）；
1=任一 FAIL 或参数错误（阻断）；2=无 FAIL 但有 WARN。
全部参数错误（缺参自查 + argparse 解析错误）统一 exit 1（_BlockArgParser，
撞码纪律全工具对齐）；缺参自查消息含"用法"（V6 冒烟 C2 契约）。

用法:
    python dep_check.py <skill_dir> [--out report.md]

注: 本工具只做机械初筛；运行器与环境匹配（§8.1.5–§8.1.6/V22）、依赖实际可解析
属 O 实测域（M1-9），不在本工具范围。

版本: v1.0.1（2026-10-03 建成 v1.0，同日首轮外部评审 7 条处置——dist-tag 黑名单/
Bun 导入统一 classify_pkg_spec/SKILL.md 缺失计 COV/取值旗标过滤/TOML 单引号，
另修伴生缺陷 pkg@ 尾随空版本 IndexError）
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- 常量表 ----

VERSION = "v1.0.1"

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".verification"}

CODE_EXTS = {
    ".py": "python", ".sh": "shell", ".bash": "shell",
    ".js": "js", ".mjs": "js", ".cjs": "js", ".ts": "js", ".tsx": "js", ".jsx": "js",
    ".rb": "ruby",
}

# manifest 判级：出现即违背 §8.2.2（FAIL）；pyproject.toml/setupcfg 常为工具
# 配置（pytest/ruff 等）→ WARN 人工甄别
MANIFEST_FAIL = {
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "requirements.txt", "pipfile", "pipfile.lock", "uv.lock",
    "gemfile", "gemfile.lock", "go.mod", "cargo.toml",
}
MANIFEST_WARN = {"pyproject.toml", "setup.cfg"}

PEP723_START_RE = re.compile(r"^\s*#\s*///\s*script\s*$", re.M)
PEP723_END_RE = re.compile(r"^\s*#\s*///\s*$", re.M)
PEP723_DEPS_RE = re.compile(r"dependencies\s*=\s*\[(.*?)\]", re.S)
PEP723_DEP_ITEM_RE = re.compile(r"['\"]([^'\"]+)['\"]")   # TOML 允许单/双引号（评审 v1.0.1⑥）
PEP723_PY_RE = re.compile(r"requires-python\s*=\s*['\"]([^'\"]*)['\"]")
PY_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)")
JS_SPEC_RE = re.compile(
    r"""(?:from|import|require\s*\(|import\s*\()\s*["']([^"']+)["']""")
RUBY_REQUIRE_RE = re.compile(r'^\s*require\s+["\']([^"\']+)["\']', re.M)
RUBY_GEM_RE = re.compile(
    r'^\s*gem\s+["\']([^"\']+)["\']\s*(?:,\s*["\']([^"\']*)["\'])?', re.M)

# 运行器调用（DEP-1）：词级匹配 + 行内取其后首个非旗标 token
RUNNER_WORD_RE = re.compile(r"\b(npx|bunx|uvx|pipx)\b")
RUNNER_PIP_RE = re.compile(r"\b(pip3?)\s+install\b")
RUNNER_UV_RE = re.compile(r"\buv\s+(?:pip\s+install|tool\s+run|run\s+--with)\b")
RUNNER_DENO_RE = re.compile(r"\bdeno\s+(?:run|install)\b")
RUNNER_GO_RE = re.compile(r"\bgo\s+run\b")

# npm dist-tag：非精确版本，随发布漂移（评审 v1.0.1①——latest 恰是"永远漂移"
# 的典型违背，pkg@latest 不得判 pinned）
DIST_TAGS = {"latest", "next", "beta", "canary", "rc", "alpha", "dev"}


# ---------------------------------------------------------------- 基础设施 ----

def classify_pkg_spec(spec: str) -> tuple[str, str]:
    """包规格判级。返回 ('pinned'|'ranged'|'unpinned', 说明)。
    口径：== 与精确 @版本 为固定；^ ~ > < * 范围说明符与 npm dist-tag
    （latest/next/beta 等随发布漂移）为 ranged（§8.2.3 WARN）；
    无版本为 unpinned（§8.1.2/§8.2.1 域）。"""
    s = spec.strip().strip("`\"',")
    if s.startswith(("npm:", "jsr:")):
        rest = s[4:]
        if rest.startswith("@"):  # 作用域包 @scope/name@ver
            slash = rest.find("/")
            if slash < 0:
                return "unpinned", "npm:/jsr: 作用域包缺版本"
            rest = rest[slash + 1:]
        if "@" in rest:
            ver = rest.rsplit("@", 1)[1]
            if not ver:
                return "unpinned", "npm:/jsr: 尾随 @ 缺版本号"
            if ver[0] in "^~>*<" or ver == "*":
                return "ranged", f"范围说明符 {ver} 非精确固定"
            if ver.lower() in DIST_TAGS:
                return "ranged", f"dist-tag {ver} 非精确版本（随发布漂移）"
            return "pinned", ver
        return "unpinned", "npm:/jsr: 导入未带版本"
    m = re.match(r"^([A-Za-z0-9._-]+)(\[[^\]]*\])?(.*)$", s)
    if m and m.group(3) and m.group(3)[0] in "=<>!~":
        rest = m.group(3).split(";")[0]
        if rest.startswith("=="):
            return "pinned", rest
        return "ranged", f"版本说明符 {rest} 非精确固定（== 为固定口径）"
    at = s.rfind("@")
    if at > 0 and "/" not in s[at + 1:]:  # npm 风格 name@ver / @scope/pkg@ver
        ver = s[at + 1:]
        if not ver:
            return "unpinned", "尾随 @ 缺版本号"
        if ver[0] in "^~>*<" or ver == "*":
            return "ranged", f"范围说明符 {ver} 非精确固定"
        if ver.lower() in DIST_TAGS:
            return "ranged", f"dist-tag {ver} 非精确版本（随发布漂移）"
        return "pinned", ver
    return "unpinned", "包规格未带版本"


def scan_runners(text: str, where: str) -> list[tuple[str, int, str, str]]:
    """行级扫描运行器调用。返回 (位置, 行号, 命令, 包规格) 列表。
    注释行（# 开头）跳过；docstring/示例内命令可能误报（证据带行号人工甄别）。"""
    found: list[tuple[str, int, str, str]] = []

    # 取值旗标：其后 token 是旗标的值（文件名/包名/路径），不是被调用对象——
    # pip -r/--requirement/-c/--constraint（-r 后的 requirements.txt 不得当包名，
    # manifest 口径归 DEP-3）、npx/bunx -p/--package、-e/--editable、-i/--index-url
    # 等须连同其值一并跳过（评审 v1.0.1④）
    VALUE_FLAGS = {"-r", "--requirement", "-c", "--constraint", "-e", "--editable",
                   "-i", "--index-url", "--extra-index-url", "-t", "--target",
                   "--prefix", "-p", "--package"}

    def first_spec(toks: list[str], pred=lambda t: not t.startswith("-")):
        skip_next = False
        for t in toks:
            if skip_next:
                skip_next = False
                continue
            if t.lower() in VALUE_FLAGS:
                skip_next = True
                continue
            if pred(t):
                return t
        return None

    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for m in RUNNER_WORD_RE.finditer(line):
            spec = first_spec(line[m.end():].split())
            if spec:
                found.append((where, i, m.group(1), spec))
        for m in RUNNER_PIP_RE.finditer(line):
            spec = first_spec(line[m.end():].split())
            if spec:
                found.append((where, i, m.group(1), spec))
        for m in RUNNER_UV_RE.finditer(line):
            spec = first_spec(line[m.end():].split())
            if spec:
                found.append((where, i, "uv", spec))
        for m in RUNNER_DENO_RE.finditer(line):
            spec = first_spec(line[m.end():].split(),
                              lambda t: t.startswith(("npm:", "jsr:")))
            if spec:
                found.append((where, i, "deno", spec))
        m = RUNNER_GO_RE.search(line)
        if m:
            spec = first_spec(line[m.end():].split())
            # go run 本地形态（main.go / ./pkg/ / .）不涉外部版本固定
            if spec and not (spec.endswith(".go") or spec.startswith(("./", "../", "/"))
                             or spec in (".", "..")):
                found.append((where, i, "go run", spec))
    return found


def extract_pep723(text: str) -> tuple[list[str], str | None]:
    """抽取 PEP 723 "# /// script" 块（TOML 子集口径）。返回 (dependencies, requires-python)。"""
    start = PEP723_START_RE.search(text)
    if not start:
        return [], None
    buf: list[str] = []
    for ln in text[start.end():].splitlines():
        if PEP723_END_RE.match(ln):
            break
        buf.append(ln)
    block = "\n".join(buf)
    # 剥行首注释符（"# key = val" → "key = val"）再抽取
    block = re.sub(r"^\s*#\s?", "", block, flags=re.M)
    deps_m = PEP723_DEPS_RE.search(block)
    deps = PEP723_DEP_ITEM_RE.findall(deps_m.group(1)) if deps_m else []
    py_m = PEP723_PY_RE.search(block)
    return deps, (py_m.group(1) if py_m else None)


def norm_dep_name(dep: str) -> str:
    """PEP 508 依赖规格 → 归一化顶层包名（PEP 503：[-_.]+ → -，lower）。"""
    name = re.split(r"[<>=!~;\[\s]", dep.strip(), 1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def python_third_party(text: str, scripts_dir: Path) -> list[str]:
    """Python 第三方顶层导入模块（stdlib 机械判定 + scripts 目录内本地模块豁免）。"""
    mods: set[str] = set()
    for ln in text.splitlines():
        if ln.lstrip().startswith("#"):
            continue
        m = PY_IMPORT_RE.match(ln)
        if m:
            mods.add(m.group(1))
    third: list[str] = []
    for mod in sorted(mods):
        if mod in sys.stdlib_module_names:
            continue
        if (scripts_dir / f"{mod}.py").is_file() or (scripts_dir / mod).is_dir():
            continue
        third.append(mod)
    return third


def js_specifiers(text: str) -> list[str]:
    """JS/TS 导入说明符去重列表（import/from/require/动态 import）。"""
    seen: list[str] = []
    for m in JS_SPEC_RE.finditer(text):
        spec = m.group(1)
        if spec not in seen:
            seen.append(spec)
    return seen


def iter_code_files(scripts_dir: Path) -> tuple[list[tuple[Path, str, str]], list[str]]:
    """遍历 scripts/ 代码文件。返回 [(路径, 语言, 文本)], 读取失败列表。"""
    out: list[tuple[Path, str, str]] = []
    errors: list[str] = []
    if not scripts_dir.is_dir():
        return out, errors
    for p in sorted(scripts_dir.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(scripts_dir).parts):
            continue
        lang = CODE_EXTS.get(p.suffix.lower())
        if not lang:
            continue
        try:
            out.append((p, lang, p.read_text(encoding="utf-8", errors="replace")))
        except OSError as e:
            errors.append(f"{p.relative_to(scripts_dir)}（{e.strerror or e}）")
    return out, errors


# ---------------------------------------------------------------- 检查主体 ----

def dep_check(skill_dir: Path) -> tuple[list[dict], dict]:
    """返回 (报告行, 统计)。行: dict(vid,title,level,ev)。"""
    rows: list[dict] = []
    n_read_err = 0
    read_err_files: list[str] = []

    def add(vid: str, title: str, level: str, ev: str) -> None:
        rows.append(dict(vid=vid, title=title, level=level, ev=ev))

    skill_md = skill_dir / "SKILL.md"
    scripts_dir = skill_dir / "scripts"

    md_text: str | None = None
    if skill_md.is_file():
        try:
            md_text = skill_md.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            n_read_err += 1
            read_err_files.append(f"SKILL.md（{e.strerror or e}）")
    else:
        n_read_err += 1
        read_err_files.append("SKILL.md（缺失）")

    code_files, code_errs = iter_code_files(scripts_dir)
    read_err_files.extend(f"scripts/{e}" for e in code_errs)
    n_read_err += len(code_errs)

    # ---- DEP-1 外部工具调用版本固定（§8.1.2）----
    usages = scan_runners(md_text, "SKILL.md") if md_text else []
    for p, _lang, text in code_files:
        usages += scan_runners(text, f"scripts/{p.relative_to(scripts_dir).as_posix()}")
    if not usages:
        add("DEP-1", "外部工具调用版本固定（pkg@1.2.3，§8.1.2）", "SKIP",
            "未发现运行器/包管理调用（npx/bunx/uvx/pipx/pip/uv/deno/go run）——条款不适用")
    else:
        fails: list[str] = []
        warns: list[str] = []
        for where, ln, cmd, spec in usages:
            state, detail = classify_pkg_spec(spec)
            if state == "pinned":
                continue
            item = f"{where}:{ln} {cmd} {spec}（{detail}）"
            if state == "ranged":
                warns.append(item)
            elif where == "SKILL.md":
                warns.append(item + "［文档口径 WARN］")
            else:
                fails.append(item)
        if fails:
            ev = ("; ".join(fails[:5]) + (f"（另 {len(fails) - 5} 处略）" if len(fails) > 5 else "")
                  + "——外部工具未固定版本，命令随时间行为不一致")
            if warns:
                ev += "；WARN 并列: " + "; ".join(warns[:3]) \
                    + (f"（另 {len(warns) - 3} 处略）" if len(warns) > 3 else "")
            add("DEP-1", "外部工具调用版本固定（pkg@1.2.3，§8.1.2）", "FAIL", ev)
        elif warns:
            add("DEP-1", "外部工具调用版本固定（pkg@1.2.3，§8.1.2）", "WARN",
                "; ".join(warns[:5]) + (f"（另 {len(warns) - 5} 处略）" if len(warns) > 5 else ""))
        else:
            add("DEP-1", "外部工具调用版本固定（pkg@1.2.3，§8.1.2）", "PASS",
                f"{len(usages)} 处运行器/包管理调用全部带精确版本")

    # ---- DEP-2 / DEP-4 内联依赖声明与版本说明符（§8.2.1 / §8.2.3+§8.2.5）----
    dep2_fails: list[str] = []
    dep4_warns: list[str] = []
    pep723_seen = False
    js_declared = 0
    ruby_gems = 0
    for p, lang, text in code_files:
        rel = f"scripts/{p.relative_to(scripts_dir).as_posix()}"
        if lang == "python":
            third = python_third_party(text, scripts_dir)
            deps, req_py = extract_pep723(text)
            if deps or req_py is not None:
                pep723_seen = True
            declared = {norm_dep_name(d) for d in deps}
            if third and not deps:
                dep2_fails.append(
                    f"{rel}: 第三方导入 {', '.join(third)} 无 PEP 723 '# /// script' 内联声明")
            elif third:
                undeclared = [t for t in third
                              if re.sub(r"[-_.]+", "-", t).lower() not in declared]
                if undeclared:
                    dep2_fails.append(
                        f"{rel}: 第三方导入 {', '.join(undeclared)} 未入内联 dependencies")
            for d in deps:
                name = re.split(r"[<>=!~;\[\s]", d.strip(), 1)[0]
                rest = d.strip()[len(name):].split(";")[0].strip()
                if not rest:
                    dep4_warns.append(f"{rel}: PEP 723 依赖 {name} 无版本说明符（§8.2.3）")
            if (deps or third) and req_py is None:
                dep4_warns.append(f"{rel}: PEP 723 块缺 requires-python（§8.2.3）")
        elif lang == "js":
            for spec in js_specifiers(text):
                if spec.startswith(("node:", "bun:", "data:", "http:", "https:",
                                    "./", "../", "/")):
                    continue
                if spec.startswith(("npm:", "jsr:")):
                    js_declared += 1
                    state, detail = classify_pkg_spec(spec)
                    if state == "unpinned":
                        dep2_fails.append(f"{rel}: {spec}（{detail}）——单命令不可运行")
                    elif state == "ranged":
                        dep4_warns.append(f"{rel}: {spec}（{detail}）")
                else:
                    # Bun 版本化导入与 npm:/jsr: 分支统一判据（classify_pkg_spec）——
                    # pkg@latest / pkg@^1.0.0 不再静默计入声明（评审 v1.0.1②：
                    # 同一版本语义须同一判定，ranged → DEP-4 WARN）
                    state, detail = classify_pkg_spec(spec)
                    if state == "unpinned":
                        dep2_fails.append(
                            f"{rel}: 裸导入 \"{spec}\" 无内联版本声明"
                            "（Deno 须 npm:/jsr: 带版本，Bun 须 pkg@ver）")
                    else:
                        js_declared += 1
                        if state == "ranged":
                            dep4_warns.append(f"{rel}: Bun 导入 {spec}（{detail}）")
        elif lang == "ruby":
            requires = RUBY_REQUIRE_RE.findall(text)
            gems = RUBY_GEM_RE.findall(text)
            ruby_gems += len(gems)
            inline = any("bundler/inline" in r for r in requires)
            gem_reqs = [r for r in requires
                        if not r.startswith(".") and r != "bundler/inline"]
            if gem_reqs and not inline:
                dep2_fails.append(
                    f"{rel}: require {', '.join(gem_reqs[:3])} 无 bundler/inline 内联声明"
                    "（Ruby 标准库无机械清单，非相对 require 一律按 gem 依赖保守口径）")
            for name, ver in gems:
                if not ver:
                    dep4_warns.append(f"{rel}: gem {name} 未钉版本（§8.2.5 [P]——"
                                      "bundler/inline 无 lockfile 须显式钉版本）")
    if not code_files:
        add("DEP-2", "捆绑脚本内联依赖声明（§8.2.1）", "SKIP",
            "scripts/ 无代码文件——内联声明条款不适用" +
            ("（读取失败 " + "; ".join(code_errs[:3]) + "）" if code_errs else ""))
    elif dep2_fails:
        add("DEP-2", "捆绑脚本内联依赖声明（§8.2.1）", "FAIL",
            "; ".join(dep2_fails[:5]) + (f"（另 {len(dep2_fails) - 5} 处略）"
                                         if len(dep2_fails) > 5 else "")
            + "——捆绑脚本须内联声明依赖，agent 单命令即可运行")
    else:
        add("DEP-2", "捆绑脚本内联依赖声明（§8.2.1）", "PASS",
            f"{len(code_files)} 个代码文件第三方依赖均已内联声明或无第三方依赖")
    if not pep723_seen and not js_declared and not ruby_gems and not dep4_warns:
        add("DEP-4", "依赖版本说明符固定（§8.2.3/§8.2.5）", "SKIP",
            "无内联依赖声明可核（无 PEP 723 块/Deno-Bun 版本化导入/gem 声明）——条款不适用")
    elif dep4_warns:
        add("DEP-4", "依赖版本说明符固定（§8.2.3/§8.2.5）", "WARN",
            "; ".join(dep4_warns[:5]) + (f"（另 {len(dep4_warns) - 5} 处略）"
                                         if len(dep4_warns) > 5 else "")
            + "——[S] 级：精确固定（== / @1.2.3）保证可复现，书面说明后可放行")
    else:
        add("DEP-4", "依赖版本说明符固定（§8.2.3/§8.2.5）", "PASS",
            "内联依赖版本说明符全部精确固定（含 requires-python）")

    # ---- DEP-3 禁独立 manifest（§8.2.2）----
    m_fails: list[str] = []
    m_warns: list[str] = []
    if skill_dir.is_dir():
        for p in sorted(skill_dir.rglob("*")):
            if not p.is_file() or p.is_symlink():
                continue
            rel_parts = p.relative_to(skill_dir).parts
            if any(part in SKIP_DIRS for part in rel_parts):
                continue
            name = p.name.lower()
            soft = name in MANIFEST_WARN
            hit = soft or name in MANIFEST_FAIL
            if not hit:
                continue
            rel = p.relative_to(skill_dir).as_posix()
            if rel_parts[0] in ("references", "assets"):
                m_warns.append(f"{rel}（示例/夹具口径，人工确认）")
            elif soft:
                m_warns.append(f"{rel}（pyproject/setupcfg 常为工具配置——人工甄别；"
                               "若为运行 manifest 则违背 §8.2.2）")
            else:
                m_fails.append(rel)
                if name in ("gemfile", "gemfile.lock"):
                    m_fails[-1] += ("（§8.2.6：Gemfile 在场时 bundler/inline 机制可能失效，"
                                    "须真实挂载环境复测）")
    if m_fails:
        ev = "; ".join(m_fails[:5]) + "——捆绑脚本不得要求单独 manifest 或安装步骤"
        if m_warns:
            ev += "；WARN 并列: " + "; ".join(m_warns[:3])
        add("DEP-3", "禁独立 manifest / 安装步骤（§8.2.2）", "FAIL", ev)
    elif m_warns:
        add("DEP-3", "禁独立 manifest / 安装步骤（§8.2.2）", "WARN",
            "; ".join(m_warns[:5]) + "——须人工判定是否属运行依赖")
    else:
        add("DEP-3", "禁独立 manifest / 安装步骤（§8.2.2）", "PASS",
            "技能树内未发现独立依赖 manifest")

    # ---- DEP-5 脚本清单完备（§8.2.4）----
    if not scripts_dir.is_dir():
        add("DEP-5", "脚本清单完备（scripts/ 实际文件 ⊆ SKILL.md 清单，§8.2.4）", "SKIP",
            "无 scripts/ 目录——条款不适用")
    elif md_text is None:
        add("DEP-5", "脚本清单完备（scripts/ 实际文件 ⊆ SKILL.md 清单，§8.2.4）", "FAIL",
            "SKILL.md 缺失或不可读——清单比对不可验（A 门亦会 FAIL）")
    else:
        actual = [p.relative_to(scripts_dir).as_posix()
                  for p in sorted(scripts_dir.rglob("*"))
                  if p.is_file() and not p.is_symlink()
                  and not any(part in SKIP_DIRS
                              for part in p.relative_to(scripts_dir).parts)]
        unlisted = [a for a in actual
                    if Path(a).name not in md_text and a not in md_text]
        mentioned = {Path(m).name for m in re.findall(r"scripts/[\w./-]+", md_text)}
        stale = sorted(mentioned - {Path(a).name for a in actual})
        if unlisted:
            add("DEP-5", "脚本清单完备（scripts/ 实际文件 ⊆ SKILL.md 清单，§8.2.4）", "FAIL",
                f"未列入 SKILL.md: {', '.join(unlisted[:5])}"
                + (f"（另 {len(unlisted) - 5} 个略）" if len(unlisted) > 5 else "")
                + "——SKILL.md 须列出全部脚本及用途与调用方式")
        else:
            add("DEP-5", "脚本清单完备（scripts/ 实际文件 ⊆ SKILL.md 清单，§8.2.4）", "PASS",
                f"scripts/ {len(actual)} 个文件全部在 SKILL.md 列出"
                + ("；'用途与调用方式'语义归 H" if actual else ""))
        if stale:
            add("DEP-5", "脚本清单完备（scripts/ 实际文件 ⊆ SKILL.md 清单，§8.2.4）", "WARN",
                f"SKILL.md 提及但不存在: {', '.join(stale[:5])}——清单陈旧或调用示例中的"
                "占位脚本路径（如 scripts/foo.py 示例行），须人工甄别")

    # ---- COV 覆盖行 + 覆盖不全降级 ----
    cov_parts = ["DEP-1/2/3/4/5 SKILL.md+scripts/+技能树 manifest"]
    if read_err_files:
        cov_parts.append("读取失败 " + "; ".join(read_err_files[:3]) +
                         ("（覆盖不全，PASS 行已同步降 WARN）" if n_read_err else ""))
    add("COV", "扫描覆盖", "WARN" if n_read_err else "INFO", "; ".join(cov_parts))

    if n_read_err:
        for r in rows:
            if r["level"] == "PASS":
                r["level"] = "WARN"
                r["ev"] += f"（WARN 缘由: {n_read_err} 个文件读取失败，覆盖不全）"

    stats = dict(read_err=n_read_err,
                 skips=sum(1 for r in rows if r["level"] == "SKIP"))
    return rows, stats


# ---------------------------------------------------------------- 报告与入口 ----

class _BlockArgParser(argparse.ArgumentParser):
    """参数错误统一 exit 1（阻断码）——argparse 默认 exit 2 撞 WARN 码
    （撞码纪律全工具对齐，v1.0.3 error() 覆写口径）。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"错误: {message}。下一步: 按用法核对参数后重试。", file=sys.stderr)
        raise SystemExit(1)


_ORDER = {"DEP-1": 1, "DEP-2": 2, "DEP-3": 3, "DEP-4": 4, "DEP-5": 5, "COV": 50}


def build_report(skill_dir: Path, rows: list[dict], stats: dict) -> str:
    has_fail = any(r["level"] == "FAIL" for r in rows)
    has_warn = any(r["level"] == "WARN" for r in rows)
    judged = [r for r in rows if r["level"] in ("PASS", "FAIL")]
    skips = sum(1 for r in rows if r["level"] == "SKIP")
    lines = [
        "# 依赖检测五项报告（dep_check.py）",
        "",
        f"- 技能: {skill_dir.name}（{skill_dir}）",
        f"- 工具版本: {VERSION}",
        "- 口径: §8.1.2 版本固定（[M]）/§8.2.1 内联声明（[M]）/§8.2.2 禁 manifest（[M]）"
        "/§8.2.3+§8.2.5 版本说明符（[S]/[P]）/§8.2.4 脚本清单完备（[M]）；"
        "SKIP 不计警告（须人工留痕佐证，不豁免上游条款）",
        f"- 总结论: {'FAIL（存在阻断项）' if has_fail else ('WARN（需人工复核）' if has_warn else 'PASS')}"
        + (f"（SKIP {skips} 行）" if skips else ""),
        "",
        "| 项 | 检查内容 | 结论 | 证据 |",
        "|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: (_ORDER.get(r["vid"], 99), r["vid"])):
        lines.append(f"| {r['vid']} | {r['title']} | {r['level']} | {r['ev']} |")
    lines += [
        "",
        f"> 判定统计: {sum(1 for r in judged if r['level'] == 'PASS')}/{len(judged)} PASS。"
        "运行器与环境匹配（§8.1.5–§8.1.6/V22）与依赖实际可解析属 O 实测域（M1-9），"
        "不在本工具范围；§8.2.6 环境干扰（Gemfile/node_modules 在场时自包含机制可能失效）"
        "须真实挂载环境复测。",
    ]
    if has_fail:
        lines[-1] += " [M] FAIL 阻断：先处置再进入下一阶段。"
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = _BlockArgParser(
        description="Agent Skill 依赖检测五项（§8.1.2 版本固定 / §8.2.1–§8.2.4 自包含脚本）")
    ap.add_argument("skill_dir", nargs="?", help="待检技能目录（含 SKILL.md 与 scripts/）")
    ap.add_argument("--out", help="报告落盘路径（建议 .verification/m1-s/dep-check.md）")
    a = ap.parse_args()

    if not a.skill_dir:
        print("错误: 缺技能目录参数。用法: python dep_check.py <skill_dir> [--out report.md]。",
              file=sys.stderr)
        return 1

    skill_dir = Path(a.skill_dir)
    if not skill_dir.is_dir():
        print(f"错误: 目录不存在: {skill_dir}。下一步: 核对路径后重试。", file=sys.stderr)
        return 1

    rows, stats = dep_check(skill_dir)
    report = build_report(skill_dir, rows, stats)
    print(report)

    if a.out:
        outp = Path(a.out)
        try:
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text(report, encoding="utf-8", newline="\n")
            print(f"[已落盘] {outp}")
        except OSError as e:
            print(f"[FAIL] 报告落盘失败: {outp} — {e}。下一步: 检查路径权限或改用其他 --out 路径。",
                  file=sys.stderr)
            return 1

    has_fail = any(r["level"] == "FAIL" for r in rows)
    has_warn = any(r["level"] == "WARN" for r in rows)
    return 1 if has_fail else (2 if has_warn else 0)


if __name__ == "__main__":
    sys.exit(main())
