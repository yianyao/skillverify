"""describe —— 命令面自描述（对外机读契约）。

为什么单独立一个模块：操作台等外部工具此前靠解析 argparse 私有结构
（`parser._actions`）来得知本工具的命令面——那是"从外面拆"，解析器内部
一动（换参数库、改装配方式）外部工具就静默拿到旧数据。`describe` 让
skillverify **自己声明**自己的命令面，输出带 schema 版本号的 JSON 契约：

    skillverify describe            # 人读命令树
    skillverify describe --json     # 机读契约（schema: skillverify.describe/1）

消费方（谁在等这份契约）：
- 本仓库 console/introspect.py：内省脚本的数据源（auto 模式下发现
  `describe_surface` 协议属性即优先使用，argparse 遍历降级为兜底）；
- 任何第三方工具（CI 校验、文档生成器）。

契约稳定性承诺：
- `schema` 字段带版本号；字段语义变更必须升版本号，只加字段不变语义可保持 /1；
- 实现上目前从 `cli.build_parser()` 的 parser 遍历提取（与内省脚本同一份
  事实来源），但这是**实现细节**——将来内部换参数库，只需保持本契约不变。

零业务知识出口：本模块只输出机械属性（flag/action/type/default/choices/
required/help），不含任何"这条命令该怎么用"的语义——语义在
console/manual/（操作台语义层）与文档里。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

#: 契约版本标记（消费方按此识别与校验）
SCHEMA = "skillverify.describe/1"


def _json_safe(value: Any) -> Any:
    """把 argparse 的属性值转成可 JSON 化的形式（与 console/introspect.py 同口径）。"""
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
        "metavar": _json_safe(action.metavar),
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
    """help / version 等元动作不进入命令面。"""
    return isinstance(action, (argparse._HelpAction, argparse._VersionAction))


def _walk_parser(parser: argparse.ArgumentParser,
                 command_path: str,
                 commands: dict) -> None:
    """递归遍历一个 parser 层级：先记录本层参数，再下钻子命令。"""
    positionals: list[dict] = []
    options: list[dict] = []
    sub_action: argparse._SubParsersAction | None = None

    for action in parser._actions:  # noqa: SLF001 —— 读自己的解析器
        if _is_skipped(action):
            continue
        if isinstance(action, argparse._SubParsersAction):
            sub_action = action
            continue
        if action.option_strings:
            options.append(_describe_option(action))
        else:
            positionals.append(_describe_positional(action))

    commands[command_path] = {
        "help": parser.description,
        "positionals": positionals,
        "options": options,
    }

    if sub_action is None:
        return
    for name, child in sub_action.choices.items():
        _walk_parser(child, f"{command_path} {name}".strip(), commands)


def build_surface() -> dict:
    """构建命令面契约（skillverify.describe/1）。

    延迟导入 cli：cli/__init__.py 会 import 本模块（cmd_describe 与
    describe_surface 协议导出），反向顶层 import 会成环。
    """
    from . import __version__
    from .cli import build_parser

    parser = build_parser()
    commands: dict = {}
    _walk_parser(parser, "", commands)
    return {
        "schema": SCHEMA,
        "tool": (parser.prog or "skillverify").split()[0],
        "version": __version__,
        "commands": commands,
    }


def render_text(surface: dict) -> str:
    """契约的人读形态：命令树 + 逐参数一行摘要（默认输出，--json 才是契约本体）。"""
    lines: list[str] = []
    for path in sorted(surface["commands"]):
        cmd = surface["commands"][path]
        title = path or surface["tool"]
        help_text = (cmd.get("help") or "").splitlines()[0] if cmd.get("help") else ""
        lines.append(f"{title}" + (f"  —— {help_text}" if help_text else ""))
        for p in cmd["positionals"]:
            lines.append(f"    <{p['name']}>  {p.get('help') or ''}")
        for o in cmd["options"]:
            flags = ",".join(o["flags"]) if o["flags"] else o["id"]
            extra = ""
            if o.get("choices") is not None:
                extra = f"  choices: {'|'.join(str(c) for c in o['choices'])}"
            elif o.get("type"):
                extra = f"  type: {o['type']}"
            lines.append(f"    {flags}  {o.get('help') or ''}{extra}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    """`python -m skillverify.describe` 直跑入口（调试用；正式入口是 describe 子命令）。"""
    del argv
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    surface = build_surface()
    json.dump(surface, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
