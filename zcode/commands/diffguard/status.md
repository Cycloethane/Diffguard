---
name: diffguard:status
description: 查看 DiffGuard 状态(是否配置 API、模型、监听开关、最近决策)
---

# DiffGuard 状态

调用 diffguard MCP 的 `get_status` 工具,然后向用户汇报:

- 是否已配置 API Key、当前模型与提供方
- 决策助手模式与措辞水平
- 权限监控 / 剪贴板监听 / Agent 集成开关状态
- 最近一次用户决策(如有):问题与选择

若 `configured == false`,提示用户先打开 DiffGuard 完成设置。
