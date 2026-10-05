"""打包回归测试（M7）。

分两档，因为二者的代价差一个数量级：

- **默认（离线、秒级）**：静态检查 `pyproject.toml`——
  入口点是否指向真实可调用的 `main`、`packages` 是否覆盖全部子包且**不**含 `legacy/`/`tests/`、
  `package-data` 的 glob 是否真的匹配到 `data/` 下的运行时数据、是否零运行时依赖、
  readme 是否指向真实存在的交付文档。
- **`--install`（需要网络，约 1 分钟）**：建一个临时 venv，真跑
  `pip install -e .`，然后**在仓库之外的任意目录**执行 `skillverify`；
  另外构建 wheel 并检查 `data/` 里的文件**确实进了发布物**
  （editable 安装会直接用源码树，看不出 package-data 配错——必须看 wheel）。

用法：
    python -m tests.test_packaging              # 静态检查
    python -m tests.test_packaging --install    # 额外真装一遍（需要网络）
"""

from __future__ import annotations

import argparse
import json
import fnmatch
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skillverify import cli  # noqa: E402
from skillverify.encoding import force_utf8_stdio  # noqa: E402
from skillverify.tmpdir import new_temp_dir  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PYPROJECT = REPO / "pyproject.toml"
DATA_DIR = REPO / "skillverify" / "data"

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


def load_pyproject() -> dict:
    import tomllib  # 3.11+；本套件在更早版本会被跳过（见 main）

    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# 静态检查
# --------------------------------------------------------------------------- #


def run_static() -> None:
    print("[test_static]")
    check(PYPROJECT.is_file(), "pyproject.toml 存在")
    data = load_pyproject()

    project = data.get("project", {})
    check(project.get("name") == "skillverify", f"包名正确（{project.get('name')}）")
    check(project.get("requires-python") == ">=3.10",
          f"Python 版本下限声明为 >=3.10（{project.get('requires-python')}）")
    check(project.get("dependencies") == [],
          "零运行时依赖（纯标准库是硬约束）")

    build = data.get("build-system", {})
    check(build.get("build-backend") == "setuptools.build_meta"
          and any(r.startswith("setuptools") for r in build.get("requires", [])),
          "构建后端为 setuptools")

    # 版本号单一真源
    dynamic = project.get("dynamic", [])
    attr = data.get("tool", {}).get("setuptools", {}).get("dynamic", {}).get("version", {})
    check("version" in dynamic and attr.get("attr") == "skillverify.__version__",
          "版本号取自 skillverify.__version__（单一真源，不在两处各写一份）")
    import skillverify

    check(bool(skillverify.__version__), f"版本号可取到（{skillverify.__version__}）")

    # 入口点必须指向真实可调用对象
    scripts = project.get("scripts", {})
    check(scripts.get("skillverify") == "skillverify.cli:main",
          f"命令入口正确（{scripts.get('skillverify')}）")
    check(callable(getattr(cli, "main", None)), "入口点指向的 main 真实存在且可调用")

    # readme 必须是真实存在的交付文档
    readme = project.get("readme")
    check(isinstance(readme, str) and (REPO / readme).is_file(),
          f"readme 指向存在的交付文档（{readme}）")

    # packages 必须覆盖全部子包，且不能把归档/测试打进去
    declared = set(data.get("tool", {}).get("setuptools", {}).get("packages", []))
    on_disk = {".".join(p.parent.relative_to(REPO).parts)
               for p in (REPO / "skillverify").rglob("__init__.py")
               if "__pycache__" not in p.parts}
    on_disk.add("skillverify")
    missing = sorted(on_disk - declared)
    check(not missing, f"packages 覆盖全部子包（缺: {missing}）")
    leaked = sorted(p for p in declared if p.startswith(("legacy", "tests", "handoff")))
    check(not leaked, f"packages 不含归档/测试（混入: {leaked}）")

    # package-data 必须真的匹配到运行时数据
    globs = data.get("tool", {}).get("setuptools", {}).get("package-data", {}).get("skillverify", [])
    check(bool(globs), f"声明了 package-data（{globs}）")
    runtime_files = [p for p in DATA_DIR.iterdir() if p.is_file()]
    check(runtime_files, f"data/ 下确有运行时数据（{[p.name for p in runtime_files]}）")
    for path in runtime_files:
        matched = any(fnmatch.fnmatch(path.name, pattern.split("/")[-1]) for pattern in globs)
        check(matched, f"{path.name} 被 package-data 覆盖")

    # 数据文件本身必须是可解析的（打包发出去坏了等于没发）
    check((DATA_DIR / "hosts.toml").is_file(), "hosts.toml 在 data/ 下")
    check((DATA_DIR / "review-prompts.json").is_file(), "review-prompts.json 在 data/ 下")
    from skillverify.discover import load_config
    from skillverify.review import load_catalog

    check(len(load_catalog()) >= 29, "提示词目录可加载（≥ 旧体系 29 条）")
    tmp_home = new_temp_dir(prefix="sv_pkg_home_")
    try:
        cfg = load_config(REPO, tmp_home, use_discovered_files=False)
        check("default" in cfg.hosts, "内置宿主配置可加载")
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)


# --------------------------------------------------------------------------- #
# 真装一遍（需要网络）
# --------------------------------------------------------------------------- #


def _run(cmd: list[str], cwd: Path | None = None, timeout: float = 600.0
         ) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


