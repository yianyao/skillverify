"""临时目录的创建与清理——**不用** `tempfile.mkdtemp` / `TemporaryDirectory`。

为什么不能直接用标准库那两个：

- `tempfile.mkdtemp()` 以 `mode=0o700` 创建目录；在 Windows 上 CPython 会把这个 mode
  落成"仅所有者"的 DACL（`tempfile` 连自己的清理都要先把权限改回 0o700）。
- 沙箱（DSH 等以 AppContainer 形式运行子进程的机制）的访问检查要求 DACL **同时**授予
  用户 SID 与该容器的 SID。只写用户 SID 的 DACL 于是**创建者自己也进不去**。
- 实测现象：`mount` 的临时副本探针、`lint --scripts` 的 dry-run 探针在沙箱里直接抛
  `PermissionError: [WinError 5]`（连 `TemporaryDirectory` 的清理都会二次抛错），
  而在**普通终端里跑永远复现不了**——正是本项目最忌讳的"本机通过、换个环境就崩"。

修法只有一句：`os.mkdir()` **不传 mode**，让目录继承父目录的 DACL（含容器 SID）。
`os.urandom` 负责撞名重试，`shutil.rmtree(..., ignore_errors=True)` 负责收尾——
清理失败不该把一次正常检查变成崩溃（临时目录是尽力而为的产物）。
"""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

#: 默认前缀；调用方一律再给一个语义化的前缀，便于排查残留
DEFAULT_PREFIX = "skillverify-"

#: 撞名重试次数（6 字节随机后缀撞名概率可忽略，这里只是不写死 while True）
_MAX_ATTEMPTS = 64


def base_dir() -> Path:
    """系统临时根（尊重 TEMP/TMP/TMPDIR 等环境变量）。"""
    return Path(tempfile.gettempdir())


def new_temp_dir(prefix: str = DEFAULT_PREFIX) -> Path:
    """在系统临时根下创建一个**本进程可继续读写**的目录并返回它。

    调用方负责清理；需要自动清理请用 `temp_dir()`。创建不出来时抛 `OSError`
    （调用方应把它记成"未执行"而不是假装通过——临时目录不可用是环境事实）。
    """
    base = base_dir()
    for _ in range(_MAX_ATTEMPTS):
        candidate = base / f"{prefix}{os.urandom(6).hex()}"
        try:
            os.mkdir(candidate)
        except FileExistsError:
            continue
        return candidate
    raise OSError(f"临时目录创建失败：{base} 下连续 {_MAX_ATTEMPTS} 次撞名")


@contextmanager
def temp_dir(prefix: str = DEFAULT_PREFIX) -> Iterator[Path]:
    """创建临时目录并在退出时尽力删除（删除失败不抛）。"""
    path = new_temp_dir(prefix)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
