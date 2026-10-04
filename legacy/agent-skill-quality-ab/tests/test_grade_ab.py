#!/usr/bin/env python3
"""test_grade_ab.py — grade_ab.py 固化回归单测（v1.2 第六轮评审修订后 14 组断言）。

用法: python tests/test_grade_ab.py （退出码 0=全过，非 0=有失败）
覆盖: delta 三态判定、summary 造假无视、数量/集合/唯一性校验（S-1 + 2.1）、
      非 dict 根（P-7）与非 dict 子对象（2.2）、assertions 缺失、passed 非 bool、
      单方优势项证据摘录（P-5 + 2.7）、成本估算（P-1 label 入错 消息）。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "grade_ab.py"
TMP: Path | None = None  # 2.5：main() 创建，__main__ 的 finally 统一清理
passed: list[str] = []
failed: list[str] = []


def ok(name: str, _detail: str = "") -> None:
    passed.append(name)
    print(f"PASS {name}")


def fail(name: str, detail: str = "") -> None:
    failed.append(name)
    print(f"FAIL {name}\n{detail}")


def make_grading(tmp: Path, texts_a: list[str], passed_a: list[bool],
                 texts_b: list[str], passed_b: list[bool],
                 report_a="a.md", report_b="b.md", extra=None) -> Path:
    A = [{"text": t, "passed": p, "evidence": f"证据-{t}"} for t, p in zip(texts_a, passed_a)]
    B = [{"text": t, "passed": p, "evidence": f"证据-{t}"} for t, p in zip(texts_b, passed_b)]
    data = {"with_skill": {"report": report_a, "assertions": A},
            "without_skill": {"report": report_b, "assertions": B}}
    if extra:
        data.update(extra)
    g = tmp / "g.json"
    g.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return g


def run(tmp: Path, extra_args=()) -> tuple[int, str, str]:
    p = subprocess.run([sys.executable, str(SCRIPT), "--grading", str(tmp / "g.json"), *extra_args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout, p.stderr


def main() -> int:
    texts = [f"a{i}" for i in range(1, 11)]

    # 1) delta>0 → 候选 PASS exit 0（复刻实测 0.7 vs 0.6）
    global TMP
    tmp = Path(tempfile.mkdtemp())
    TMP = tmp
    make_grading(tmp, texts, [i <= 7 for i in range(1, 11)], texts, [i <= 6 for i in range(1, 11)])
    rc, out, err = run(tmp)
    (ok if (rc == 0 and "PASS 候选" in out and "+0.10" in out) else fail)(
        "case1 delta +0.10 → exit 0", f"rc={rc}\n{out}{err}")

    # 2) delta<0 → exit 1
    make_grading(tmp, texts, [i <= 5 for i in range(1, 11)], texts, [i <= 7 for i in range(1, 11)])
    rc, out, err = run(tmp)
    (ok if (rc == 1 and "FAIL" in out) else fail)("case2 delta<0 → exit 1", f"rc={rc}\n{out}")

    # 3) 平局 → exit 2
    make_grading(tmp, texts, [i <= 6 for i in range(1, 11)], texts, [i <= 6 for i in range(1, 11)])
    rc, out, err = run(tmp)
    (ok if (rc == 2 and "平局" in out) else fail)("case3 平局 → exit 2", f"rc={rc}\n{out}")

    # 4) 断言数不一致 → 报错 exit 1
    make_grading(tmp, texts, [i <= 7 for i in range(1, 11)], texts[:9], [i <= 6 for i in range(1, 10)])
    rc, out, err = run(tmp)
    (ok if (rc == 1 and "不一致" in err) else fail)("case4 断言数不一致报错", f"rc={rc}\n{err}")

    # 5) 手填 summary 造假被无视：填 0.9，实算 4/10
    g = {"with_skill": {"report": "a.md", "summary": {"pass_rate": 0.9},
         "assertions": [{"text": f"t{i}", "passed": i <= 4, "evidence": "e"} for i in range(1, 11)]},
         "without_skill": {"report": "b.md",
         "assertions": [{"text": f"t{i}", "passed": i <= 6, "evidence": "e"} for i in range(1, 11)]}}
    (tmp / "g.json").write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    rc, out, err = run(tmp)
    (ok if (rc == 1 and "0.40" in out and "0.60" in out) else fail)(
        "case5 手填 summary 被无视（0.40 vs 0.60 → exit 1）", f"rc={rc}\n{out}")

    # 6) S-1：两臂顺序不同但 text 集合相同 → 重排后正确配对（错配会使单方优势项失真）
    rev = list(reversed(texts))
    make_grading(tmp, texts, [i <= 7 for i in range(1, 11)], rev, [t in {"a8", "a9", "a10"} for t in rev])
    rc, out, err = run(tmp)
    # a8/a9/a10 在 B 通过、A 未通过 → 仅 without_skill 通过 3 条；a1–a7 反之 → 仅 with 7 条
    (ok if (rc == 0 and "仅 with_skill 通过（7 条）" in out and "仅 without_skill 通过（3 条）" in out)
     else fail)("case6 顺序重排后正确配对", f"rc={rc}\n{out}{err}")

    # 7) S-1：数量相同但 text 集合不同源 → 报错 exit 1
    other = [f"x{i}" for i in range(1, 11)]
    make_grading(tmp, texts, [i <= 7 for i in range(1, 11)], other, [i <= 6 for i in range(1, 11)])
    rc, out, err = run(tmp)
    (ok if (rc == 1 and "不同源" in err) else fail)("case7 text 集合不同源报错", f"rc={rc}\n{err}")

    # 8) P-7：根类型非 dict → 报错不崩溃
    (tmp / "g.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    rc, out, err = run(tmp)
    (ok if (rc == 1 and "根类型" in err) else fail)("case8 非 dict 根报错", f"rc={rc}\n{err}")

    # 9) P-5：单方优势项附证据摘录（a7 是 A 独过项）
    make_grading(tmp, texts, [i <= 7 for i in range(1, 11)], texts, [i <= 6 for i in range(1, 11)])
    rc, out, err = run(tmp)
    (ok if "a7（A 证据: 证据-a7）" in out else fail)("case9 单方优势项附证据摘录", f"rc={rc}\n{out}")

    # 10) P-1：成本估算 + label 入错误消息（不存在的文件）
    rc, out, err = run(tmp, ("--cost-a", str(tmp / "nonexist.md")))
    (ok if ("文件不存在（A:" in out and "粗估" not in out) else fail)(
        "case10 成本 label 入错误消息", f"rc={rc}\n{out}")

    # 11) 2.4：with_skill 缺 assertions → arm_stats ValueError → exit 1
    (tmp / "g.json").write_text(json.dumps(
        {"with_skill": {"report": "a.md"},
         "without_skill": {"report": "b.md",
                           "assertions": [{"text": "t1", "passed": True, "evidence": "e"}]}},
        ensure_ascii=False), encoding="utf-8")
    rc, out, err = run(tmp)
    (ok if (rc == 1 and "assertions 数组缺失" in err) else fail)(
        "case11 assertions 缺失报错", f"rc={rc}\n{err}")

    # 12) 2.4：passed 非 bool（字符串 "yes"）→ 拒绝 exit 1
    (tmp / "g.json").write_text(json.dumps(
        {"with_skill": {"report": "a.md",
                        "assertions": [{"text": "t1", "passed": "yes", "evidence": "e"}]},
         "without_skill": {"report": "b.md",
                           "assertions": [{"text": "t1", "passed": True, "evidence": "e"}]}},
        ensure_ascii=False), encoding="utf-8")
    rc, out, err = run(tmp)
    (ok if (rc == 1 and "布尔 passed" in err) else fail)(
        "case12 passed 非 bool 拒绝", f"rc={rc}\n{err}")

    # 13) 2.1：断言 text 重复（集合校验会误通过）→ 唯一性校验报错 exit 1
    dup = [{"text": "dup", "passed": True, "evidence": "e1"},
           {"text": "dup", "passed": False, "evidence": "e2"},
           {"text": "unique", "passed": True, "evidence": "e3"}]
    (tmp / "g.json").write_text(json.dumps(
        {"with_skill": {"report": "a.md", "assertions": dup},
         "without_skill": {"report": "b.md", "assertions": list(reversed(dup))}},
        ensure_ascii=False), encoding="utf-8")
    rc, out, err = run(tmp)
    (ok if (rc == 1 and "重复 text" in err) else fail)(
        "case13 text 重复报错（防 ab_map 静默错配）", f"rc={rc}\n{err}")

    # 14) 2.2：with_skill 键存在但非 dict → ValueError 走统一错误通道 exit 1（不抛栈）
    (tmp / "g.json").write_text(json.dumps(
        {"with_skill": "foo",
         "without_skill": {"report": "b.md",
                           "assertions": [{"text": "t1", "passed": True, "evidence": "e"}]}},
        ensure_ascii=False), encoding="utf-8")
    rc, out, err = run(tmp)
    (ok if (rc == 1 and "应为对象（dict）" in err and "Traceback" not in err) else fail)(
        "case14 子对象非 dict 报错不崩溃", f"rc={rc}\n{err}")

    print(f"\n{'ALL PASS（%d 组断言）' % len(passed)}" if not failed
          else f"\n{len(failed)} FAILED / {len(passed)} PASS")
    return 0 if not failed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        if TMP is not None:
            shutil.rmtree(TMP, ignore_errors=True)
