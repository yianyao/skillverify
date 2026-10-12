"""console/introspect.py —— 通用命令面内省脚本（子进程内执行）。

职责（设计文档 §9.1 + EVOL-01）：
- 由生成器以子进程方式调用：`<python> console/introspect.py [选项]`，JSON 打到 stdout；
- **数据源二选一**（--data-source，默认 auto）：
  1. `describe` 协议（首选）：目标模块按约定导出 `describe_surface()`（返回
     `<tool>.describe/<n>` 版本化契约，如 skillverify 的 `skillverify describe --json`），
     本脚本校验并映射为内部输出结构——稳定契约，不碰 argparse 私有结构；
  2. argparse 遍历（兜底）：导入目标工具的 parser 工厂，遍历 `_actions` 提取
     子命令树、位置参数与选项的机械属性（flag/action/type/default/choices/
     required/help）——给没有 describe 协议的任意 argparse 工具用；
- 本脚本**不含任何 skillverify 业务知识**（目标模块与工厂经命令行指定）。

零侵入边界：本脚本运行在独立子进程里，允许 import 目标工具；console 自身进程
永不 import skillverify（设计文档 §1.1 契约 1）。

输出结构（两数据源归一为同一形状）：
    {"tool_version": "<字符串>", "commands": {"<命令路径>": {"positionals": [...], "options": [...]}, ...}}
命令路径对嵌套子命令用空格连接（如 "review collect"）。
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
from pathlib import Path

# 让本脚本无论从哪个 cwd 调用，都能 import 到"console/ 所在仓库"的包。
# 通用假设：脚本位于目标仓库的 console/ 目录下；已安装（pip）的包天然可导入。
_HERE = Path(__file__).resolve()
for _p in (str(_HERE.parent.parent), os.getcwd()):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _json_safe(value):
    """把 argparse 的属性值转成可 JSON 化的形式。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if callable(value):
        return getattr(value, "__name__", str(value))
    return str(value)


def _describe_option(action: argparse.Action) -> dict:
    """选项（有 option_strings）的机械属性描述。"""
    flags = list(action.option_strings)
    long_flags = [f for f in flags if f.startswith("--")]
    return {
        "id": action.dest,
        "flag": (long_flags or flags)[0] if flags else None,
        "flags": flags,
        "action": action.__class__.__name__,
        "nargs": action.nargs,
        "type": _json_safe(action.type),
        "default": _json_safe(action.default),
        "choices": _json_safe(action.choices) if action.choices is not None else None,
        "required": bool(getattr(action, "required", False)),
        "help": action.help,
        "metavar": action.metavar,
    }


def _describe_positional(action: argparse.Action) -> dict:
    """位置参数（无 option_strings）的机械属性描述。"""
    return {
        "id": action.dest,
        "name": action.metavar or action.dest,
        "nargs": action.nargs,
        "choices": _json_safe(action.choices) if action.choices is not None else None,
        "help": action.help,
    }


def _is_skipped(action: argparse.Action) -> bool:
    """help / version 等元动作不进入参数面。"""
    return isinstance(action, (argparse._HelpAction, argparse._VersionAction))


def _introspect_parser(parser: argparse.ArgumentParser,
                       command_path: str,
                       commands: dict) -> None:
    """递归遍历一个 parser 层级：先记录本层参数，再下钻子命令。"""
    positionals: list[dict] = []
    options: list[dict] = []
    sub_action: argparse._SubParsersAction | None = None

    for action in parser._actions:
        if _is_skipped(action):
            continue
        if isinstance(action, argparse._SubParsersAction):
            sub_action = action
            continue
        if action.option_strings:
            options.append(_describe_option(action))
        else:
            positionals.append(_describe_positional(action))

    commands[command_path] = {"positionals": positionals, "options": options}

    if sub_action is None:
        return
    for name, child in sub_action.choices.items():
        child_path = f"{command_path} {name}".strip()
        _introspect_parser(child, child_path, commands)


def _derive_tool_version(module, parser: argparse.ArgumentParser) -> str:
    """按 Python 约定推导工具版本（<包>.__version__）——通用机制，不含业务知识。"""
    pkg_name = getattr(module, "__package__", "") or module.__name__
    root_name = pkg_name.split(".")[0]
    try:
        root = importlib.import_module(root_name)
        version = getattr(root, "__version__", None)
    except Exception:  # noqa: BLE001 —— 版本推导失败不致命，降级为空
        version = None
    prog = (parser.prog or "").split()[0] if parser.prog else ""
    if version and prog:
        return f"{prog} {version}"
    return str(version or prog or "")


