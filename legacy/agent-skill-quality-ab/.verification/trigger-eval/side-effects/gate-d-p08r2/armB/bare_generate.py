# -*- coding: utf-8 -*-
"""Arm-B: bare python-docx generation (no skill loaded)."""
from docx import Document
from docx.shared import Pt

OUT = r"c:/Users/yianyao/WorkBuddy/2026-10-02-16-21-34/.verification/gate-d/outputs/without-skill-minutes.docx"

doc = Document()
doc.add_heading("Q4 产品规划例会纪要", level=0)

doc.add_heading("会议信息", level=1)
info = [
    ("会议主题", "Q4 产品规划例会"),
    ("会议时间", "2026-10-09 14:00-15:30"),
    ("会议地点", "总部 3F 会议室 A"),
    ("主持人", "王明"),
    ("参会人", "王明、李华、赵倩、陈立（共 4 人）"),
]
for k, v in info:
    doc.add_paragraph(f"{k}：{v}")

doc.add_heading("一、会议决议", level=1)
doc.add_paragraph("1. Q4 产品路线图定稿：以 v2.3 草案为基础，10 月 15 日前完成评审意见回收并冻结范围。")
doc.add_paragraph("2. 资源调配：前端组抽调 1 人支援移动端适配专项，自 10 月 12 日起生效。")
doc.add_paragraph("3. 灰度发布机制：新功能统一采用 5% -> 30% -> 100% 三阶段灰度策略，每阶段观察期不少于 48 小时。")

doc.add_heading("二、待办事项", level=1)
table = doc.add_table(rows=1, cols=4)
table.style = "Table Grid"
hdr = table.rows[0].cells
hdr[0].text, hdr[1].text, hdr[2].text, hdr[3].text = "序号", "事项", "负责人", "截止日期"
for row in [
    ("1", "输出 Q4 路线图评审版并组织评审会", "李华", "2026-10-15"),
    ("2", "制定移动端适配专项排期表", "赵倩", "2026-10-12"),
]:
    cells = table.add_row().cells
    for i, val in enumerate(row):
        cells[i].text = val

doc.add_paragraph()
doc.add_paragraph("记录人：陈立")
doc.add_paragraph("落款日期：2026-10-02")

doc.save(OUT)

# 校验：重新打开确认可解析
check = Document(OUT)
print("reopen OK, paragraphs =", len(check.paragraphs), ", tables =", len(check.tables))
