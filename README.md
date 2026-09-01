# DiffGuard

DiffGuard 是一款面向开发者的本地桌面工具，用于**审查 Git Diff** 与**监控 AI 编程助手的权限请求**，把"变更有多危险""这个授权要不要给"变成可量化的风险分数与明确提示。

- 技术栈：Python 3.13 + CustomTkinter + SQLModel + Windows UI Automation
- 平台：Windows 10 / 11（64 位）
- 许可证：仅供内部测试

---

## 功能一览

| 功能 | 说明 |
|---|---|
| AI 审查 Diff | 粘贴 git diff，调用大模型流式生成审查报告，指出硬编码密钥、配置泄漏等风险 |
| 本地风险评分 | 不联网也能算出 0-100 风险分（密钥/配置文件/删除占比/变更规模等启发式） |
| 剪贴板自动监听 | 复制 git diff 即自动载入；同步识别剪贴板中的权限请求文本 |
| 权限审批监控 | 通过 Windows UI Automation 扫描窗口，识别 AI 工具（如 OpenCode/Cursor/Cline）的授权请求并弹出置顶浮窗 |
| 风险仪表盘 | 载入 diff 后顶部显示总分、风险等级、文件数与主要风险点 |
| 自动放行 | 低风险权限请求（风险分低于阈值）可自动放行并记录，减少打扰 |
| 托盘通知 | 高风险权限请求（≥60 分）在系统托盘弹出气球提醒 |
| 历史记录 | 审查记录与权限审批记录分表持久化到 SQLite，支持搜索、风险过滤、回看与改决策 |
| 导出报告 | 一键将审查结果导出为 Markdown / HTML / 纯文本 |
| 快捷键 | Ctrl+V 载入 · Ctrl+Enter 审查 · Ctrl+S 保存 · Ctrl+E 导出 |
| 强调色 | 界面主色支持 蓝 / 绿 / 紫 / 橙 四套方案 |
| 前台模式 | 迷你悬浮窗，把当前 diff 的风险状态常驻显示在最前 |

## 快速上手

1. 双击 `DiffGuard.exe` 启动。
2. 首次使用点击 **设置**，填入 SiliconFlow API Key 并选择模型，保存。
3. 复制任意 git diff（`git diff` 输出）到剪贴板，程序自动载入（可用 Ctrl+V）；点击 **开始审查**（Ctrl+Enter）生成 AI 报告。
4. 若检测到权限请求，屏幕会弹出**权限审批浮窗**，选择"允许一次 / 总是允许 / 拒绝"。

## 使用说明

完整操作手册见 **使用说明书.md**（随便携版一同分发）。

## 目录结构（便携版）

```
DiffGuard/
├── DiffGuard.exe        程序入口
├── README.md            本文件
├── 使用说明书.md         详细操作手册
└── _internal/           Python 运行环境与依赖（请勿修改）
```

## 数据与配置存放位置

程序运行时数据保存在系统用户目录（非安装目录）：

- 配置：`%APPDATA%\DiffGuard\config.json`
- 数据库：`%LOCALAPPDATA%\DiffGuard\diffguard.db`
- 日志：`%LOCALAPPDATA%\DiffGuard\Logs\`

删除安装目录不影响已有数据；如需彻底清理，删除上述目录即可。

## 常见问题

**启动被 SmartScreen 拦截？**
安装包未签名，属于正常提示。点击"更多信息 → 仍要运行"即可。正式发布可进行代码签名。

**权限审批浮窗弹出后不自动消失？**
浮窗等待人工决策。点击任意决策按钮后自动关闭，并尝试在原工具窗口中回写对应操作（对原生 GUI 工具生效，对终端类 TUI 工具仅记录决策）。

**为什么偶尔会弹出风险提示但又消失了？**
剪贴板辅助通道只对**新复制**的权限文本触发；程序启动时的残留剪贴板内容仅作基线，不会误弹。另外，若开启了"低风险自动放行"，低于阈值（默认 20）的请求会被静默放行并直接写入历史，可到权限记录中查看。

**托盘没看到通知？**
高风险通知依赖 Windows 通知支持（需 `tray_notify` 开启，默认开）。若系统禁用了应用通知，气球不会显示，但不影响浮窗与历史记录。

## 构建

```powershell
# 打包便携版（onedir）
pip install pyinstaller
pyinstaller --noconfirm --onedir --windowed --name DiffGuard --icon app.ico --collect-all customtkinter --collect-submodules uiautomation main.py

# 生成安装包（需 Inno Setup 6+；默认单用户安装，免管理员权限）
ISCC.exe installer.iss
```

## 免责声明

本工具的风险评分与权限识别均为**本地启发式**，结果仅供人工决策参考，不构成安全结论。请结合自身判断处理高风险变更与授权请求。


## OpenCode 深度集成 (v0.2.0)

DiffGuard 提供与 AI 编程 Agent（OpenCode）的双向协作：

| 能力 | 说明 |
|---|---|
| MCP Server | 零依赖 MCP server（stdio），暴露 9 个工具：审查 diff/文件、查历史/权限/决策、提交决策请求、本地风险扫描 |
| 决策反馈闭环 | 用户在决策浮窗中的选择自动回写，Agent 可读取避免重复询问 |
| 决策请求通道 | Agent 通过 MCP/桥接文件显式提交决策，DiffGuard 弹浮窗（比剪贴板精确） |
| pre-commit 审查钩子 | 提交前自动风险扫描，高风险阻止提交 |
| CLI | python -m bridge.cli：review / scan / history / decisions / submit-decision / mcp 等 |

### 接入 OpenCode

在 opencode.json 的 mcp 段注册（源码运行）：

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

详细说明见随包 opencode/SKILL.md 与 opencode/plugin/README.md。

### 安装 git 审查钩子

```bash
python -m bridge.cli install-git-hook --dir <你的项目根目录>
```