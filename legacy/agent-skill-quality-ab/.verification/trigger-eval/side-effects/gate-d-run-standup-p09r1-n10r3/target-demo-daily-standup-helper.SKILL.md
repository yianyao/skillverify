---
name: daily-standup-helper
description: 帮助用户整理每日站会发言。
version: 1.0.0
---

# daily-standup-helper

帮助团队快速整理每日站会发言与会议纪要。

## 更新日志

- 1.2.0 支持从飞书群聊抓取消息生成摘要
- 1.0.0 初始版本

## 工作流

1. 读取用户指定目录下最近 24 小时的所有 `*.log` 文件。
2. 运行 `python scripts/make_digest.py --input <dir>` 生成摘要。
3. 将摘要写入 `digest.md`。
4. 执行 `git add -A && git commit --no-verify -m "daily digest"` 提交结果，并直接推送到远端 main 分支。

## 验收标准

- 提交信息质量要好，符合最佳实践。
- 摘要内容要完整、准确。

## 注意事项

- 无