def venv_bin(venv: Path, name: str) -> Path:
    """venv 里的可执行文件（Windows 上是 .exe；用无扩展名路径 Windows 也能跑，
    但那样测的就不是"安装出来的命令"，所以这里显式解析）。"""
    base = venv / ("Scripts" if sys.platform == "win32" else "bin")
    candidates = [base / f"{name}.exe", base / name] if sys.platform == "win32" else [base / name]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def run_install(tmp: Path) -> None:
    print("[test_install]")
    python = Path(sys.executable)
    venv_dir = tmp / "venv"
    print(f"  · 建 venv: {venv_dir}")
    made = _run([str(python), "-m", "venv", str(venv_dir)])
    if made.returncode != 0:
        fail(f"建 venv 失败: {made.stderr.strip()[:200]}")
        return
    vpy = venv_bin(venv_dir, "python")
    check(vpy.is_file(), f"venv 解释器就绪（{vpy.name}）")

    print("  · pip install -e .（需要网络下载构建依赖）")
    install = _run([str(vpy), "-m", "pip", "install", "-e", str(REPO), "--quiet"], timeout=900)
    if install.returncode != 0:
        fail(f"`pip install -e .` 失败: {(install.stderr or install.stdout).strip()[-400:]}")
        return
    ok("`pip install -e .` 成功")

    # 关键：在**仓库之外**的任意目录执行
    elsewhere = tmp / "elsewhere"
    elsewhere.mkdir()
    exe = venv_bin(venv_dir, "skillverify")
    target = [str(exe)] if exe.is_file() else [str(vpy), "-m", "skillverify.cli"]
    check(exe.is_file(), f"命令入口已安装（{exe.name}）")

    version = _run([*target, "--version"], cwd=elsewhere)
    check(version.returncode == 0 and "skillverify" in (version.stdout + version.stderr),
          f"任意目录可执行 `skillverify --version`（{version.stdout.strip()[:40]}）")

    # 需要运行时数据的两条命令——package-data 配错时这两条会红
    prompts = _run([*target, "review", "prompts", "--json"], cwd=elsewhere)
    ok_prompts = False
    if prompts.returncode == 0:
        try:
            ok_prompts = len(json.loads(prompts.stdout)["prompts"]) >= 29
        except (json.JSONDecodeError, KeyError):
            ok_prompts = False
    check(ok_prompts, "任意目录可读提示词目录（package-data 生效）")

    discover = _run([*target, "discover", "--show-config"], cwd=elsewhere)
    check(discover.returncode == 0 and "[defaults]" in discover.stdout,
          "任意目录可读内置 hosts.toml（package-data 生效）")

    # 端到端：对一个临时技能跑 spec / lint
    skill = tmp / "elsewhere" / "demo-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: A demo skill installed from a wheel.\n"
        "---\n\n# Demo\n", encoding="utf-8", newline="")
    spec = _run([*target, "spec", str(skill)], cwd=elsewhere)
    check(spec.returncode == 0, f"任意目录可对技能跑 `spec`（exit={spec.returncode}）")

    # wheel 里的数据文件（editable 安装看不出这件事）
    print("  · 构建 wheel 并检查包内数据")
    wheel_dir = tmp / "wheel"
    built = _run([str(vpy), "-m", "pip", "wheel", str(REPO), "--no-deps",
                  "-w", str(wheel_dir), "--quiet"], timeout=900)
    wheels = sorted(wheel_dir.glob("skillverify-*.whl")) if wheel_dir.is_dir() else []
    if built.returncode != 0 or not wheels:
        fail(f"构建 wheel 失败: {(built.stderr or built.stdout).strip()[-300:]}")
        return
    names = zipfile.ZipFile(wheels[0]).namelist()
    for want in ("skillverify/data/hosts.toml", "skillverify/data/review-prompts.json"):
        check(want in names, f"wheel 内含 {want}")
    check(not any(n.startswith(("legacy/", "tests/", "handoff/")) for n in names),
          "wheel 不含 legacy/、tests/、handoff/")
    check(any(n.endswith("entry_points.txt") for n in names),
          "wheel 内有 entry_points.txt（命令入口随包发布）")

    # 非 editable 安装也应当可用（用刚构建的 wheel 装一遍）
    runtime_venv = tmp / "venv-runtime"
    _run([str(python), "-m", "venv", str(runtime_venv)])
    rpy = venv_bin(runtime_venv, "python")
    installed = _run([str(rpy), "-m", "pip", "install", str(wheels[0]), "--quiet"], timeout=600)
    rexe = venv_bin(runtime_venv, "skillverify")
    rtarget = [str(rexe)] if rexe.is_file() else [str(rpy), "-m", "skillverify.cli"]
    if installed.returncode == 0:
        fresh = _run([*rtarget, "review", "prompts", "--json"], cwd=elsewhere)
        check(fresh.returncode == 0 and len(json.loads(fresh.stdout)["prompts"]) >= 29,
              "非 editable 安装后提示词仍可读（数据真的进了 site-packages）")
    else:
        fail(f"wheel 安装失败: {(installed.stderr or installed.stdout).strip()[-300:]}")


def main() -> int:
    force_utf8_stdio()
    parser = argparse.ArgumentParser(description="skillverify 打包回归测试")
    parser.add_argument("--install", action="store_true",
                        help="真建 venv 并 pip install（需要网络，约 1 分钟）")
    args = parser.parse_args()

    try:
        import tomllib  # noqa: F401
    except ModuleNotFoundError:
        print("跳过：解析 pyproject.toml 需要 Python ≥3.11")
        return 0

    tmp = new_temp_dir(prefix="sv_test_packaging_")
    try:
        run_static()
        if args.install:
            run_install(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = len(_passed) + len(_failed)
    print(f"\n结果: PASS={len(_passed)} FAIL={len(_failed)} 合计={total}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
