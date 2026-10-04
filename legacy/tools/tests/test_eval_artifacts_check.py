#!/usr/bin/env python3
"""test_eval_artifacts_check.py — eval_artifacts_check.py 单测（20 组断言）。

夹具全部 write_bytes / json.dumps 落盘（Windows write_text 换行翻译会污染
LF 夹具——历轮踩坑，见 ~/.workbuddy/MEMORY.md）。真实结构取材
agent-skill-trigger-eval/.verification（queryset meta+queries 形态）与
agent-skill-llm-review/.verification/gate-d/grading.json（with_skill.assertions
+ summary 形态）脱敏。python -O 免疫（断言不用 assert 语句）。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "eval_artifacts_check.py"

_n_pass = 0
_n_fail = 0


def ok(msg: str) -> None:
    global _n_pass
    _n_pass += 1
    print(f"  PASS {msg}")


def fail(msg: str) -> None:
    global _n_fail
    _n_fail += 1
    print(f"  FAIL {msg}")


def done() -> int:
    print(f"\n{'=' * 60}\n总计: {_n_pass} PASS / {_n_fail} FAIL"
          f" — {'全绿' if not _n_fail else '存在失败'}")
    return 1 if _n_fail else 0


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, encoding="utf-8")


def row_level(stdout: str, lid: str) -> str:
    for ln in stdout.splitlines():
        if ln.startswith(f"| {lid} |"):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) >= 3:
                return cells[2]
    return "(无该行)"


def write_json(p: Path, obj: object) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"))


def mk_queryset(n_pos: int = 6, n_neg: int = 6, drop_field: str = "",
                bad_bool_id: str = "", dup_id: bool = False) -> dict:
    """构造查询集：train 7 / validation 5（58%/42%，60/40±5pp 带内）。"""
    qs: list[dict] = []
    train_val = ["train"] * 7 + ["validation"] * 5
    idx = 0
    ids: list[str] = []
    for i in range(1, n_pos + 1):
        qid = f"P{i:02d}"
        ids.append("P01" if dup_id and i == 2 else qid)
        it = {"id": ids[-1], "subset": train_val[idx % 12], "should_trigger": True,
              "category": "positive-direct", "query": f"正例查询 {i}：请实测该技能触发。"}
        idx += 1
        qs.append(it)
    for i in range(1, n_neg + 1):
        qid = f"N{i:02d}"
        ids.append("N01" if dup_id and i == 2 else qid)
        it = {"id": ids[-1], "subset": train_val[idx % 12], "should_trigger": False,
              "category": "negative-near-miss", "query": f"负例 near-miss 查询 {i}：CI 门禁排障。"}
        idx += 1
        qs.append(it)
    if bad_bool_id:
        for it in qs:
            if it["id"] == bad_bool_id:
                it["should_trigger"] = "true"
    if drop_field:
        for it in qs:
            it.pop(drop_field, None)
    return {"meta": {"counts": {"total": len(qs)}}, "queries": qs}


def hash_of(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


def make_base(root: Path) -> None:
    """合规基线夹具：Q-1~Q-9 全 PASS/INFO 形态。"""
    qs = mk_queryset()
    qsp = root / "trigger-eval" / "queryset.json"
    write_json(qsp, qs)
    (root / "trigger-eval" / "frozen.sha256").write_bytes(
        f"{hash_of(qsp)}  queryset.json\n".encode("utf-8"))
    runs = []
    for it in qs["queries"]:
        for k in (1, 2):
            runs.append({"query_id": it["id"], "run": k,
                         "loaded": it["should_trigger"],
                         "evidence": "Skill 调用记录（夹具）",
                         "total_tokens": 100, "duration_ms": 500})
    write_json(root / "trigger-eval" / "runs.json", {"runs": runs})
    write_json(root / "workspace" / "iteration-1" / "eval-a" / "with_skill" / "timing.json",
               {"total_tokens": 100, "duration_ms": 2000})
    assertions = [
        {"text": "断言一：输出含结论", "passed": True, "evidence": "报告 §2 原文引用（夹具）"},
        {"text": "断言二：路径正确", "passed": False, "evidence": "实测 ls 输出引用（夹具）"},
        {"text": "断言三：格式合规", "passed": True, "evidence": "frontmatter 四字段齐（夹具）"},
    ]
    write_json(root / "workspace" / "iteration-1" / "eval-a" / "with_skill" / "grading.json",
               {"with_skill": {"assertions": assertions,
                               "summary": {"passed": 2, "failed": 1, "total": 3,
                                           "pass_rate": 2 / 3}}})
    write_json(root / "workspace" / "iteration-1" / "eval-a" / "benchmark.json",
               {"with_skill": {"pass_rate": 0.8, "time_seconds": 12.5, "tokens": 900},
                "without_skill": {"pass_rate": 0.4, "time_seconds": 10.0, "tokens": 600},
                "delta": {"pass_rate": 0.4, "time_seconds": 2.5, "tokens": 300}})
    log = (
        "# LLM 评审日志（V12 留痕）\n\n"
        "| 日期 | 提示词编号 | 模型名+版本 | 输出证据（结论摘要/引用） | 判定 | 是否双评 |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| 2026-10-03 | W-02 | GLM-测试(独立会话A) | [包A] 五子维全PASS, 证据=SKILL.md L28 | PASS | 是 |\n"
        "| 2026-10-03 | W-02 | GLM-测试(独立会话B) | [包B] 与A包独立一致PASS | PASS | 是 |\n")
    (root / "llm-review-log.md").write_bytes(log.encode("utf-8"))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="eac_") as td:
        tdp = Path(td)

        # ---- 1. 合规基线全绿 + 报告头版本 ----
        base = tdp / "g1"
        make_base(base)
        p = run(str(base))
        if p.returncode != 0:
            fail(f"合规基线应 exit 0，实为 {p.returncode}:\n{p.stdout[-600:]}")
        elif "eval_artifacts_check.py v1.1" not in p.stdout:
            fail("报告头缺版本标识")
        elif any(row_level(p.stdout, f"Q-{i}") == "FAIL" for i in range(1, 10)):
            fail("合规基线出现 FAIL 行")
        else:
            ok("合规基线 exit 0 全绿 + 报告头版本标识")

        # ---- 2. 参数错误 ----
        p = run(str(tdp / "no-such-dir"))
        if p.returncode != 1 or "目录不存在" not in (p.stderr + p.stdout):
            fail(f"目录不存在应 exit 1 且有提示，实为 {p.returncode}")
        else:
            ok("目录不存在 → exit 1 + 下一步提示（fail-fast）")
        p = run(str(base), "--out", "   ")
        if p.returncode != 1 or "--out" not in (p.stderr + p.stdout):
            fail("--out 空串应 exit 1，实为 {p.returncode}")
        else:
            ok("--out 空串 → exit 1")

        # ---- 3. --out 落盘 ----
        rep = tdp / "rep" / "eac.md"
        p = run(str(base), "--out", str(rep))
        if p.returncode != 0 or not rep.is_file() \
                or "eval_artifacts_check.py v1.1" not in rep.read_text(encoding="utf-8"):
            fail("--out 未落盘或缺版本")
        else:
            ok("--out 报告落盘且含版本标识")

        # ---- 4. Q-1/Q-2 产物缺失 → SKIP 不计警告 ----
        empty = tdp / "g4"
        (empty / "workspace").mkdir(parents=True)
        p = run(str(empty))
        if p.returncode != 0 or row_level(p.stdout, "Q-1") != "SKIP" \
                or row_level(p.stdout, "Q-2") != "SKIP":
            fail(f"空产物目录应 exit 0 且 Q-1/Q-2 SKIP，实为 {p.returncode}")
        else:
            ok("产物缺失 → Q-1/Q-2 SKIP，exit 0（SKIP 不计警告）")

        # ---- 5. Q-1 条数不足 → FAIL ----
        d = tdp / "g5"
        make_base(d)
        write_json(d / "trigger-eval" / "queryset.json", mk_queryset(n_pos=5, n_neg=5))
        p = run(str(d))
        if p.returncode != 1 or row_level(p.stdout, "Q-1") != "FAIL" \
                or "条数 10" not in p.stdout:
            fail(f"条数不足应 FAIL exit 1，实为 {p.returncode}")
        else:
            ok("Q-1 条数 10 < 下限 12 → FAIL")

        # ---- 6. Q-1 配比错（12 条 7/5）----
        d = tdp / "g6"
        make_base(d)
        write_json(d / "trigger-eval" / "queryset.json", mk_queryset(n_pos=7, n_neg=5))
        p = run(str(d))
        if p.returncode != 1 or "配比 7/5" not in p.stdout:
            fail(f"配比 7/5 应 FAIL，实为 {p.returncode}")
        else:
            ok("Q-1 配比 7/5 ≠ 6/6（12 条口径）→ FAIL")

        # ---- 7. Q-1 非布尔 + id 重复 ----
        d = tdp / "g7"
        make_base(d)
        write_json(d / "trigger-eval" / "queryset.json",
                   mk_queryset(bad_bool_id="P03", dup_id=True))
        p = run(str(d))
        if p.returncode != 1 or "非布尔" not in p.stdout or "id 重复" not in p.stdout:
            fail(f"非布尔/重复 id 应 FAIL，实为 {p.returncode}")
        else:
            ok("Q-1 should_trigger 非布尔 + id 重复 → FAIL")

        # ---- 8. Q-1 必要字段缺失 ----
        d = tdp / "g8"
        make_base(d)
        write_json(d / "trigger-eval" / "queryset.json", mk_queryset(drop_field="query"))
        p = run(str(d))
        if p.returncode != 1 or "缺 query" not in p.stdout:
            fail(f"缺 query 字段应 FAIL，实为 {p.returncode}")
        else:
            ok("Q-1 必要字段缺失（query）→ FAIL")

        # ---- 9. Q-1 查询集 JSON 损坏 → FAIL（schema 错误区别于缺失 SKIP）----
        d = tdp / "g9"
        make_base(d)
        (d / "trigger-eval" / "queryset.json").write_bytes(b"{ not json")
        p = run(str(d))
        if p.returncode != 1 or row_level(p.stdout, "Q-1") != "FAIL" \
                or "解析失败" not in p.stdout:
            fail(f"JSON 损坏应 FAIL，实为 {p.returncode}")
        else:
            ok("Q-1 查询集 JSON 损坏 → FAIL（区别于缺失 SKIP）")

        # ---- 10. Q-2 --split 两路：缺文件 FAIL / 正常 PASS ----
        d = tdp / "g10"
        make_base(d)
        p = run(str(d), "--split", str(d / "t.json") + "," + str(d / "v.json"))
        if p.returncode != 1 or "切分文件不存在" not in p.stdout:
            fail(f"--split 缺文件应 FAIL，实为 {p.returncode}")
        else:
            ok("Q-2 --split 文件缺失 → FAIL")
        qs_items = mk_queryset()["queries"]
        tr = [it for it in qs_items if it["subset"] == "train"]
        va = [it for it in qs_items if it["subset"] == "validation"]
        write_json(d / "t.json", {"queries": tr})
        write_json(d / "v.json", {"queries": va})
        p = run(str(d), "--split", str(d / "t.json") + "," + str(d / "v.json"))
        flat = p.stdout.replace("，", ",")
        if p.returncode != 0:
            fail(f"--split 正常两文件应 PASS，实为 {p.returncode}:\n{p.stdout[-500:]}")
        elif "⊆ 全量" not in flat or "train 7/validation 5" not in flat:
            fail(f"--split PASS 证据缺关键串:\n{p.stdout[-500:]}")
        else:
            ok("Q-2 --split 显式切分文件存在且 ⊆ 全量 → PASS")

        # ---- 11. Q-2 哈希冻结不一致 → FAIL ----
        d = tdp / "g11"
        make_base(d)
        qsp = d / "trigger-eval" / "queryset.json"
        q = json.loads(qsp.read_bytes().decode("utf-8"))
        q["queries"][0]["query"] = "篡改后的查询。"
        write_json(qsp, q)  # 改了 queryset 但 frozen.sha256 未更新
        p = run(str(d))
        if p.returncode != 1 or "哈希冻结不一致" not in p.stdout:
            fail(f"哈希冻结不一致应 FAIL，实为 {p.returncode}")
        else:
            ok("Q-2 冻结哈希不一致（改集未换证）→ FAIL（只读校验）")

        # ---- 12. Q-2 validation 越出全量集 + 比例越带 ----
        d = tdp / "g12"
        make_base(d)
        write_json(d / "t.json", {"queries": tr + va[:3]})   # train 10
        write_json(d / "v.json", {"queries": va[3:] + [{"id": "X99", "subset": "validation"}]})  # val 3
        # train 占比 10/13 ≈ 77% 越出 60/40±5pp；X99 系全量集外 id
        p = run(str(d), "--split", str(d / "t.json") + "," + str(d / "v.json"))
        if p.returncode != 1 or "X99" not in p.stdout or "越出 60/40" not in p.stdout:
            fail(f"越集/比例越带应 FAIL，实为 {p.returncode}:\n{p.stdout[-400:]}")
        else:
            ok("Q-2 切分集 ⊆ 全量违反 + 60/40±5pp 越带 → FAIL")

        # ---- 13. Q-3 三态：SKIP / 缺字段 FAIL / 非数值 FAIL ----
        d = tdp / "g13"
        make_base(d)
        (d / "workspace" / "iteration-1" / "eval-a" / "with_skill" / "timing.json").unlink()
        p = run(str(d))
        if row_level(p.stdout, "Q-3") != "SKIP":
            fail("timing.json 缺失应 SKIP")
        else:
            ok("Q-3 timing.json 缺失 → SKIP")
        write_json(d / "workspace" / "iteration-1" / "eval-a" / "with_skill" / "timing.json",
                   {"total_tokens": 100})
        p = run(str(d))
        if p.returncode != 1 or "缺 duration_ms" not in p.stdout:
            fail("timing 缺 duration_ms 应 FAIL")
        else:
            ok("Q-3 timing.json 缺 duration_ms → FAIL")
        write_json(d / "workspace" / "iteration-1" / "eval-a" / "with_skill" / "timing.json",
                   {"total_tokens": "100", "duration_ms": True})
        p = run(str(d))
        if p.returncode != 1 or "非数值" not in p.stdout:
            fail("timing 非数值应 FAIL")
        else:
            ok("Q-3 timing.json 非数值（str/bool）→ FAIL")

        # ---- 14. Q-4 断言缺 evidence + summary 手填不符 ----
        d = tdp / "g14"
        make_base(d)
        gp = d / "workspace" / "iteration-1" / "eval-a" / "with_skill" / "grading.json"
        g = json.loads(gp.read_bytes().decode("utf-8"))
        del g["with_skill"]["assertions"][0]["evidence"]
        write_json(gp, g)
        p = run(str(d))
        if p.returncode != 1 or "缺 evidence" not in p.stdout:
            fail("断言缺 evidence 应 FAIL")
        else:
            ok("Q-4 断言缺 evidence → FAIL（§7.5.1 PASS 须附证据）")
        g = json.loads(gp.read_bytes().decode("utf-8"))
        g["with_skill"]["assertions"][0]["evidence"] = "补回证据（夹具）"
        g["with_skill"]["summary"]["passed"] = 3
        write_json(gp, g)
        p = run(str(d))
        if p.returncode != 1 or "重算不一致" not in p.stdout or "手填 3" not in p.stdout:
            fail("summary 手填不符应 FAIL")
        else:
            ok("Q-4 summary 与断言重算不一致（手填 passed=3）→ FAIL（§三.3 不吃手填）")

        # ---- 15. Q-5 缺组 / delta 非数值 ----
        d = tdp / "g15"
        make_base(d)
        bp = d / "workspace" / "iteration-1" / "eval-a" / "benchmark.json"
        b = json.loads(bp.read_bytes().decode("utf-8"))
        del b["without_skill"]
        write_json(bp, b)
        p = run(str(d))
        if p.returncode != 1 or "缺 without_skill" not in p.stdout:
            fail("benchmark 缺组应 FAIL")
        else:
            ok("Q-5 benchmark 缺 without_skill 组 → FAIL（§7.6.1 两组对照）")
        b["without_skill"] = {"pass_rate": 0.4, "time_seconds": 10.0, "tokens": 600}
        b["delta"] = {"pass_rate": "0.4"}
        write_json(bp, b)
        p = run(str(d))
        if p.returncode != 1 or "delta 非数值" not in p.stdout:
            fail("delta 非数值应 FAIL")
        else:
            ok("Q-5 delta 非数值（str）→ FAIL")
        # v1.0.1 评审 2.2：delta 空 dict 结构在场即可，不判缺失
        b["delta"] = {}
        write_json(bp, b)
        p = run(str(d))
        if row_level(p.stdout, "Q-5") != "PASS":
            fail("delta 空 dict 应 PASS（§7.6.1 只要求结构在场）")
        else:
            ok("Q-5 delta 空 dict → PASS（不判缺失）")

        # ---- 16. Q-6 正例恒挂 → WARN；退出码 2 ----
        d = tdp / "g16"
        make_base(d)
        rp = d / "trigger-eval" / "runs.json"
        r = json.loads(rp.read_bytes().decode("utf-8"))
        for e in r["runs"]:
            if e["query_id"] == "P01":
                e["loaded"] = False
        write_json(rp, r)
        p = run(str(d))
        if p.returncode != 2 or row_level(p.stdout, "Q-6") != "WARN" \
                or "恒挂" not in p.stdout or "P01" not in p.stdout:
            fail(f"正例恒挂应 WARN exit 2，实为 {p.returncode}")
        else:
            ok("Q-6 正例恒挂清单输出 → WARN（exit 2 契约）")

        # ---- 17. Q-7 离群 >3× 均值 → WARN；无样本 → SKIP ----
        d = tdp / "g17"
        make_base(d)
        rp = d / "trigger-eval" / "runs.json"
        r = json.loads(rp.read_bytes().decode("utf-8"))
        r["runs"][0]["total_tokens"] = 5000  # 其余 23 条为 100：均值=(5000+2300)/24≈304，5000 > 3×304
        write_json(rp, r)
        p = run(str(d))
        if row_level(p.stdout, "Q-7") != "WARN" or "3×均值" not in p.stdout:
            fail("离群 >3× 均值应 WARN")
        else:
            ok("Q-7 单次 token > 3× 均值 → WARN（§7.6.3）")
        e = tdp / "g17e"
        (e / "workspace").mkdir(parents=True)
        p = run(str(e))
        if row_level(p.stdout, "Q-7") != "SKIP":
            fail("无运行指标应 SKIP")
        else:
            ok("Q-7 无 ≥3 样本运行指标 → SKIP")

        # ---- 18. Q-8 留痕缺字段 → WARN；无留痕文件 → INFO ----
        d = tdp / "g18"
        make_base(d)
        lp = d / "llm-review-log.md"
        log = lp.read_bytes().decode("utf-8").replace(
            "| 2026-10-03 | W-02 | GLM-测试(独立会话A) | [包A] 五子维全PASS, 证据=SKILL.md L28 | PASS | 是 |",
            "|  | W-02 | GLM-测试(独立会话A) | [包A] 五子维全PASS, 证据=SKILL.md L28 | PASS |  |")
        lp.write_bytes(log.encode("utf-8"))
        p = run(str(d))
        if p.returncode != 2 or row_level(p.stdout, "Q-8") != "WARN" \
                or "日期缺失" not in p.stdout:
            fail(f"留痕缺日期/双评标记应 WARN，实为 {p.returncode}")
        else:
            ok("Q-8 留痕行缺日期与双评标记 → WARN（V12 必备字段）")
        d2 = tdp / "g18b"
        make_base(d2)
        (d2 / "llm-review-log.md").unlink()
        p = run(str(d2))
        if row_level(p.stdout, "Q-8") != "INFO":
            fail("无留痕文件应 INFO")
        else:
            ok("Q-8 无留痕文件 → INFO（未跑评审期属预期）")

        # ---- 19. Q-9 INFO 恒定（有/无工作区标志物）----
        p = run(str(base))
        if row_level(p.stdout, "Q-9") != "INFO":
            fail("Q-9 应恒 INFO")
        else:
            ok("Q-9 工作区对账恒 INFO（V25 信息供给不判 FAIL）")
        p = run(str(tdp / "g4"))
        if row_level(p.stdout, "Q-9") != "INFO":
            fail("空目录 Q-9 应 INFO")
        else:
            ok("Q-9 空产物目录亦 INFO（盘点如实呈现缺省）")

        # ---- 21. Q-2 train 越集（v1.0.1 Bug 1 回归）----
        d = tdp / "g21"
        make_base(d)
        write_json(d / "t.json", {"queries": tr + [{"id": "Y88", "subset": "train"}]})
        write_json(d / "v.json", {"queries": va})
        p = run(str(d), "--split", str(d / "t.json") + "," + str(d / "v.json"))
        # train 8/13≈62% 在带内，越集是唯一 FAIL 源
        if p.returncode != 1 or "train 含全量集外 id: Y88" not in p.stdout:
            fail(f"train 越集应 FAIL，实为 {p.returncode}:\n{p.stdout[-400:]}")
        else:
            ok("Q-2 train ⊆ 全量对称校验 → FAIL（v1.0.1 Bug 1 回归）")

        # ---- 22. Q-2 交集非空 → FAIL ----
        d = tdp / "g22"
        make_base(d)
        write_json(d / "t.json", {"queries": tr + va[:1]})
        write_json(d / "v.json", {"queries": va})
        p = run(str(d), "--split", str(d / "t.json") + "," + str(d / "v.json"))
        if p.returncode != 1 or "交集非空" not in p.stdout:
            fail(f"train/validation 交集非空应 FAIL，实为 {p.returncode}")
        else:
            ok("Q-2 train/validation 交集非空 → FAIL")

        # ---- 23. Q-2 --split 个数 ≠2 + frozen 幽灵条目 ----
        d = tdp / "g23"
        make_base(d)
        p = run(str(d), "--split", str(d / "t.json"))
        if p.returncode != 1 or "须为 train,val" not in p.stdout:
            fail("--split 单路径应 FAIL")
        else:
            ok("Q-2 --split 参数个数 ≠2 → FAIL")
        d2 = tdp / "g23b"
        make_base(d2)
        qsp = d2 / "trigger-eval" / "queryset.json"
        (d2 / "trigger-eval" / "frozen.sha256").write_bytes(
            (f"{hash_of(qsp)}  queryset.json\n{'f' * 64}  ghost.json\n").encode("utf-8"))
        p = run(str(d2))
        if p.returncode != 0 or "ghost.json" not in p.stdout:
            fail(f"frozen 幽灵条目应 PASS + 备注，实为 {p.returncode}")
        else:
            ok("Q-2 frozen.sha256 幽灵条目 → PASS + 证据备注（不误判）")

        # ---- 24. Q-4 无 assertions 数组 + 嵌套组 where 定位 ----
        d = tdp / "g24"
        make_base(d)
        gp = d / "workspace" / "iteration-1" / "eval-a" / "with_skill" / "grading.json"
        write_json(gp, {"with_skill": {"report": "r.md"}})
        p = run(str(d))
        if p.returncode != 1 or "无 assertions 数组" not in p.stdout:
            fail("grading 无 assertions 应 FAIL")
        else:
            ok("Q-4 grading.json 无 assertions 数组 → FAIL（§7.4.5）")
        write_json(gp, {"a": {"b": {"assertions": [
            {"text": "断言", "passed": True}]}}})
        p = run(str(d))
        if p.returncode != 1 or "缺 evidence" not in p.stdout or "a/b" not in p.stdout:
            fail(f"嵌套组应 FAIL 且 where 含 a/b，实为:\n{p.stdout[-400:]}")
        else:
            ok("Q-4 嵌套断言组 where 路径拼接（a/b）→ 定位准确（2.1 回归）")

        # ---- 25. Q-6 高摇摆 + 无查询集标注分支 ----
        d = tdp / "g25"
        make_base(d)
        rp = d / "trigger-eval" / "runs.json"
        r = json.loads(rp.read_bytes().decode("utf-8"))
        for e in r["runs"]:
            if e["query_id"] == "P01":
                e["loaded"] = e["run"] == 1  # P01: 1/2 → rate 0.5
        write_json(rp, r)
        p = run(str(d))
        if p.returncode != 2 or "高摇摆" not in p.stdout or "P01" not in p.stdout:
            fail(f"高摇摆应 WARN，实为 {p.returncode}")
        else:
            ok("Q-6 高摇摆（rate∈[0.4,0.6]）→ WARN 清单")
        d2 = tdp / "g25b"
        make_base(d2)
        (d2 / "trigger-eval" / "queryset.json").unlink()
        p = run(str(d2))
        # 无标注时恒过项不做正负归因、直接清单呈现（附 ×n 样本数）
        if p.returncode != 2 or "恒过" not in p.stdout or "×2" not in p.stdout:
            fail(f"无标注分支应 WARN 清单呈现（含样本数），实为 {p.returncode}:\n{p.stdout[-400:]}")
        else:
            ok("Q-6 无查询集标注 → 恒态清单呈现（不归因，附样本数）→ WARN")

        # ---- 26. Q-7 多池独立（timing 池离群，runs 池干净）----
        d = tdp / "g26"
        make_base(d)
        tp = d / "workspace" / "iteration-1" / "eval-a" / "with_skill" / "timing.json"
        write_json(tp, [{"total_tokens": 100, "duration_ms": 500}] * 4
                   + [{"total_tokens": 10000, "duration_ms": 500}])
        # timing 池 5 样本：均值 (400+10000)/5=2080，10000 > 3×2080 ✓（n=3 时
        # 数学上不可能超 3× 均值，须 ≥5 样本才能构成离群用例）
        p = run(str(d))
        if row_level(p.stdout, "Q-7") != "WARN" or "timing.json" not in p.stdout:
            fail("timing 池离群应 WARN 且独立于 runs 池")
        else:
            ok("Q-7 按来源分池：timing.json 池离群独立检出（runs 池干净）")

        # ---- 27. Q-8 证据过短 + 表头不识别静默 ----
        d = tdp / "g27"
        make_base(d)
        lp = d / "llm-review-log.md"
        log = lp.read_bytes().decode("utf-8").replace(
            "| [包A] 五子维全PASS, 证据=SKILL.md L28 |", "| ok |")
        lp.write_bytes(log.encode("utf-8"))
        p = run(str(d))
        if p.returncode != 2 or "证据缺失/过短" not in p.stdout:
            fail("证据过短应 WARN")
        else:
            ok("Q-8 输出证据 <8 字符 → WARN（Bug 2 回归：长列名在场）")
        d2 = tdp / "g27b"
        make_base(d2)
        (d2 / "llm-review-log.md").write_bytes(
            "# 无表格的日志\n\n普通段落，没有日期+判定表头。\n".encode("utf-8"))
        p = run(str(d2))
        if row_level(p.stdout, "Q-8") != "INFO":
            fail("表头不识别应静默走 INFO")
        else:
            ok("Q-8 表头不含日期+判定 → 静默跳过（INFO）")

        # ---- 28. Q-9 iteration-1 为文件形态 ----
        d = tdp / "g28"
        d.mkdir(parents=True)
        (d / "iteration-1").write_bytes(b"not a dir\n")
        p = run(str(d))
        if row_level(p.stdout, "Q-9") != "INFO" or "iteration-1" not in p.stdout:
            fail("iteration-1 文件形态应 INFO 且计入在场")
        else:
            ok("Q-9 标志物为文件（非目录）→ exists() 如实计入（2.4 回归）")

        # ---- 29. --queryset 显式指定 ----
        d = tdp / "g29"
        make_base(d)
        ext = tdp / "ext" / "qs-copy.json"
        write_json(ext, mk_queryset())
        p = run(str(d), "--queryset", str(ext))
        if p.returncode != 0 or "显式指定" not in p.stdout \
                or row_level(p.stdout, "Q-1") != "PASS":
            fail(f"--queryset 显式指定应 PASS，实为 {p.returncode}")
        else:
            ok("--queryset 显式指定路径 → Q-1 PASS + 报告头注明口径")

        # ---- 30. --min-count 20（全量口径）----
        p = run(str(base), "--min-count", "20")
        if p.returncode != 1 or "条数 12 < 下限 20" not in p.stdout:
            fail("--min-count 20 对 12 条集应 FAIL")
        else:
            ok("--min-count 20 全量口径 → 12 条集 FAIL（参数生效）")

        # ---- 30b. Q-6 多 runs.json 合并统计（v1.1 自查⑨回归）----
        d30b = tdp / "g30b"
        make_base(d30b)
        # 第二个 runs.json：P01 两次 loaded=False——合并后 P01 rate 2/4=0.5 → 高摇摆；
        # 若只取首个文件（旧实现），P01 恒过且按标注归因被过滤 → Q-6 PASS
        write_json(d30b / "workspace" / "runs.json",
                   {"runs": [{"query_id": "P01", "run": 1, "loaded": False,
                              "evidence": "第二份 runs 记录（夹具）",
                              "total_tokens": 100, "duration_ms": 500},
                             {"query_id": "P01", "run": 2, "loaded": False,
                              "evidence": "第二份 runs 记录（夹具）",
                              "total_tokens": 100, "duration_ms": 500}]})
        p = run(str(d30b))
        if p.returncode != 2 or "高摇摆" not in p.stdout \
                or "P01(×4" not in p.stdout:
            fail(f"多 runs.json 应合并统计（P01 ×4 摇摆），实为 exit={p.returncode}:\n"
                 + next((ln for ln in p.stdout.splitlines() if ln.startswith('| Q-6')), ''))
        ok("Q-6 多 runs.json 合并统计 → P01 ×4 高摇摆（v1.1 自查⑨回归）")
        # 合并口径下解析失败仍 FAIL
        (d30b / "workspace" / "runs.json").write_bytes(b"{broken\n")
        p = run(str(d30b))
        if p.returncode != 1 or row_level(p.stdout, "Q-6") != "FAIL":
            fail("任一 runs.json 解析失败应 FAIL")
        else:
            ok("Q-6 多 runs.json 任一解析失败 → FAIL")

        # ---- 31. 纪律源码断言 ----
        src = TOOL.read_text(encoding="utf-8")
        checks = [
            ("_BlockArgParser" in src and "def error" in src, "参数错误统一 exit 1 覆写"),
            ('encoding="utf-8-sig"' in src, "读码 utf-8-sig（BOM 容忍）"),
            ("is_symlink" in src, "is_symlink 前置"),
            ("_ev(" in src and 'replace("|", "｜")' in src, "证据净化（表格竖线/换行）"),
            ("SKIP" in src and "不计警告" in src, "SKIP 不计警告口径声明"),
        ]
        for cond, name in checks:
            (ok if cond else fail)(f"纪律源码断言: {name}")
        if _is_num_check(src):
            ok("纪律源码断言: 数值判定显式排除 bool")
        else:
            fail("纪律源码断言: 数值判定未排除 bool")

    return done()


def _is_num_check(src: str) -> bool:
    # 家族纪律：本字符串是 grep 锚——改动 eval_artifacts_check.py 中
    # _is_num 的写法前须同步此锚（否则断言静默失效）
    return "not isinstance(x, bool)" in src


if __name__ == "__main__":
    sys.exit(main())
