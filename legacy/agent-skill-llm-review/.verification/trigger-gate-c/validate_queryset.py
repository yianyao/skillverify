# C:/Users/yianyao/.workbuddy/binaries/python/versions/3.13.12/python.exe 结构校验（对齐总表 §6.2.1/§6.2.6/§6.2.7、§6.4.1）
import json
from pathlib import Path

base = Path("C:/Users/yianyao/.workbuddy/skills/agent-skill-llm-review/.verification/trigger-gate-c")
qs = json.loads((base / "queryset.json").read_text(encoding="utf-8-sig"))
items = qs["queries"]
errors = []

# §6.2.1: 20 条、正负 8-10
if len(items) != 20:
    errors.append(f"总数 {len(items)} != 20")
pos = [q for q in items if q["should_trigger"] is True]
neg = [q for q in items if q["should_trigger"] is False]
if not (8 <= len(pos) <= 10 and 8 <= len(neg) <= 10):
    errors.append(f"正负配比 {len(pos)}/{len(neg)} 超出 8-10 区间")

# §6.2.7: should_trigger 必须布尔（json 解析已保证类型，但要防写成字符串）
for q in items:
    if not isinstance(q["should_trigger"], bool):
        errors.append(f"{q['id']} should_trigger 非布尔")
    for k in ("id", "subset", "category", "query", "rationale", "dims", "context_features"):
        if k not in q or not q[k]:
            errors.append(f"{q['id']} 缺字段 {k}")

# §6.4.1/§6.2.6: 60/40 切分且比例保持
tr = [q for q in items if q["subset"] == "train"]
va = [q for q in items if q["subset"] == "validation"]
if len(tr) != 12 or len(va) != 8:
    errors.append(f"切分 {len(tr)}/{len(va)} != 12/8")
# §6.2.6：子集内正负比例必须与全集比例保持（全集 10/10 = 50/50）
overall_frac = len(pos) / len(items)
for name, grp in (("train", tr), ("validation", va)):
    p = sum(1 for q in grp if q["should_trigger"])
    n = len(grp) - p
    if abs(p / len(grp) - overall_frac) > 0.05:
        errors.append(f"{name} 子集配比 {p}正/{n}负 偏离全集 {overall_frac:.0%}")
    ids = [q["id"] for q in grp]
    if len(ids) != len(set(ids)):
        errors.append(f"{name} 存在重复 ID")

# 负例全部 near-miss（§6.2.4/6.2.5）：category 必须标注
for q in neg:
    if q["category"] != "negative-near-miss":
        errors.append(f"{q['id']} 负例未标 near-miss")

# ID 全局唯一
all_ids = [q["id"] for q in items]
if len(all_ids) != len(set(all_ids)):
    errors.append("全局 ID 重复")

if errors:
    print("FAIL")
    for e in errors:
        print(" -", e)
    raise SystemExit(1)

print(f"PASS: 20 条 = {len(pos)} 正 + {len(neg)} 负；train {len(tr)}（{sum(1 for q in tr if q['should_trigger'])}正/{len(tr)-sum(1 for q in tr if q['should_trigger'])}负）+ validation {len(va)}（{sum(1 for q in va if q['should_trigger'])}正/{len(va)-sum(1 for q in va if q['should_trigger'])}负）；全部字段齐备、负例全 near-miss、ID 唯一")
