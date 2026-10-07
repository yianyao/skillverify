"""自检套件：死代码与过期措辞。

**为什么单独立一套**：这两件事原本是我每轮收尾手工扫的（AST 找未用 import/函数、正则找
"待实现/后续版本"这类过期话术）。手工扫描漏过一次——`material.MaterialBundle` 是**类**，
我的扫描只覆盖 import/函数/常量，于是它一直躺在代码里，直到外部评审指出。
凡是"每轮都要做、且已经漏过一次"的检查，就该进套件。

覆盖：
- 未使用的导入（`import x` / `from x import y` 之后没人用）
- 未使用的模块级函数与**类**
- 未使用的模块级常量（全大写）
- 过期措辞（TODO / FIXME / 后续版本 / 待实现 / 暂未实现）出现在非注释代码里

误报防护：只看模块顶层定义；名字出现在任意 Name / Attribute / 字符串常量里都算"被用到"
（因此 `getattr(mod, "name")`、`__all__ = ["Name"]`、f-string 里的 `{Name}` 都不会被误判）。
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skillverify.encoding import force_utf8_stdio  # noqa: E402
from skillverify.tmpdir import TEMP_DIR_MODE, temp_dir  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

#: 扫描范围（交付物本体 + 测试）
TREES = ("skillverify", "tests")

#: 过期措辞：功能早已实现、话术却还停在"以后会做"的状态
STALE_RE = re.compile(r"TODO|FIXME|后续版本|待实现|暂未实现|尚未实现")

#: 明令禁止的 API：临时目录必须走 `tmpdir.py`。
#: 理由见 `skillverify/tmpdir.py` 的模块说明——`tempfile.mkdtemp`/`TemporaryDirectory`
#: 按 `mode=0o700` 建目录，Windows 沙箱（AppContainer）的访问检查要求 DACL 同时授予
#: 用户 SID 与容器 SID，于是**创建者自己也进不去**（WinError 5）；而在普通终端里跑
#: 永远复现不了，正是本项目最忌讳的"本机通过、换个环境就崩"。
FORBIDDEN_ATTRS = {"mkdtemp", "TemporaryDirectory"}

_passed: list[str] = []
_failed: list[str] = []


def ok(msg: str) -> None:
    _passed.append(msg)
    print(f"  PASS {msg}")


def fail(msg: str) -> None:
    _failed.append(msg)
    print(f"  FAIL {msg}")


def check(cond: bool, msg: str) -> None:
    ok(msg) if cond else fail(msg)


def source_files() -> list[Path]:
    files: list[Path] = []
    for tree in TREES:
        files.extend(p for p in (REPO / tree).rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(files)


def imported_names(tree: ast.AST) -> dict[str, int]:
    """模块级导入进来的名字 -> 行号。"""
    found: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "*":
                    continue
                found[alias.asname or alias.name.split(".")[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in ("*", "annotations"):
                    continue
                found[alias.asname or alias.name] = node.lineno
    return found


def _exported_only_ids(tree: ast.AST) -> set[int]:
    """`__all__ = [...]` 列表里那些字符串常量的 id。

    **它们不算「被使用」**：`__all__` 声明的是「我导出这个」，不是「有人用了它」。
    早先没排除，于是**死类**只要写进 `__all__` 就永远抓不到——而这套自检本来就是
    「因为手工扫描漏了类」才诞生的（外部评审正是这样发现了它）。
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            for element in getattr(node.value, "elts", []):
                ids.add(id(element))
    return ids


def used_names(tree: ast.AST, *, include_imports: bool = False,
               include_strings: bool = True) -> set[str]:
    """所有"被提到"的名字。

    字符串常量整个加入（不做分词）：这样 `__all__ = ["Foo"]`、`getattr(m, "Foo")`、
    f-string 片段都能算用到——宁可漏报死代码，也不要误报活代码。
    """
    exported = _exported_only_ids(tree)
    used: set[str] = set()
    for node in ast.walk(tree):
        # import 语句算不算「用到」——两个用途口径相反：
        # 查死**导入**时不算（否则 `from m import INFO` 自己这行就把 INFO 标记成已使用）；
        # 查死**定义**时算（别处 `from ..mount import load as x` 就是有人用了它）。
        if include_imports and isinstance(node, ast.Import):
            for alias in node.names:
                used.add(alias.name.split(".")[0])
        elif include_imports and isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    used.add(alias.name)
        elif isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif include_strings and isinstance(node, ast.Constant) \
                and isinstance(node.value, str) and id(node) not in exported:
            used.add(node.value)
            for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", node.value):
                used.add(word)
    return used


