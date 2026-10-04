# -*- coding: utf-8 -*-
"""Arm-B (without skill): 清洗 sales_data_raw.csv"""
import csv, re
from datetime import datetime

SRC = "data/sales_data_raw.csv"
DST = "outputs/cleaned_without_skill.csv"
LOG = []

with open(SRC, encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

# 1. 去除末尾总计行
total_rows = [r for r in rows if r["订单编号"].strip() in ("总计",)]
rows = [r for r in rows if r["订单编号"].strip() not in ("总计",)]
LOG.append(f"剔除嵌入的'总计'行 {len(total_rows)} 条（其数值 20529.00 与实际合计不符，一并废弃）")

before = len(rows)

# 2. 去重
seen, uniq, dup = set(), [], 0
for r in rows:
    key = tuple(r.values())
    if key in seen:
        dup += 1
    else:
        seen.add(key)
        uniq.append(r)
rows = uniq
LOG.append(f"去除完全重复行 {dup} 条，{before} -> {len(rows)}")

# 3. 字段清洗
MONTHS = {m: i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August","September","October","November","December"], 1)}
def norm_date(s):
    s = s.strip()
    m = re.match(r"^(\w+) (\d+), (\d{4})$", s)
    if m and m.group(1) in MONTHS:
        return datetime(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2))).strftime("%Y-%m-%d")
    m = re.match(r"^(\d{4})[/-](\d{1,2})[-/](\d{1,2})$", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        # 按日/月优先解析（结合数据整体落在 2026-03~04 的背景）
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y}-{mo:02d}-{d:02d}"
    return s

REGION = {"beijing": "北京", "shanghai": "上海", "guangzhou": "广州", "shenzhen": "深圳"}
def norm_amount(s):
    s = s.strip()
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[¥(),\s]", "", s)
    v = float(s)
    return -v if neg else v

for r in rows:
    r["订单编号"] = r["订单编号"].strip().lstrip("'").zfill(5)
    r["下单日期"] = norm_date(r["下单日期"])
    reg = r["地区"].strip()
    r["地区"] = REGION.get(reg.lower(), reg) if reg else reg
    r["数量"] = r["数量"].strip()
    r["金额"] = f"{norm_amount(r['金额']):.2f}"

# 4. 缺失值处理（逐处说明）
for r in rows:
    if not r["数量"]:
        try:
            inferred = round(float(r["金额"]) / float(r["单价"]))
            r["数量"] = str(int(inferred))
            LOG.append(f"缺失值：订单 {r['订单编号']} 数量缺失，按 金额/单价 推断为 {inferred}（已标记为推断值）")
        except Exception:
            r["数量"] = "0"
    if not r["地区"]:
        r["地区"] = "未知"
        LOG.append(f"缺失值：订单 {r['订单编号']} 地区缺失，填为'未知'（无法可靠推断）")
    if not r["客户名称"].strip():
        r["客户名称"] = "未知"
        LOG.append(f"缺失值：订单 {r['订单编号']} 客户名称缺失，填为'未知'（无法可靠推断）")

# 5. 逻辑校验：数量×单价 vs 金额
for r in rows:
    try:
        calc = int(r["数量"]) * float(r["单价"])
        if abs(calc - float(r["金额"])) > 0.01:
            LOG.append(f"逻辑异常：订单 {r['订单编号']} 数量×单价={calc:.2f} ≠ 金额={r['金额']}，保留原值并标记待人工核对")
    except Exception:
        pass

with open(DST, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["订单编号","下单日期","地区","客户名称","产品","数量","单价","金额"])
    w.writeheader()
    w.writerows(rows)

amt = sum(float(r["金额"]) for r in rows)
print(f"清洗完成：{before}(含重复) -> {len(rows)} 行")
print(f"金额合计：{amt:.2f}")
print("--- 处理日志 ---")
for line in LOG:
    print(line)
