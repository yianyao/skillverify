"""强制 UTF-8 的 IO 辅助。

为什么必须独立成模块：本项目在 Windows 上实测过工具链因 GBK 控制台编码而
直接崩溃（UnicodeEncodeError: 'gbk' codec can't encode character '\\ufffd'）。
凡是要迁移到不同宿主/不同操作系统的程序，都不能假设默认编码。

原则：
1. 读文件一律显式 encoding="utf-8"（配合 newline="" 保留原始换行信息）。
2. 写文件一律显式 encoding="utf-8"、newline="\\n"（仓库统一 LF）。
3. 标准输出在入口处收敛为 UTF-8；对无法编码的字符用替代符而非抛异常。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: 全项目统一的文件编码
ENCODING = "utf-8"


def force_utf8_stdio() -> None:
    """把 stdout/stderr 切到 UTF-8，并使无法编码的字符降级为替代符。

    只在命令行入口调用一次。幂等。
    """
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding=ENCODING, errors="replace")
        except (ValueError, OSError):
            # 某些宿主把 stdout 换成不可重配的对象；不因此中断程序。
            pass


def read_text(path: Path) -> str:
    """按 UTF-8 读取文本；BOM 由调用方决定是否保留（此处不剥除）。"""
    return path.read_text(encoding=ENCODING, newline="")


def write_text(path: Path, text: str) -> None:
    """以 UTF-8 + LF 写入文本，必要时创建父目录。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=ENCODING, newline="\n")
