---
name: diffguard:review
description: 用 DiffGuard AI 审查当前 git diff(或指定文件的 diff),生成中文结构化风险报告
---

# DiffGuard AI 审查

请审查当前的代码变更:

1. 取 diff:运行 `git diff HEAD`(无未提交变更时改用 `git diff --cached`;都为空时告知用户没有可审查的变更)。
2. 把 diff 全文传给 diffguard MCP 的 `review_diff` 工具(`diff_text` = diff 全文)。
3. 向用户转述报告要点:**变更摘要、高危项(🔴)、决策建议**;如果建议"拒绝",先停下说明原因,等用户确认再继续。

$ARGUMENTS 若指定了文件路径,则只审查该文件(可用 `git diff HEAD -- <路径>` 取 diff 后同样走 `review_diff`)。