def collect(all_trees: dict[Path, ast.AST]) -> tuple[list[str], list[str], list[str]]:
    """返回 (未用导入, 未用定义, 过期措辞)。

    判定口径：
    - **导入**：只看**本文件**有没有用到它（跨文件同名不算"用到这个导入"）；
      `__all__`/字符串里的名字算用到（re-export 场景不会被误报）。
    - **模块级函数/类/常量**：在全仓语料里搜名字，出现次数 ≤1（只有定义那一处）才算死。
    """
    referenced: set[str] = set()
    for path, tree in all_trees.items():
        # 扫描器**自己的文字**不算引用（代码引用照算）：否则只要在说明里写一句
        # 「某某类已经没人用了」，那个类就会被自己的说明文字"证明"成在用
        # ——真实案例：一个死 dataclass 就这样躲过了一轮扫描。
        referenced |= used_names(tree, include_imports=True,
                                 include_strings=path.name != "test_selfcheck.py")

    dead_imports: list[str] = []
    dead_defs: list[str] = []
    stale: list[str] = []
    for path, tree in all_trees.items():
        try:
            rel = path.relative_to(REPO).as_posix()
        except ValueError:          # 反向自检用的临时探针在仓库外
            rel = path.name
        own_used = used_names(tree)
        for name, lineno in imported_names(tree).items():
            if name not in own_used:
                dead_imports.append(f"{rel}:{lineno} 未使用的导入 {name}")
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name.startswith("__") or node.name in own_used:
                    continue
                if node.name.startswith("__") or node.name in referenced:
                    continue
                kind = "类" if isinstance(node, ast.ClassDef) else "函数"
                dead_defs.append(f"{rel}:{node.lineno} 未被引用的{kind} {node.name}")
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper() \
                            and target.id not in referenced:
                        dead_defs.append(f"{rel}:{node.lineno} 未使用的常量 {target.id}")
        # 本文件自己必然包含这些关键词（模式定义与说明），跳过它，否则自检永远红
        if path.name == "test_selfcheck.py":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if STALE_RE.search(line):
                stale.append(f"{rel}:{lineno} {stripped[:80]}")
    return dead_imports, dead_defs, stale


def forbidden_tempfile_calls(tree: ast.AST) -> list[int]:
    """返回使用 `tempfile.mkdtemp` / `tempfile.TemporaryDirectory` 的行号。

    只看 **AST**（属性访问与 from-import），不看文本：`tmpdir.py` 的模块说明里必须写出
    这两个名字（说清为什么不用它们），文本扫描会把它自己判红——这是本项目在自检里
    踩过好几次的坑（"扫描器自己的文字不算引用"）。
    """
    hits: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
            base = node.value
            if isinstance(base, ast.Name) and base.id == "tempfile":
                hits.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module == "tempfile":
            for alias in node.names:
                if alias.name in FORBIDDEN_ATTRS:
                    hits.append(node.lineno)
    return sorted(hits)


