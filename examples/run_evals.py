"""run_evals.py —— 双臂（with/without skill）各跑一遍并记下 timing.json

这是**样例模板**，不是工具的一部分：本工具不自研执行器（执行层委托官方工具/宿主），
所以把"怎么委托"写成可以照抄改的脚本。纯标准库、Python ≥3.10。

**它做什么 / 不做什么**（别指望它替你判断质量）：
- 做：按 `<技能名>-workspace/iteration-N/eval-*/{with_skill,without_skill}/` 的官方布局
  建目录、跑你给的命令、把输出写进 `outputs/`、把**实测**耗时与 token 记进 `timing.json`；
- 不做：**不评分**。断言通不通要人或 LLM 判断（见提示词 `E-04`），本脚本只把可测的那半测掉。
- 用法：
```bash
python examples/run_evals.py --skill .agents/skills/csv-report \
    --cmd "python wrap.py --arm {arm} --prompt \"{prompt}\""   # {prompt} 与 {arm} 会被替换
skillverify evals .agents/skills/csv-report --json   # 跑完再让工具校验产物
```

**`{arm}` 必须写**（这是本脚本最容易踩的坑）：两臂**唯一**的差别就靠它实现——
Claude CLI 路线在 `without_skill` 时加 `--disallowedTools Skill`，裸 API 路线在 `with_skill`
时把 `SKILL.md` 注入 prompt。命令里没有 `{arm}` 时，两臂跑的**是同一条命令**，实验不成立
（脚本会直接拒绝并退 2；确有必要用工作目录区分时，显式加 `--allow-same-cmd`）。
夹具不在这里替换：按官方布局在 `prompt` 里用相对路径引用（如 `evals/files/input.csv`）。

"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ARMS = ("with_skill", "without_skill")


def load_evals(skill: Path) -> list[dict]:
    path = skill / "evals" / "evals.json"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return [e for e in data.get("evals", []) if isinstance(e, dict)]


def run_arm(cmd: str, ev: dict, arm: str, work: Path, dry_run: bool) -> dict:
    """跑一条用例的一个臂，返回 timing 记录。`--dry-run` 只打印不执行。"""
    outputs = work / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    prompt = str(ev.get("prompt", ""))
    if dry_run:
        print(f"  [dry-run] {arm}: {prompt[:60]}")
        return {"total_tokens": 0, "duration_ms": 0, "dry_run": True}
    command = cmd.replace("{prompt}", prompt).replace("{arm}", arm)
    started = time.monotonic()
    proc = subprocess.run(command, shell=True, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    elapsed_ms = int((time.monotonic() - started) * 1000)
    (outputs / f"{arm}.md").write_text(proc.stdout or "", encoding="utf-8", newline="\n")
    # token 数只有你的执行器知道：能报就报（这里从 stderr 里找 `tokens: N` 这种一行）
    tokens = 0
    for line in (proc.stderr or "").splitlines():
        if "tokens:" in line:
            tail = line.split("tokens:", 1)[1].strip().split()[0]
            tokens = int(tail) if tail.isdigit() else 0
    return {"total_tokens": tokens, "duration_ms": elapsed_ms, "exit_code": proc.returncode}


def main() -> int:
    parser = argparse.ArgumentParser(description="双臂跑评测并记录 timing（不评分）")
    parser.add_argument("--skill", required=True, help="技能目录（含 SKILL.md 与 evals/）")
    parser.add_argument("--cmd", required=True,
                        help="执行一条用例的命令；可用 {prompt} / {arm} 占位")
    parser.add_argument("--iteration", type=int, default=1, help="写到第几轮（默认 1）")
    parser.add_argument("--eval-id", help="只跑指定用例 id（默认全部）")
    parser.add_argument("--workspace", help="工作区目录（默认技能目录的兄弟目录）")
    parser.add_argument("--dry-run", action="store_true", help="只打印要跑什么，不执行、不写盘")
    parser.add_argument("--allow-same-cmd", action="store_true",
                        help="允许 cmd 里不写 {arm}（两臂命令将完全相同；只在你的命令"
                             "靠工作目录等其它方式区分两臂时才用）")
    args = parser.parse_args()

    # 巨坑守卫：cmd 里没有 {arm} → 两臂命令逐字相同，A/B 对照在结构上不成立。
    # 早先的版本"不报错、不警告、照跑不误，产物布局也完整"——看起来一切正常，实验已经废了。
    if "{arm}" not in args.cmd and not args.allow_same_cmd:
        print("FAIL: --cmd 里没有 {arm} 占位符——两臂会跑同一条命令，A/B 对照不成立。\n"
              "      两臂唯一的差别必须由 {arm} 实现：\n"
              "        Claude CLI 路线：arm==without_skill 时加 --disallowedTools Skill\n"
              "        裸 API 路线：arm==with_skill 时把 SKILL.md 注入 prompt\n"
              "      确有必要靠工作目录等其它方式区分两臂，再加 --allow-same-cmd。",
              file=sys.stderr)
        return 2
    if "{arm}" not in args.cmd:
        print("警告：--allow-same-cmd 已开——两臂命令逐字相同，只有当你的命令能靠工作目录"
              "等其它方式区分两臂时，这轮实验才有意义。", file=sys.stderr)

    skill = Path(args.skill).resolve()
    ws = Path(args.workspace) if args.workspace else (skill.parent / f"{skill.name}-workspace")
    iteration = ws / f"iteration-{args.iteration}"
    evals = load_evals(skill)
    if args.eval_id:
        evals = [e for e in evals if str(e.get("id")) == str(args.eval_id)]
    if not evals:
        print(f"没有可跑的用例（看了 {skill / 'evals' / 'evals.json'}）", file=sys.stderr)
        return 1

    print(f"技能 {skill.name}｜用例 {len(evals)} 条｜工作区 {iteration}")
    for index, ev in enumerate(evals, 1):
        eval_dir = iteration / f"eval-{ev.get('id', index)}"
        for arm in ARMS:
            timing = run_arm(args.cmd, ev, arm, eval_dir / arm, args.dry_run)
            if not args.dry_run:
                (eval_dir / arm / "timing.json").write_text(
                    json.dumps(timing, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
                print(f"  eval-{ev.get('id', index)}/{arm}: {timing['duration_ms']} ms"
                      f"（tokens {timing['total_tokens']}）")
    if args.dry_run:
        print("（dry-run：什么都没写）")
        return 0
    print()
    print("下一步：给每个 outputs/ 评分并写 grading.json（断言是否通过要人来判），")
    print(f"然后用 `skillverify evals {skill}` 校验产物——本脚本不替你打分。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
