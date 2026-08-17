# DiffGuard v0.2.0

DiffGuard：面向开发者的本地桌面安全工具，审查 Git Diff 并监控 AI 编程助手的权限请求，附带 OpenCode 深度集成。

## 亮点

- **AI 审查 Diff**：流式生成中文审查报告，识别硬编码密钥、配置泄漏等风险
- **权限审批监控**：UIA 扫描 AI 工具授权请求，置顶浮窗提示 + 本地 0-100 风险评分
- **决策助手**：识别 Agent 决策，三档措辞解释选项并推荐
- **OpenCode 集成**：MCP Server（9 工具）、决策反馈闭环、pre-commit 钩子、CLI
- **全新图标**：三向对称阀门手轮，托盘图标自动适配深浅色

## 下载

- `DiffGuardSetup-0.2.0.exe` — Windows 安装包
- `DiffGuard便携版-0.2.0.7z` — 便携版

## 快速开始

1. 运行安装包，首次启动点击**设置**填入 SiliconFlow API Key
2. 复制 git diff 到剪贴板自动载入，点**开始审查**生成报告
3. 安装 git 审查钩子：`python -m bridge.cli install-git-hook --dir <项目目录>`

## 系统要求

- Windows 10 / 11（64 位）
- 安装包 / 便携版：无需 Python
- 源码运行：Python 3.10+