# ------------------------------------------------------------ describe 协议映射

#: describe 协议的 schema 标记格式：<工具名>.describe/<版本号>
_DESCRIBE_SCHEMA_RE = re.compile(r"^[\w.-]+\.describe/\d+$")


def _from_describe_contract(contract: object) -> dict:
    """把 describe 协议载荷映射为内部输出结构。

    载荷形状不对 → ValueError（调用方决定降级还是报错）；只取两数据源
    共有的字段（positionals/options），命令的 help 等扩展字段留在契约里
    不进本输出——保证两条数据源的产出**逐字段一致**。
    """
    if not isinstance(contract, dict):
        raise ValueError(f"载荷不是 JSON 对象（实得 {type(contract).__name__}）")
    schema = contract.get("schema")
    if not isinstance(schema, str) or not _DESCRIBE_SCHEMA_RE.match(schema):
        raise ValueError(f"schema 标记缺失或不合法（实得 {schema!r}，"
                         f"应为 <工具名>.describe/<版本号>）")
    raw_commands = contract.get("commands")
    if not isinstance(raw_commands, dict):
        raise ValueError("commands 缺失或不是对象")
    commands: dict = {}
    for path, cmd in raw_commands.items():
        if not isinstance(path, str) or not isinstance(cmd, dict):
            raise ValueError(f"命令条目形状不合法（路径 {path!r}）")
        if not isinstance(cmd.get("positionals"), list) \
                or not isinstance(cmd.get("options"), list):
            raise ValueError(f"命令 {path!r} 缺 positionals/options 列表")
        commands[path] = {"positionals": cmd["positionals"],
                          "options": cmd["options"]}
    tool = contract.get("tool") or ""
    version = contract.get("version") or ""
    return {
        "tool_version": f"{tool} {version}".strip(),
        "commands": commands,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="introspect.py",
        description="通用命令面内省脚本：提取子命令树与逐参数机械属性，JSON 输出到 stdout",
    )
    ap.add_argument("--import", dest="module", default="skillverify.cli",
                    help="parser 工厂所在的模块导入路径（默认 skillverify.cli）")
    ap.add_argument("--factory", default="build_parser",
                    help="构建 argparse parser 的工厂函数名（默认 build_parser）")
    ap.add_argument("--tool-version", default="",
                    help="显式指定工具版本（缺省时按数据源自动推导）")
    ap.add_argument("--data-source", choices=("auto", "describe", "argparse"),
                    default="auto",
                    help="命令面数据源：describe=目标模块的 describe_surface 协议；"
                         "argparse=遍历 parser；auto=有协议用协议、没有走 argparse（默认）")
    args = ap.parse_args(argv)

    try:
        module = importlib.import_module(args.module)
    except Exception as exc:  # noqa: BLE001 —— 内省失败必须显式报错，不产出半份数据
        print(f"introspect: 无法导入目标模块（{args.module}）: {exc}", file=sys.stderr)
        return 1

    payload: dict | None = None
    describe_fn = getattr(module, "describe_surface", None)
    if args.data_source in ("auto", "describe") and callable(describe_fn):
        try:
            payload = _from_describe_contract(describe_fn())
        except ValueError as exc:
            if args.data_source == "describe":
                print(f"introspect: describe 协议载荷不合法: {exc}", file=sys.stderr)
                return 1
            print(f"introspect: describe 载荷不合法（{exc}），降级 argparse 遍历",
                  file=sys.stderr)
        if payload is not None and args.tool_version:
            payload["tool_version"] = args.tool_version
    if payload is None:
        if args.data_source == "describe":
            print(f"introspect: {args.module} 未提供 describe 协议"
                  f"（模块属性 describe_surface）", file=sys.stderr)
            return 1
        try:
            factory = getattr(module, args.factory)
            parser = factory()
        except Exception as exc:  # noqa: BLE001 —— 同上，显式报错
            print(f"introspect: 无法构建目标 parser（{args.module}.{args.factory}）: {exc}",
                  file=sys.stderr)
            return 1
        commands: dict = {}
        _introspect_parser(parser, "", commands)
        payload = {
            "tool_version": args.tool_version or _derive_tool_version(module, parser),
            "commands": commands,
        }

    # Windows 控制台默认 cp936，统一以 UTF-8 输出
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
