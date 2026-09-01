# DiffGuard 集成 Skill

这个 Skill 教你如何在对话中与 **DiffGuard**（本地安全审查 + 决策助手工具）协作。

## 快速开始

DiffGuard 是运行在你本机 Windows 上的桌面工具。它提供：

1. **AI 审查**：把一段 git diff 交给 AI 分析（密钥、权限、高风险变更）。
2. **权限监控**：监控系统权限调用，拦截高风险操作。
3. **决策助手**：当你（Agent）需要用户做选择时，可以请用户通过 DiffGuard 决策浮窗选择，并把用户偏好记录下来。

## 推荐接入方式：MCP

在 `opencode.json` 中注册（DiffGuard 源码运行）：

```jsonc
{
  "mcp": {
    "diffguard": {
      "type": "stdio",
      "command": ["python", "-m", "bridge.mcp_server"],
      "cwd": "D:/SP_DiffGuard"
    }
  }
}
```

> 打包版：使用 `DiffGuardMCP.bat` 或指定可执行文件路径。

## 无 MCP 时的文件级通信

DiffGuard 会把状态写到 `%APPDATA%/DiffGuard/bridge/`：

- `decision_feedback.json` — 用户决策偏好历史，**决策前先读它**。
- `status.json` — 当前状态快照。
- `report_results.json` — 最近的审查结果。
- `agent_decision_in.json` — 你（Agent）提交待决策请求的文件。

### 工作流建议

1. **需要用户做选择时**：先读 `decision_feedback.json` 看用户历史偏好，若已有明确偏好则直接沿用，不再重复询问；若没有，把决策请求写入 `agent_decision_in.json`（格式见下），DiffGuard 会弹出浮窗让用户选择。
2. **提交决策请求的 JSON 格式**：
   ```json
   {
     "timestamp": "2026-01-01T00:00:00",
     "source": "OpenCode",
     "question": "打包方式请选择：",
     "options": [
       {"key": "A", "text": "PyInstaller 单文件"},
       {"key": "B", "text": "PyInstaller 目录"},
       {"key": "C", "text": "Inno Setup 安装包"}
     ],
     "context": "用户需要一个可分发版本"
   }
   ```
3. **用户选择后**：读 `decision_feedback.json` 最新一条，就是用户的最终选择，据此继续执行。

## 关键原则

- **尊重用户历史偏好**：用户之前选过同类问题，不要重复询问，直接用 `get_decision_feedback` 的结果。
- **高风险操作前主动审查**：改动涉密钥、权限、删除文件、系统目录时，先用 `review_diff` 或 `scan_risk` 自查一遍再执行。
- **决策请求给足上下文**：`context` 字段写清楚背景，DiffGuard 的 AI 才能给出准确解释。
