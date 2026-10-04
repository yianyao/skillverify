#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_suite.py — Agent-Skill 生命周期验证分阶段调度器（v1.0）

所属技能: agent-skill-validation-suite（实测编排）。
职责: 按"设计/编写/测试/交付"四阶段自动选择并调用 specSkill 脚本工具链,
      集成官方校验器 agentskills validate(即 PyPI 官方包 skills-ref 0.1.1 的
      CLI 入口; npm 同名包系第三方占用,勿用),汇总各步判定输出报告。

阶段与工具映射(详见 references/lifecycle-map.md):
  design  命名冲突预检(naming_precheck/V2)
  write   格式门 A(check_skill) + 安全扫描(V8/security_scan) + 上下文预算(V11/V17/token_budget)
          + 依赖检测(DEP/dep_check) + 静态补检(L-1~L-18/w_static_lint) + 官方校验(agentskills validate)
  test    脚本冒烟(V6/smoke_runner) + 加载注入(V23/inject_test) + 评测纪律 check(V21/V28/V29/eval_discipline)
          + 评测产物校验(Q-1~Q-9/eval_artifacts_check)
  deliver 上列全部 + 交付物检查(EX/deliver_check) + 关键词定位(kw_locator/B3-1) —— 等价验收全门复扫
  auto    按技能目录产物自动判阶段(无 evals/evals.json -> write; 否则 deliver 复扫)

判定口径(重要): 本调度器只做"调齐工具 + 汇总报告",判定结论供人工复核;
      依仓库纪律,编排器不得仅凭退出码作验收阻断。退出码约定:
      0=所选阶段全部 PASS; 1=有 FAIL(或参数/环境错误); 2=无 FAIL 但有 WARN/SKIP。

家族纪律: 退出码 0/1/2; 参数错误一律 stderr+用法+exit 1(_BlockArgParser);
      无交互、无隐式副作用; VERSION 常量 + 报告头版本标识。

用法:
  python validate_suite.py --stage design --name my-skill --description "一句话"
  python validate_suite.py --stage write  --skill-dir <技能目录>
  python validate_suite.py --stage test   --skill-dir <技能目录>
  python validate_suite.py --stage deliver --skill-dir <技能目录>
  python validate_suite.py --stage auto   --skill-dir <技能目录>
  可选: --tools-dir <specSkill tools 目录>(默认自动探测) --out <报告.md>
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

VERSION = "v1.1"  # v1.1: 挂载甲档两新工具(write+w_static_lint / test+eval_artifacts_check)——验证补全工程任务书第 4 步

# 工具链探测顺序: 环境变量 > 脚本相对位置(设计库内) > 设计库绝对路径(宿主部署副本场景)
_DEFAULT_LIB = Path("D:/sData/specSkill")
_REL_TOOLS = Path(__file__).resolve().parent.parent.parent / "tools"


def fail(msg):
    """fail-fast: 打印错误 + 用法到 stderr 后 exit 1(族惯例,非 try/except 容错)。"""
    print(f"FAIL: {msg}", file=sys.stderr)
    print("用法: python validate_suite.py --stage <design|write|test|deliver|auto> "
          "[--skill-dir <目录> | --name <n> --description <d>] [--tools-dir <目录>] [--out <报告.md>]",
          file=sys.stderr)
    sys.exit(1)


class _BlockArgParser(argparse.ArgumentParser):
    """族纪律: 参数错误统一 exit 1(覆盖 argparse 默认 exit 2,避免撞 WARN 码)。"""

    def error(self, message):
        fail(f"参数错误: {message}")


def find_tools_dir(override):
    """定位 specSkill/tools 目录;找不到 fail-loud,不静默降级。"""
    cands = []
    if override:
        cands.append(Path(override))
    if os.environ.get("SPEC_SKILL_TOOLS"):
        cands.append(Path(os.environ["SPEC_SKILL_TOOLS"]))
    cands += [_REL_TOOLS, _DEFAULT_LIB / "tools"]
    for c in cands:
        if (c / "check_skill.py").is_file():
            return c.resolve()
    fail("未找到 specSkill 工具链(需含 check_skill.py): "
         "用 --tools-dir 指定,或设环境变量 SPEC_SKILL_TOOLS,或确认设计库在 " + str(_DEFAULT_LIB))


def find_official_cli():
    """探测官方校验器 agentskills(兼容 check_skill.find_official_cli 的入口名口径)。

    返回 (可执行路径或 None, 说明文本)。npm 同名包系第三方占用,只认官方入口名。
    """
    exe = shutil.which("agentskills")
    if exe:
        return exe, "PATH 命中 agentskills"
    venv_scripts = Path.home() / ".workbuddy/binaries/python/envs/default/Scripts"
    cand = venv_scripts / ("agentskills.exe" if os.name == "nt" else "agentskills")
    if cand.is_file():
        return str(cand), f"托管 venv 命中: {cand}"
    return None, "未探测到 agentskills(官方包 skills-ref 0.1.1 的 CLI);该步 SKIP 不计警告"


