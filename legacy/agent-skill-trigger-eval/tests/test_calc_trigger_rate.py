#!/usr/bin/env python3
"""test_calc_trigger_rate.py — calc_trigger_rate.py 固化回归单测（v1.1 第七轮评审修订后 9 组断言）。

用法: python tests/test_calc_trigger_rate.py （退出码 0=全过，非 0=有失败）
覆盖: 过门三态判定、次数不足 WARN 降级、未运行 WARN、S-1 非 dict 根、
      S-2 汇总 WARN 分列不混同、P-4 loaded 非 bool 告警、P-8 统计覆盖率。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "calc_trigger_rate.py"
TMP: Path | None = None
passed: list[str] = []
failed: list[str] = []


def ok(name: str, _detail: str = "") -> None:
    passed.append(name)
    print(f"PASS {name}")


def fail(name: str, detail: str = "") -> None:
    failed.append(name)
    print(f"FAIL {name}\n{detail}")


QS = {"queries": [
    {"id": "P01", "subset": "train", "should_trigger": True},
    {"id": "N01", "subset": "train", "should_trigger": False},
    {"id": "P06", "subset": "validation", "should_trigger": True},
    {"id": "N06", "subset": "validation", "should_trigger": False},
]}


def run(runs: list[dict], queryset=None) -> tuple[int, str, str]:
    (TMP / "qs.json").write_text(json.dumps(queryset or QS, ensure_ascii=False), encoding="utf-8")
    (TMP / "runs.json").write_text(json.dumps({"runs": runs}, ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([sys.executable, str(SCRIPT), "--runs", str(TMP / "runs.json"),
                        "--queryset", str(TMP / "qs.json")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout, p.stderr


def main() -> int:
    global TMP
    TMP = Path(tempfile.mkdtemp())
    try:
        _cases()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

    print(f"\n{'ALL PASS（%d 组断言）' % len(passed)}" if not failed
          else f"\n{len(failed)} FAILED / {len(passed)} PASS")
    return 0 if not failed else 1


def _cases() -> None:
    # 1) 全过 exit 0，汇总无 WARN 后缀
    rc, out, err = run([{"query_id": "P01", "run": i, "loaded": True} for i in (1, 2, 3)]
                       + [{"query_id": "N01", "run": i, "loaded": False} for i in (1, 2, 3)]
                       + [{"query_id": "P06", "run": i, "loaded": i < 3} for i in (1, 2, 3)]
                       + [{"query_id": "N06", "run": i, "loaded": i == 1} for i in (1, 2, 3)])
    (ok if (rc == 0 and "PASS 全过门" in out and "WARN" not in out.split("总结论")[0].split("统计覆盖率")[1])
     else fail)("case1 全过 exit 0 且汇总无 WARN", f"rc={rc}\n{out}{err}")

    # 2) 次数足、负例误触发 → FAIL exit 1
    rc, out, err = run([{"query_id": "P01", "run": 1, "loaded": True}] * 3
                       + [{"query_id": "N01", "run": i, "loaded": i < 3} for i in (1, 2, 3)])
    (ok if (rc == 1 and "FAIL" in out) else fail)("case2 负例误触发 exit 1", f"rc={rc}\n{out}")

    # 3) 次数不足且负例误触发 → FAIL 降级 WARN exit 2，汇总 WARN 分列（S-2：不与"过"混同）
    rc, out, err = run([{"query_id": "P01", "run": 1, "loaded": True},
                        {"query_id": "N01", "run": 1, "loaded": True}])
    (ok if (rc == 2 and "另 1 WARN" in out and "0/1 过（另 1 WARN）" in out and "数据不足" in out)
     else fail)("case3 次数不足 WARN 降级且汇总分列", f"rc={rc}\n{out}")

    # 4) 未运行 → WARN 数据缺失 exit 2
    rc, out, err = run([{"query_id": "P01", "run": i, "loaded": True} for i in (1, 2, 3)]
                       + [{"query_id": "N01", "run": i, "loaded": False} for i in (1, 2, 3)])
    (ok if (rc == 2 and "未运行" in out) else fail)("case4 未运行 WARN", f"rc={rc}\n{out}")

    # 5) S-1：queryset 根为数组 → ValueError 统一错误 exit 1 不抛栈
    rc, out, err = run([{"query_id": "P01", "run": 1, "loaded": True}], queryset=[1, 2, 3])
    (ok if (rc == 1 and "根类型" in err and "Traceback" not in err) else fail)(
        "case5 非 dict 根报错不崩溃", f"rc={rc}\n{err}")

    # 6) P-4：loaded=1（整数）→ 告警 + 按未触发计入（P01 触发率 0 → FAIL exit 1）
    rc, out, err = run([{"query_id": "P01", "run": i, "loaded": 1} for i in (1, 2, 3)]
                       + [{"query_id": "N01", "run": i, "loaded": False} for i in (1, 2, 3)])
    (ok if (rc == 1 and "非 bool" in err and "P01 | train | 是 | 3 | 0 |" in out) else fail)(
        "case6 loaded 非 bool 告警且不计触发", f"rc={rc}\n{out}{err}")

    # 7) P-8：unknown 比例高 → 覆盖率行 + 低覆盖率 WARN（2/4 记录被丢弃 = 50%）
    rc, out, err = run([{"query_id": "P01", "run": i, "loaded": True} for i in (1, 2, 3)]
                       + [{"query_id": "N01", "run": i, "loaded": False} for i in (1, 2, 3)]
                       + [{"query_id": "XX99", "run": 1, "loaded": True}] * 6)
    (ok if (rc == 2 and "统计覆盖率: 6/12 条记录（50%" in out and "不在查询集内" in err) else fail)(
        "case7 低覆盖率显著展示", f"rc={rc}\n{out}{err}")

    # 8) P-8：覆盖率正常时也不误报 WARN 后缀（全过场景已含覆盖率 100%）
    rc, out, err = run([{"query_id": "P01", "run": i, "loaded": True} for i in (1, 2, 3)]
                       + [{"query_id": "N01", "run": i, "loaded": False} for i in (1, 2, 3)])
    (ok if ("统计覆盖率: 6/6 条记录（100%" in out) else fail)(
        "case8 正常覆盖率 100%", f"rc={rc}\n{out}")

    # 9) S-1：runs 根为字符串 → 报错不崩溃
    (TMP / "qs.json").write_text(json.dumps(QS, ensure_ascii=False), encoding="utf-8")
    (TMP / "runs.json").write_text('"hello"', encoding="utf-8")
    p = subprocess.run([sys.executable, str(SCRIPT), "--runs", str(TMP / "runs.json"),
                        "--queryset", str(TMP / "qs.json")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    (ok if (p.returncode == 1 and "根类型" in p.stderr and "Traceback" not in p.stderr) else fail)(
        "case9 runs 非 dict 根报错", f"rc={p.returncode}\n{p.stderr}")


if __name__ == "__main__":
    sys.exit(main())
