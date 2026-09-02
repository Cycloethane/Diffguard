---
name: diffguard
description: Use when reviewing git diffs before commit, scanning risky commands/paths before executing them, or when you need the user to make a choice via DiffGuard's floating decision window. Provides local risk scoring, AI diff review, permission audit history, and a decision feedback loop via the diffguard MCP tools.
---

# DiffGuard 集成 Skill

这个 Skill 教你如何与 **DiffGuard**(本地安全审查 + 决策助手工具)协作。

## 快速开始

DiffGuard 是运行在你本机 Windows 上的桌面工具,通过 `diffguard` MCP server 提供:

1. **AI 审查**:`review_diff` / `review_file` 把 git diff 交给 AI 分析(密钥、权限、高风险变更)。
2. **本地风险扫描**:`scan_risk` 不调 AI,秒级返回 0-100 风险分与命中项。
3. **权限审计**:`get_recent_permissions` 查询权限审批记录(含 ZCode 钩子自动入库的记录)。
4. **决策闭环**:`submit_decision` 让用户在 DiffGuard 浮窗中做选择,`get_decision_feedback` 读取历史偏好。

## 工作流建议

### 1. 高风险操作前主动自查

改动涉及密钥、权限、删除文件、系统目录时,执行前先用 `scan_risk` 自查:

- `level == "high"` → 停下来,向用户说明风险并确认
- 提交前用 `review_diff` 审查完整 diff(暂存区:`git diff --cached`)

注意:PreToolUse 钩子已自动对 Bash/Write/Edit 调用做本地扫描,高危命令会被直接阻断
(设置环境变量 `DIFFGUARD_HOOK_SKIP=1` 可临时跳过,但必须先向用户说明原因)。

### 2. 需要用户选择时:先查偏好,再提问

**决策前先读 `get_decision_feedback`**——用户此前对同类问题的选择就是偏好,
有明确偏好时直接沿用,不要重复询问。

没有历史偏好时,用 `submit_decision` 提交决策请求(比在对话里问更醒目,
用户会在置顶浮窗中选择):

```json
{
  "question": "打包方式请选择：",
  "options": [
    {"key": "A", "text": "PyInstaller 单文件"},
    {"key": "B", "text": "PyInstaller 目录"},
    {"key": "C", "text": "Inno Setup 安装包"}
  ],
  "context": "用户需要一个可分发版本",
  "source": "ZCode"
}
```

用户选择后,`get_decision_feedback` 的最新一条就是结果,据此继续执行。
`context` 写清楚背景,DiffGuard 的 AI 才能给出准确的选项解读。

### 3. 无 MCP 时的文件级通信

DiffGuard 把状态写在 `%APPDATA%/DiffGuard/bridge/`:

- `decision_feedback.json` — 用户决策偏好历史,**决策前先读它**
- `agent_decision_in.json` — 你提交待决策请求的文件(格式同上,写完即生效)
- `status.json` — 当前状态快照

## 关键原则

- **尊重用户历史偏好**:同类问题用户选过就直接沿用,避免重复打扰。
- **高风险先自查再执行**:密钥、删除、系统目录、`rm -rf`、`--force` 类操作。
- **决策请求给足上下文**:`context` 字段说明背景与影响。
