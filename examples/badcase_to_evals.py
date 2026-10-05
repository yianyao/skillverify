"""badcase_to_evals.py —— 把线上遇到的坏例子回流成一条评测用例

这是**样例模板**，不是工具的一部分：本工具不自研执行器（执行层委托官方工具/宿主），
所以把"怎么委托"写成可以照抄改的脚本。纯标准库、Python ≥3.10。

**它做什么 / 不做什么**（别指望它替你判断质量）：
- 做：往 `evals/evals.json` **追加**一条用例（自动分配 id、默认把断言留空并提示你补），改完立刻用同样的口径做一次自检（结构、断言非空洞）；
- 不做：不替你写断言——断言是这条用例的价值所在，写"输出是好的"等于没有用例。
- 用法：
```bash
python examples/badcase_to_evals.py --skill .agents/skills/csv-report \
    --prompt "把这份表按月汇总" --expected "按月汇总的表" \
    --assertion "输出含 month 与 total 两列"
```

"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VAGUE = ("输出是好的", "结果正确", "符合预期", "没问题")


def main() -> int:
    parser = argparse.ArgumentParser(description="把 bad case 追加成一条评测用例")
    parser.add_argument("--skill", required=True, help="技能目录")
    parser.add_argument("--prompt", required=True, help="用户会怎么说（照原话抄）")
    parser.add_argument("--expected", required=True, help="期望输出的描述")
    parser.add_argument("--assertion", action="append", default=None,
                        help="可判定的断言（可重复；不写会提醒你补）")
    parser.add_argument("--files", action="append", default=None,
                        help="这条用例的输入素材（相对技能目录，可重复）")
    parser.add_argument("--dry-run", action="store_true", help="只打印要追加什么，不写盘")
    args = parser.parse_args()

    skill = Path(args.skill).resolve()
    path = skill / "evals" / "evals.json"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    evals = data.setdefault("evals", [])
    ids = [e.get("id") for e in evals if isinstance(e, dict)]
    next_id = (max([i for i in ids if isinstance(i, int)], default=0) + 1)

    assertions = list(args.assertion or [])
    vague = [a for a in assertions if any(v in a for v in VAGUE)]
    entry = {"id": next_id, "prompt": args.prompt, "expected_output": args.expected,
             "files": list(args.files or []), "assertions": assertions}

    if args.dry_run:
        print(f"[dry-run] 会往 {path} 追加：")
        print(json.dumps(entry, ensure_ascii=False, indent=2))
        return 0

    evals.append(entry)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    print(f"已追加 eval #{next_id}（{path}）")
    if not assertions:
        print("⚠ 这条用例还没有断言：没有断言的用例无法判定，请补上"
              "（例：「输出含 month 与 total 两列」）", file=sys.stderr)
    if vague:
        print(f"⚠ 这些断言太笼统，机械层会判为空洞：{vague}", file=sys.stderr)
    print(f"下一步：`skillverify evals {skill}` 校验形状；"
          f"真有价值就顺手补进 trigger-queryset.json 的负例")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
