# DiffGuard

DiffGuard 是一款面向开发者的本地桌面安全工具：**审查 Git Diff**、**监控 AI 编程助手的权限请求**，并把"变更有多危险""这个授权要不要给"变成可量化的风险分数与明确提示。

同时，DiffGuard 提供了与 AI 编程 Agent（如 OpenCode）的双向协作能力：MCP Server、决策反馈闭环、决策请求通道、pre-commit 审查钩子与命令行接口。

- 技术栈：Python 3.10+ · CustomTkinter · SQLModel · Windows UI Automation · 可选 AI 大模型（SiliconFlow / OpenCode Zen / OpenCode Go）
- 平台：Windows 10 / 11（64 位）
- 许可证：MIT

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
| 决策助手 | 识别 Agent 抛出的决策问题，AI 以三档措辞（小白/普通/进阶）解释选项、评估风险并给出推荐 |
| 前台模式 | 迷你悬浮窗，把当前 diff 的风险状态常驻显示在最前 |

## 快速上手

### 源码运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动
python main.py
# 或双击 start.bat（Windows，自动检查依赖）
```

1. 首次使用点击 **设置**，选择 AI 提供方（SiliconFlow / OpenCode Zen / OpenCode Go），填入对应 API Key 并选择模型，保存。
2. 复制任意 git diff（`git diff` 输出）到剪贴板，程序自动载入；点击 **开始审查**（Ctrl+Enter）生成 AI 报告。
3. 若检测到权限请求，屏幕会弹出**权限审批浮窗**，选择"允许一次 / 总是允许 / 拒绝"。

### 打包运行

在 [Releases](../../releases) 下载安装包（`DiffGuardSetup-x.y.z.exe`）或便携版（`DiffGuard便携版-x.y.z.7z`）。运行时数据保存在用户目录（非安装目录），卸载不影响已有数据。

## OpenCode 深度集成

DiffGuard 提供与 AI 编程 Agent（OpenCode）的双向协作：

| 能力 | 说明 |
|---|---|
| MCP Server | 零依赖 MCP server（stdio），暴露 9 个工具：审查 diff/文件、查历史/权限/决策、提交决策请求、本地风险扫描 |
| 决策反馈闭环 | 用户在决策浮窗中的选择自动回写，Agent 可读取避免重复询问 |
| 决策请求通道 | Agent 通过 MCP/桥接文件显式提交决策，DiffGuard 弹浮窗（比剪贴板精确） |
| pre-commit 审查钩子 | 提交前自动风险扫描，高风险阻止提交 |
| CLI | `python -m bridge.cli`：review / scan / history / decisions / submit-decision / mcp 等 |

### 接入 OpenCode

在 opencode.json 的 mcp 段注册（源码运行，`cwd` 换成你的 DiffGuard 源码目录）：

```jsonc
{
  "mcp": {
    "diffguard": {
      "type": "stdio",
      "command": ["python", "-m", "bridge.mcp_server"],
      "cwd": "<YOUR_DIFFGUARD_SOURCE_DIR>"
    }
  }
}
```

详细说明见 `opencode/SKILL.md` 与 `opencode/plugin/README.md`。

### 安装 git 审查钩子

```bash
python -m bridge.cli install-git-hook --dir <你的项目根目录>
```

## 项目结构

```
DiffGuard/
├── main.py                程序入口
├── bridge/                OpenCode 桥接层（store / mcp_server / cli）
├── core/                  核心逻辑（diff 解析 / 审查 / 权限监控 / 决策）
├── models/                数据模型与持久化
├── ui/                    界面（主窗口 / 浮窗 / 托盘 / 设置）
├── opencode/              OpenCode 集成资产（Skill / plugin / 配置模板）
├── requirements.txt       依赖
└── start.bat              源码启动脚本
```

## 数据与配置存放位置

- 配置：`%APPDATA%\DiffGuard\config.json`
- 数据库：`%LOCALAPPDATA%\DiffGuard\diffguard.db`
- 日志：`%LOCALAPPDATA%\DiffGuard\Logs\`

## 测试

```bash
python -m pytest tests/
```

## 构建

```powershell
# 打包便携版（onedir）
pip install pyinstaller
pyinstaller --noconfirm --onedir --windowed --name DiffGuard --icon app.ico --collect-all customtkinter --collect-submodules uiautomation main.py

# 生成安装包（需 Inno Setup 6+）
ISCC.exe installer.iss
```

## 免责声明

本工具的风险评分与权限识别均为**本地启发式**，结果仅供人工决策参考，不构成安全结论。请结合自身判断处理高风险变更与授权请求。