def run_step(title, cmd, cwd=None, timeout=300):
    """执行单步,返回 {title, cmd, code, verdict, tail}。tail 取输出尾部防刷屏。

    cmd[0] == "__skip__" 为合成跳过步(如官方 CLI 缺位): 不执行,SKIP 不计警告。
    """
    if str(cmd[0]) == "__skip__":
        return {"title": title, "cmd": "(skip)", "code": "-", "verdict": "SKIP(不计警告)",
                "tail": str(cmd[1])}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=cwd, timeout=timeout)
        code = p.returncode
        out = (p.stdout or "") + (("\n[stderr] " + p.stderr) if p.stderr.strip() else "")
    except subprocess.TimeoutExpired:
        code, out = 1, f"[超时 {timeout}s]"
    except OSError as e:
        code, out = 1, f"[执行失败] {e}"
    verdict = {0: "PASS", 2: "WARN/SKIP"}.get(code, "FAIL")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    tail = "\n".join(lines[-12:]) if lines else "(无输出)"
    return {"title": title, "cmd": " ".join(str(c) for c in cmd), "code": code,
            "verdict": verdict, "tail": tail}


# ---- 阶段 -> 工具步清单 -------------------------------------------------------

def steps_design(tools, lib, name, desc):
    return [("设计期·命名冲突预检（V2：同名/描述相似度）",
             [sys.executable, str(tools / "naming_precheck.py"),
              "--name", name, "--description", desc, "--library", str(lib)])]


def steps_write(tools, skill_dir, cli):
    steps = [
        ("编写期·格式门 A（check_skill：frontmatter/目录/预算预警等 11 组）",
         [sys.executable, str(tools / "check_skill.py"), str(skill_dir)]),
        ("编写期·安全扫描（V8：密钥/端点/交互/危险操作六项）",
         [sys.executable, str(tools / "security_scan.py"), str(skill_dir)]),
        ("编写期·上下文预算门（V11/V17：token/行数预算）",
         [sys.executable, str(tools / "token_budget.py"), str(skill_dir)]),
        ("编写期·依赖检测（DEP-1~5：钉版本/内联声明）",
         [sys.executable, str(tools / "dep_check.py"), str(skill_dir)]),
        ("编写期·静态补检（L-1~L-18：全包卫生/引用链二层/i18n/恶意初筛）",
         [sys.executable, str(tools / "w_static_lint.py"), str(skill_dir)]),
    ]
    if cli:
        steps.append(("编写期·官方校验（agentskills validate，Anthropic 官方解析器）",
                      [cli, "validate", str(skill_dir)]))
    else:
        steps.append(("编写期·官方校验（agentskills validate）——SKIP",
                      ["__skip__",
                       "未探测到官方 CLI，SKIP 不计警告；安装口径见 验证操作总说明书.md §8"]))
    return steps


def steps_test(tools, skill_dir):
    steps = []
    scripts = sorted((skill_dir / "scripts").glob("*.py")) if (skill_dir / "scripts").is_dir() else []
    if scripts:
        steps.append(("测试期·脚本冒烟（V6：--help/缺参/版本/退出码/限量）",
                      [sys.executable, str(tools / "smoke_runner.py"),
                       "--scripts"] + [str(s) for s in scripts]))
    else:
        steps.append(("测试期·脚本冒烟（V6）——SKIP", ["__skip__", "技能无 scripts/ 目录，无可冒烟脚本（不计警告）"]))
    steps += [
        ("测试期·加载注入（V23：坏 frontmatter 须 fail-loud）",
         [sys.executable, str(tools / "inject_test.py"), str(skill_dir)]),
        ("测试期·评测纪律 check（V21 先写后测 / V28 写回一致 / V29 基线）",
         [sys.executable, str(tools / "eval_discipline.py"), str(skill_dir)]),
    ]
    # v1.1: 甲档工具二挂载——产物目录缺位走合成跳过步（SKIP 不计警告，口径同冒烟）
    vd = skill_dir / ".verification"
    if vd.is_dir():
        steps.append(("测试期·评测产物校验（Q-1~Q-9：queryset/切分/grading/benchmark/留痕）",
                      [sys.executable, str(tools / "eval_artifacts_check.py"), str(vd)]))
    else:
        steps.append(("测试期·评测产物校验（Q-1~Q-9）——SKIP",
                      ["__skip__", "技能无 .verification/ 产物目录（未跑评测期，不计警告）"]))
    return steps


def steps_deliver(tools, skill_dir, lib, cli):
    return (steps_write(tools, skill_dir, cli)
            + steps_test(tools, skill_dir)
            + [
                ("交付期·命名预检复扫（V2）",
                 [sys.executable, str(tools / "naming_precheck.py"), str(skill_dir),
                  "--library", str(lib)]),
                ("交付期·交付物检查（EX-1~7：验收报告/license/留痕在场）",
                 [sys.executable, str(tools / "deliver_check.py"), str(skill_dir)]),
                ("交付期·危险关键词定位（B3-1，信息供给非门禁）",
                 [sys.executable, str(tools / "kw_locator.py"), str(skill_dir)]),
            ])


