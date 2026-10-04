"""lint.inventory —— 技能包文件清单与文本读取（lint 各检查族的共同底座）。

为什么单独一层：
1. 每个检查族都要"遍历包内文本文件"，若各写各的，跳过目录/二进制/超限/符号链接
   的口径必然漂移（旧体系里 `__pycache__` 一处跳过、一处当垃圾文件检，就是实例）。
2. 读取失败必须**结构化**记录，而不是混进某条检查的证据里——旧体系曾把"读取失败"
   写进密钥检查的 FAIL 证据，被读成"发现密钥"。
3. 编码探测只做一次，供 ENC 族与内容族共用。

口径（逐条声明，避免"没报就是过"）：
- 符号链接一律不跟随（不进入清单，单独计数），避免扫描范围蔓延到包外。
- 跳过目录以 SKIP_DIRS 为准；注意 `__pycache__` **不在**其中——它本身是垃圾文件
  检查（HYG-002）的对象，跳过它就检不出来了；其内容因二进制嗅探而不会被当文本扫。
- 单文件超过 MAX_SCAN_BYTES 只做体积类判定，不做内容扫描（记 oversized）。
- 二进制判定用 NUL 嗅探（前 8192 字节），不依赖扩展名——旧体系按扩展名黑名单
  会把无扩展名的二进制文件当文本读。
- 文本解码：先严格 UTF-8；失败则记 decode_error 并用 errors="replace" 兜底，
  使检查仍能继续（可由 ENC-004 判 FAIL），绝不抛异常中断整个报告。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..encoding import ENCODING

#: 不进入清单的目录名（任一 path part 命中即跳过整棵子树）
SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".verification",  # 旧体系逐技能留痕目录（工具痕迹，非交付物）
        ".agents",  # 新体系中央留痕目录（可配置，见 M2）
        "node_modules",
        ".venv",
        "venv",
        ".idea",
        ".vscode",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
    }
)

#: 内容扫描的单个文件上限（字节）；超过则只做体积类判定
MAX_SCAN_BYTES = 2 * 1024 * 1024

#: 体积告警线（字节），见 HYG-004
BIG_FILE_BYTES = 1 * 1024 * 1024

#: 脚本类扩展名（可执行语义）
CODE_EXTS: frozenset[str] = frozenset(
    {".py", ".sh", ".bash", ".zsh", ".fish", ".js", ".mjs", ".cjs", ".ts",
     ".rb", ".pl", ".ps1", ".psm1"}
)

#: shell 家族扩展名（CRLF 会直接导致 "bad interpreter"，见 ENC-001）
SHELL_EXTS: frozenset[str] = frozenset({".sh", ".bash", ".zsh", ".fish"})

#: 素材类扩展名（应归置 assets/，见 HYG-005）
ASSET_EXTS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp",
     ".pdf", ".zip", ".gz", ".tar", ".mp3", ".mp4", ".wav", ".woff",
     ".woff2", ".ttf", ".otf", ".docx", ".xlsx", ".pptx", ".csv"}
)


@dataclass
class FileRec:
    """包内单个文件的扫描记录。"""

    rel: Path  # 相对技能根目录
    path: Path
    size: int = -1
    raw: bytes | None = None
    text: str | None = None
    is_binary: bool = False
    oversized: bool = False
    decode_error: bool = False
    error: str = ""  # stat/读取失败原因（结构化，不混入检查证据）

    @property
    def rp(self) -> str:
        """POSIX 风格相对路径（报告展示统一用它）。"""
        return self.rel.as_posix()

    @property
    def suffix(self) -> str:
        return self.rel.suffix.lower()

    def under(self, *dirs: str) -> bool:
        """首个路径段是否属于给定目录集合（references/、assets/ 等）。"""
        parts = self.rel.parts
        return bool(parts) and parts[0] in dirs

    @property
    def is_shell(self) -> bool:
        return self.suffix in SHELL_EXTS

    @property
    def is_code(self) -> bool:
        """脚本语义：位于 scripts/ 下（任意扩展名）或扩展名属 CODE_EXTS。

        「scripts/ 下任意扩展名都算脚本」是有意为之——该目录的语义就是可执行代码；
        这一点在旧体系里是隐式约定，此处显式声明。
        """
        return self.under("scripts") or self.suffix in CODE_EXTS

    @property
    def is_text(self) -> bool:
        return self.text is not None


@dataclass
class Inventory:
    """技能包清单及其统计。"""

    root: Path
    files: list[FileRec] = field(default_factory=list)
    symlinks: list[str] = field(default_factory=list)

    @property
    def read_errors(self) -> list[FileRec]:
        return [f for f in self.files if f.error]

    @property
    def oversized(self) -> list[FileRec]:
        return [f for f in self.files if f.oversized]

    @property
    def binaries(self) -> list[FileRec]:
        return [f for f in self.files if f.is_binary]

    @property
    def texts(self) -> list[FileRec]:
        return [f for f in self.files if f.is_text]

    def by_rel(self, rel: str) -> FileRec | None:
        for rec in self.files:
            if rec.rp == rel:
                return rec
        return None

    def find(self, name: str) -> FileRec | None:
        """按文件名（basename）查记录，仅用于 SKILL.md 这类唯一文件。"""
        for rec in self.files:
            if rec.rel.name.lower() == name.lower():
                return rec
        return None


def build_inventory(root: Path) -> Inventory:
    """遍历技能目录，产出文件清单。不抛异常，失败一律记入 FileRec.error。"""
    inv = Inventory(root=root)
    try:
        walker = sorted(root.rglob("*"))
    except OSError as exc:  # 极端情况：目录不可列
        return inv

    for path in walker:
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.is_symlink():
            inv.symlinks.append(rel.as_posix())
            continue
        try:
            if not path.is_file():
                continue
        except OSError:
            continue

        rec = FileRec(rel=rel, path=path)
        try:
            rec.size = path.stat().st_size
        except OSError as exc:
            rec.error = f"stat 失败（{exc.strerror or exc}）"
            inv.files.append(rec)
            continue

        if rec.size > MAX_SCAN_BYTES:
            rec.oversized = True
            inv.files.append(rec)
            continue

        try:
            rec.raw = path.read_bytes()
        except OSError as exc:
            rec.error = f"读取失败（{exc.strerror or exc}）"
            inv.files.append(rec)
            continue

        # 二进制嗅探：NUL 字节（不依赖扩展名）
        if b"\x00" in rec.raw[:8192]:
            rec.is_binary = True
            inv.files.append(rec)
            continue

        try:
            rec.text = rec.raw.decode(ENCODING)
        except UnicodeDecodeError:
            rec.decode_error = True
            rec.text = rec.raw.decode(ENCODING, errors="replace")
        inv.files.append(rec)

    return inv
