"""run_triggers.py —— 把触发查询集真跑一遍并落盘 trigger-runs.json

这是**样例模板**，不是工具的一部分：本工具不自研执行器（执行层委托官方工具/宿主），
所以把"怎么委托"写成可以照抄改的脚本。纯标准库、Python ≥3.10。

**它做什么 / 不做什么**（别指望它替你判断质量）：
- 做：读 `evals/trigger-queryset.json`，对每条查询调用你给的命令，让它只回答 `yes`/`no`（该技能的 description 会不会被这条话触发），把结果写成官方约定的
  `evals/trigger-runs.json`（每条查询默认跑 3 次）；
- 不做：不替你挑模型、不判断答案对不对——它只是把"跑过"这件事变成产物。
- 用法：
```bash
python examples/run_triggers.py --skill .agents/skills/csv-report \
    --cmd "claude -p \"只回答 yes 或 no：以下描述会被触发吗？描述={description} 查询={query}\""
skillverify evals .agents/skills/csv-report    # 跑完校验口径
```

"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

YES = re.compile(r"\byes\b|^是", re.I)
NO = re.compile(r"\bno\b|^否", re.I)


def description_of(skill: Path) -> str:
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.lower().startswith("description:"):
            return line.split(":", 1)[1].strip()
    return ""


def ask(cmd: str, description: str, query: str) -> tuple[bool | None, str]:
    """返回 (是否触发, 证据)。命令输出里第一个 yes/no 决定结果。

    **边界（照抄前先读）**：`--cmd` 是**你自己提供的**命令串，这里交给 shell 执行，
    且 `{description}` / `{query}` 是**直接插值**、不做转义。所以：只喂你信任的命令串，
    别把外部输入拼进 `--cmd`。它是样例模板、不是沙箱——脚本内容有副作用也一样会执行。
    """
    command = (cmd.replace("{description}", description).replace("{query}", query)
               .replace("{skill_dir}", str(skill_dir)))
    # shell=True 是刻意的：要支持使用者给的任意命令行（含管道/重定向）。
    # 代价见上面 docstring 的边界说明。
    proc = subprocess.run(command, shell=True, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    first = out.splitlines()[0].strip() if out else ""
    if YES.search(first):
        return True, first[:120]
    if NO.search(first):
        return False, first[:120]
    return None, f"回答无法解析（首行: {first[:80]!r}）"


skill_dir = Path(".")


def main() -> int:
    global skill_dir
    parser = argparse.ArgumentParser(description="触发集执行器：真跑一遍查询并落盘运行记录")
    parser.add_argument("--skill", required=True, help="技能目录")
    parser.add_argument("--cmd", required=True,
                        help="判定命令；可用 {description} / {query} / {skill_dir} 占位")
    parser.add_argument("--runs", type=int, default=3, help="每条查询跑几次（默认 3）")
    parser.add_argument("--out", help="运行记录路径（默认 <技能>/evals/trigger-runs.json）")
    parser.add_argument("--dry-run", action="store_true", help="只打印要跑什么，不执行、不写盘")
    args = parser.parse_args()

    skill_dir = Path(args.skill).resolve()
    queryset = json.loads((skill_dir / "evals" / "trigger-queryset.json")
                          .read_text(encoding="utf-8-sig"))
    queries = [q for q in queryset.get("queries", []) if isinstance(q, dict)]
    description = description_of(skill_dir)
    if not description:
        print("SKILL.md 里找不到 description —— 触发评测的前提就是它", file=sys.stderr)
        return 1

    runs: list[dict] = []
    unparsed = 0
    for item in queries:
        qid, query = str(item.get("id")), str(item.get("query", ""))
        for run in range(1, args.runs + 1):
            if args.dry_run:
                print(f"  [dry-run] {qid} run{run}: {query[:50]}")
                continue
            loaded, evidence = ask(args.cmd, description, query)
            if loaded is None:
                unparsed += 1
                print(f"  ⚠ {qid} run{run}: {evidence}", file=sys.stderr)
            runs.append({"query_id": qid, "run": run, "loaded": bool(loaded),
                         "evidence": evidence})
    if args.dry_run:
        print(f"（dry-run：{len(queries)} 条 × {args.runs} 次，什么都没写）")
        return 0

    target = Path(args.out) if args.out else (skill_dir / "evals" / "trigger-runs.json")
    target.write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8", newline="\n")
    print(f"已写 {target}（{len(runs)} 条运行记录）")
    if unparsed:
        print(f"注意：{unparsed} 条回答无法解析（已按未触发记）——换更严格的提示词再跑",
              file=sys.stderr)
    print(f"下一步：`skillverify evals {skill_dir}` 校验触发率是否达标")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
