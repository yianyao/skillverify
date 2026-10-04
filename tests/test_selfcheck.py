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
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skillverify.encoding import force_utf8_stdio  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

#: 扫描范围（交付物本体 + 测试）
TREES = ("skillverify", "tests")

#: 过期措辞：功能早已实现、话术却还停在"以后会做"的状态
STALE_RE = re.compile(r"TODO|FIXME|后续版本|待实现|暂未实现|尚未实现")

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

    # 反向自检：这套检查**能失败**吗？故意造一处死代码与一句过期话术，验证会被抓到
    print("[test_selfcheck_can_fail]")
    import tempfile

    with tempfile.TemporaryDirectory(prefix="sv_selfcheck_") as probe_dir:
        probe_path = Path(probe_dir) / "_probe.py"
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