def undefined_names(tree: ast.AST) -> list[str]:
    """Load 语境里**从未被绑定过**的名字（= 用了没定义/没导入）。

    为什么需要：本仓库唯一的实锤缺陷就是这一类——`mount.py` 的 `except ConfigError`
    从未导入 `ConfigError`，于是 CLI 敲错宿主档名时，异常处理子句自己抛 `NameError`，
    用户看到一大段 traceback，而不是那句早已写好的"未知宿主档…可用：…"。
    现有自检只查死代码与过期措辞，**不查未定义名**；ruff 能查，但本套件必须纯标准库、
    离线，不能引 ruff 当依赖——所以用 AST 自己查。

    口径（宁缺勿滥）：绑定来源含 import / 赋值与 walrus / def·class / 函数与 lambda 参数 /
    推导目标 / except-as / with-as / global·nonlocal / match 捕获 / 内置名 / 模块隐式全局；
    有 `from x import *` 的文件整体跳过。**注解也参与**——`from __future__ import annotations`
    让注解不求值，但"注解里写了个没导入的名字"仍是隐患（`get_type_hints`、或哪天去掉 future
    import 就炸），实测这条正是靠它抓到 `budget.py` 的 `Result`。
    """
    import builtins as _b

    implicit = {"__file__", "__name__", "__doc__", "__package__", "__spec__",
                "__loader__", "__builtins__", "__debug__"}
    bound: set[str] = set(implicit) | set(dir(_b))
    star = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bound |= {a.asname or a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    star = True
                else:
                    bound.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound |= set(node.names)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bound.add(node.rest)
    if star:
        return []
    used = {node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    return sorted(used - bound)


def run_undefined_names(trees: dict[Path, ast.AST]) -> None:
    """包代码里不许有未定义名（测试夹具不查：它们可以依赖别处的约定）。"""
    print("[test_undefined_names]")
    offenders: list[str] = []
    for path, tree in trees.items():
        if "tests" in path.parts:
            continue
        rel = path.relative_to(REPO).as_posix() if path.is_relative_to(REPO) else path.name
        offenders += [f"{rel}:{name}" for name in undefined_names(tree)]
    check(not offenders,
          "包代码没有未定义名（用了没导入/没赋值）" if not offenders
          else f"包代码里发现未定义名（发现 {len(offenders)} 处）:\n         "
               + "\n         ".join(offenders[:8]))
    # 反向自检（两个方向都测，否则"恒真/恒假"都看不出来）：
    bad = ast.parse("try:\n    pass\nexcept FooError:\n    pass\n")
    good = ast.parse("class FooError(Exception):\n    pass\n\n\ntry:\n    pass\n"
                     "except FooError:\n    pass\n")
    check(undefined_names(bad) == ["FooError"],
          f"能抓到「except 未导入的异常」（实得 {undefined_names(bad)}）")
    check(not undefined_names(good), f"定义过之后不再报（实得 {undefined_names(good)}）")
    star = ast.parse("from os import *\n\nprint(anything_at_all)\n")
    check(undefined_names(star) == [], "有 `import *` 的文件整体跳过（宁漏勿误报）")


def main() -> int:
    force_utf8_stdio()
    argparse.ArgumentParser(description="skillverify 自检（死代码 / 过期措辞）").parse_args()

    files = source_files()
    check(len(files) > 35, f"扫描到 {len(files)} 个 Python 文件")
    trees = {p: ast.parse(p.read_text(encoding="utf-8")) for p in files}

    print("[test_deadcode]")
    dead_imports, dead_defs, _stale = collect(trees)
    check(not dead_imports,
          "没有未使用的导入" if not dead_imports
          else f"没有未使用的导入（发现 {len(dead_imports)} 处）:\n         "
               + "\n         ".join(dead_imports[:8]))
    check(not dead_defs,
          "没有未被引用的模块级定义" if not dead_defs
          else f"没有未被引用的模块级定义（发现 {len(dead_defs)} 处）:\n         "
               + "\n         ".join(dead_defs[:8]))

    print("[test_stale_wording]")
    stale = [s for s in _stale if not s.endswith("请报 bug")]
    check(not stale,
          "没有「以后会做」式的过期措辞" if not stale
          else f"没有过期措辞（发现 {len(stale)} 处）:\n         " + "\n         ".join(stale[:6]))

    print("[test_forbidden_tempfile]")
    offenders: list[str] = []
    for path, tree in trees.items():
        rel = path.relative_to(REPO).as_posix() if path.is_relative_to(REPO) else path.name
        offenders += [f"{rel}:{lineno}" for lineno in forbidden_tempfile_calls(tree)]
    check(not offenders,
          "临时目录一律走 tmpdir.py（全仓无 tempfile.mkdtemp / TemporaryDirectory）"
          if not offenders
          else f"临时目录必须走 tmpdir.py（发现 {len(offenders)} 处禁用写法）:\n         "
               + "\n         ".join(offenders[:8]))
    # 反向自检：这条守卫**能失败**吗？拿一段典型代码问它（两种写法都要认出来）
    probe_tree = ast.parse("import tempfile\np = tempfile.mkdtemp(prefix='x')\n"
                           "from tempfile import TemporaryDirectory\n")
    check(len(forbidden_tempfile_calls(probe_tree)) == 2,
          "这条守卫能失败（探针里 `tempfile.mkdtemp` 与 from-import 两种写法都被认出）")
    # 平台差异是**刻意的**：POSIX 补回 0700（同机别的用户不该看到临时副本），
    # Windows 不能传 mode（传了会落成"仅所有者"的 DACL，沙箱里创建者自己进不去）。
    if os.name == "posix":
        check(TEMP_DIR_MODE == 0o700, f"POSIX 上临时目录用 0700（实得 {oct(TEMP_DIR_MODE)}）")
    else:
        check(TEMP_DIR_MODE is None, "Windows 上不传 mode（继承父目录 DACL，沙箱才可用）")

    run_undefined_names(trees)

    # 反向自检：这套检查**能失败**吗？故意造一处死代码与一句过期话术，验证会被抓到
    print("[test_selfcheck_can_fail]")
    with temp_dir(prefix="sv_selfcheck_") as probe_dir:
        probe_path = probe_dir / "_probe.py"
        probe_path.write_text(
            "import os\n\n\nclass UnusedProbe:\n    pass\n\n\nX = 1\n"
            "__all__ = [\"ExportedButUnused\"]\n\n\nclass ExportedButUnused:\n"
            "    pass\n",
            encoding="utf-8", newline="")
        di, dd, _s = collect({probe_path: ast.parse(probe_path.read_text(encoding="utf-8"))})
        check(any("未使用的导入 os" in item for item in di),
              "能抓到未使用的导入（证明这套检查不是恒真）")
        check(any("UnusedProbe" in item for item in dd),
              "能抓到未被引用的类（就是评审发现的那类死代码）")
        check(any("ExportedButUnused" in item for item in dd),
              "**列进 __all__ 也不豁免**：只声明导出、没人用的类同样要被抓出来")

    total = len(_passed) + len(_failed)
    print(f"\n结果: PASS={len(_passed)} FAIL={len(_failed)} 合计={total}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