def detect_stage(skill_dir):
    """auto: 按产物判阶段。无 SKILL.md -> 提示 design;无 evals.json -> write;否则 deliver 复扫。"""
    if not (skill_dir / "SKILL.md").is_file():
        fail(f"{skill_dir} 下无 SKILL.md——若尚在命名阶段,请用 --stage design --name <n> --description <d>")
    if not (skill_dir / "evals" / "evals.json").is_file():
        return "write", "未检出 evals/evals.json -> 判为编写期"
    return "deliver", "已检出编写期产物 -> 判为交付期全门复扫"


def build_report(header, steps, stage_note):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# 生命周期验证报告（{header['stage']} 阶段）",
        "",
        f"- 执行者: agent-skill-validation-suite {VERSION}（validate_suite.py）",
        f"- 时间: {now} ｜ 对象: {header['target']}",
        f"- 阶段判定: {stage_note}",
        "- 口径: 本报告为工具判定汇总,供人工复核;验收阻断须结合人工终审(仓库纪律:编排器不得仅凭退出码作验收阻断)。",
        "",
        "| # | 步骤 | 退出码 | 判定 |",
        "|---|---|---|---|",
    ]
    for i, s in enumerate(steps, 1):
        lines.append(f"| {i} | {s['title']} | {s['code']} | {s['verdict']} |")
    lines += ["", "## 各步输出尾部", ""]
    for s in steps:
        lines += [f"### {s['title']}", "", f"```", s["tail"], "```", ""]
    n_fail = sum(1 for s in steps if s["verdict"] == "FAIL")
    n_warn = sum(1 for s in steps if s["verdict"] == "WARN/SKIP")
    lines += ["## 判定统计", "",
              f"- FAIL 步: {n_fail} ｜ WARN/SKIP 步: {n_warn} ｜ 总步: {len(steps)}",
              "- 下一步: FAIL 步按报告证据修复后重跑;WARN 步逐条人工甄别;"
              "交付阶段全过后按 验证操作总说明书.md §4 落验收报告并人工终审。"]
    return "\n".join(lines) + "\n"


def main():
    ap = _BlockArgParser(add_help=True, description="Agent-Skill 生命周期验证分阶段调度器")
    ap.add_argument("--stage", required=True,
                    choices=["design", "write", "test", "deliver", "auto"])
    ap.add_argument("--skill-dir")
    ap.add_argument("--name")
    ap.add_argument("--description")
    ap.add_argument("--library", help="设计期排重库(默认 specSkill 设计库根)")
    ap.add_argument("--tools-dir")
    ap.add_argument("--out")
    args = ap.parse_args()

    if args.stage == "design":
        if not args.name or not args.description:
            fail("design 阶段须同时提供 --name 与 --description")
        if args.skill_dir:
            fail("design 阶段不需要 --skill-dir(尚未建目录)")
    else:
        if not args.skill_dir:
            fail(f"{args.stage} 阶段须提供 --skill-dir")
        if args.name or args.description:
            fail(f"{args.stage} 阶段不需要 --name/--description")
        sd = Path(args.skill_dir)
        if not sd.is_dir():
            fail(f"技能目录不存在: {sd}")
        args.skill_dir = str(sd.resolve())

    tools = find_tools_dir(args.tools_dir)
    lib = Path(args.library).resolve() if args.library else tools.parent
    cli, cli_note = find_official_cli()

    if args.stage == "auto":
        stage, note = detect_stage(Path(args.skill_dir))
    else:
        stage, note = args.stage, "显式指定"

    if stage == "design":
        steps = steps_design(tools, lib, args.name, args.description)
        target = f"(拟建) {args.name}"
    else:
        sd = Path(args.skill_dir)
        if stage == "write":
            steps = steps_write(tools, sd, cli)
        elif stage == "test":
            steps = steps_test(tools, sd)
        else:
            steps = steps_deliver(tools, sd, lib, cli)
        target = str(sd)

    header = {"stage": stage, "target": target}
    results = [run_step(t, c) for t, c in steps]
    report = build_report(header, results, f"{note}；官方 CLI: {cli_note}")

    if args.out:
        out = Path(args.out)
        if not args.out.strip() or not out.parent.is_dir():
            fail(f"--out 路径非法或父目录不存在: {args.out}")
        out.write_text(report, encoding="utf-8", newline="\n")
        print(f"报告已落盘: {out}")

    n_fail = sum(1 for s in results if s["verdict"] == "FAIL")
    n_warn = sum(1 for s in results if s["verdict"] == "WARN/SKIP")
    print(f"validate_suite {VERSION}: stage={stage} 目标={target} "
          f"FAIL={n_fail} WARN/SKIP={n_warn} 总步={len(results)}")
    sys.exit(1 if n_fail else (2 if n_warn else 0))


if __name__ == "__main__":
    main()
