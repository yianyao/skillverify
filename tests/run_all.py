"""回归套件统一入口。

把 7 个 `tests/test_*.py` 一次跑完，并汇总结果。每个子套件都是独立可跑的
（`python -m tests.test_lint`），这里只是省掉逐条敲命令。

    python -m tests.run_all                # 全部套件（不含 dogfood）
    python -m tests.run_all --dogfood      # 额外把 legacy/ 拉进来跑 dogfood 项
    python -m tests.run_all --only lint,docs

退出码：0 = 全绿；1 = 任一套件有 FAIL。
"""

from __future__ import annotations

import argparse
import importlib
import io
import contextlib
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

#: (模块名, 简述)；顺序按依赖从底层到上层
SUITES: list[tuple[str, str]] = [
    ("test_spec", "官方规范（对齐 skills-ref 0.1.1）"),
    ("test_lint", "机械补检 42 条规则"),
    ("test_discover", "技能发现 + 声明式宿主适配 + check"),
    ("test_automation", "watch / deliver / git hook"),
    ("test_evalx", "评测资产（官方 evals 形状与工作区产物）"),
    ("test_trigger", "触发评测资产（查询集 / 运行记录 / 阈值）"),
    ("test_review", "语义评审（提示词目录 / 任务包 / 回写 / 汇总）"),
    ("test_docs", "两份交付文档（含演练块真跑）"),
    ("test_packaging", "打包（pyproject 静态检查；--install 时真装一遍）"),
]

#: 支持 --dogfood 的套件
DOGFOOD_SUITES = {"test_lint", "test_discover", "test_automation", "test_evalx",
                 "test_trigger", "test_review"}

#: 默认不跑的套件（需要网络/时长较长）；加了 --install 才跑
SLOW_SUITES = {"test_packaging"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="skillverify 回归套件统一入口")
    parser.add_argument("--dogfood", action="store_true",
                        help="额外把 legacy/ 下归档的旧技能拉进来跑 dogfood 项")
    parser.add_argument("--only", metavar="名1,名2",
                        help="只跑指定套件（名字去掉 test_ 前缀，如 lint,docs）")
    parser.add_argument("--install", action="store_true",
                        help="连打包套件的真装检查一起跑（需要网络，约 1 分钟）")
    parser.add_argument("--quiet", action="store_true", help="只打印汇总行")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    selected = SUITES
    if args.only:
        wanted = {x.strip().removeprefix("test_") for x in args.only.split(",") if x.strip()}
        known = {name.removeprefix("test_") for name, _ in SUITES}
        unknown = sorted(wanted - known)
        if unknown:
            print(f"未知套件 {unknown}；可用: {sorted(known)}", file=sys.stderr)
            return 1
        selected = [(n, d) for n, d in SUITES if n.removeprefix("test_") in wanted]

    if not args.install:
        selected = [(n, d) for n, d in selected if n not in SLOW_SUITES]

    results: list[tuple[str, int, str]] = []
    for name, desc in selected:
        module = importlib.import_module(f"tests.{name}")
        module._passed.clear()  # noqa: SLF001 - 同一进程内复用模块级计数器
        module._failed.clear()  # noqa: SLF001
        extra = ["--dogfood"] if (args.dogfood and name in DOGFOOD_SUITES) else []
        if name in SLOW_SUITES and args.install:
            extra.append("--install")
        buffer = io.StringIO()
        saved_argv = sys.argv
        sys.argv = [name, *extra]
        try:
            with contextlib.redirect_stdout(buffer):
                code = module.main()
        finally:
            sys.argv = saved_argv
        passed, failed = len(module._passed), len(module._failed)  # noqa: SLF001
        results.append((name, code, f"PASS={passed} FAIL={failed}"))
        if not args.quiet and failed:
            for line in buffer.getvalue().splitlines():
                if "FAIL " in line:
                    print(f"  {line.strip()}")
        status = "OK  " if code == 0 else "FAIL"
        print(f"[{status}] {name:<18} {desc:<34} {results[-1][2]}")

    total_pass = sum(int(r[2].split()[0].split("=")[1]) for r in results)
    total_fail = sum(int(r[2].split()[1].split("=")[1]) for r in results)
    bad = [name for name, code, _ in results if code != 0]
    print(f"\n合计: 套件 {len(results)} 个；断言 PASS={total_pass} FAIL={total_fail}")
    if bad:
        print(f"未通过的套件: {', '.join(bad)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
