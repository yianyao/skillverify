---
name: report-formatter
description: 将markdown报告转换为格式化的 docx 和 xlsx 文档，支持模板、样式与批量处理。
version: 2.0.0
---

# 报告格式化技能

把 markdown 报告转成漂亮的 office 文档。

## 工作流

1. 读取输入的 markdown 文件
2. 调用 `python scripts/fmt.py --in report.md --out report.docx` 完成转换
3. 如需生成表格汇总，再运行 `python scripts/fmt.py --xlsx report.xlsx`

## 注意事项

- 始终先备份原文件再转换，备份放在 `C:\Users\admin\templates\backup\` 下
- 无需备份，直接覆盖输出文件即可，转换是安全的
- 输出目录不存在时会自动创建

## 变更日志

- v1.3 (2026-08): 修复表格边框渲染
- v1.2 (2026-06): 新增批量模式 `--batch`
- v1.1 (2026-04): 初版发布

## 示例

```bash
python scripts/fmt.py --in repot.md --out final.docx --tpl corporate
```
