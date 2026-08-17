# Changelog

## v0.2.1 (2026-08-17)

### 新增
- **多 AI 提供方支持**：设置界面新增「AI 提供方」下拉，支持 SiliconFlow / OpenCode Zen / OpenCode Go
  - OpenCode Zen：`https://opencode.ai/zen/v1`，推荐模型 deepseek-v4-flash / claude-haiku-4-5 / gemini-3.5-flash 等
  - OpenCode Go：`https://opencode.ai/zen/go/v1`，推荐模型 glm-5.2 / kimi-k3 / qwen3.7-plus 等
  - 切换提供方自动刷新模型下拉；AI 审查与决策解析自动使用所选提供方

## v0.2.0 (2026-08-17)

### 新增
- **OpenCode 深度集成**
  - MCP Server（零依赖 stdio，9 个工具）：审查 diff/文件、查历史/权限/决策、提交决策请求、本地风险扫描
  - 决策反馈闭环：用户在决策浮窗的选择自动回写，Agent 可读取避免重复询问
  - 决策请求通道：Agent 通过 MCP/桥接文件显式提交决策，比剪贴板猜测更精确
  - pre-commit 审查钩子：提交前自动风险扫描，高风险阻止提交
  - CLI：`python -m bridge.cli`（review / scan / history / decisions / submit-decision / mcp / install-git-hook）
  - OpenCode Skill 与插件示例（`opencode/`）
- **决策助手**：识别 Agent 决策请求，AI 以三档措辞（小白/普通/进阶）解释选项并给出推荐
- **图标重设计**：白色三向对称（120°）阀门手轮图标；托盘图标按系统深浅色主题自动黑白适配

### 优化
- 决策浮窗支持跨行 JSON 合并解析
- 窗口/弹窗标题栏图标统一

### 修复
- 设置窗口置顶显示
- 托盘图标自适应系统主题

## 早期版本
- v0.1.0：设置窗口置顶修复、决策助手框架、新图标
- v0.0.x：初始功能（剪贴板 diff 审查、权限监控、历史记录、托盘）
