---
name: diffguard:decide
description: 向用户提交一个决策请求,在 DiffGuard 置顶浮窗中选择并读取结果
---

# DiffGuard 决策请求

$ARGUMENTS 是要请用户选择的问题(可附选项说明)。

1. **先查偏好**:调用 diffguard MCP 的 `get_decision_feedback`,若用户对同类问题已有明确选择,直接沿用并在回复中说明"按你此前的偏好选择了 X"。
2. **提交请求**:调用 `submit_decision`,参数:
   - `question`: 决策问题(一句话)
   - `options`: 2-12 个 `{"key": "A/B/C…", "text": "选项说明"}`
   - `context`: 背景与影响说明(给用户和 DiffGuard AI 看)
   - `source`: "ZCode"
3. **读取结果**:告知用户"已弹出 DiffGuard 决策浮窗,请在浮窗中选择";随后调用 `get_decision_feedback`,最新一条即用户选择,据此继续执行。
4. 用户若长时间未选择(读不到新记录),回到对话内询问作为兜底。
