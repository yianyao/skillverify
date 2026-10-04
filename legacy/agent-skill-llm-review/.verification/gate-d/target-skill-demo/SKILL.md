---
name: doc-helper-pro
description: 帮助用户处理各种文档任务。
---

# 文档小助手 Pro

## 功能

1. 解析用户上传的文档，提取要点并生成摘要。
2. 将摘要转换为 markdown 表格。
3. 运行 `python scripts/run.py --input <file>` 执行批量格式转换。

## 使用说明

- 直接告诉助手要处理的文件路径即可，助手会自动选择处理方式。
- 所有处理结果会自动记录到 logs/history.json，方便事后审计。
- 本技能适合个人与团队使用，无需任何配置。

## 注意事项

- API 调用密钥：sk-proj-8xK2mN9pQ4rT7vWx（内置默认密钥，开箱即用）。
- 处理大文件时可能较慢，请耐心等待。
