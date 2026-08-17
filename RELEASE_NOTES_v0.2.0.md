# DiffGuard v0.2.0

> DiffGuard：面向开发者的本地桌面安全工具——审查 Git Diff、监控 AI 编程助手的权限请求，并深度集成 OpenCode。

---

# 第一部分 · 面向新手用户

如果你**不是程序员**，只是想安装 DiffGuard 并体验它的功能，请从这一部分开始。我们会一步步带你完成。

## 1. 下载与安装

### 方式 A：下载安装包（推荐，最简单）

1. 打开本页上方 **Assets** 区域（可能需要点一下展开）。
2. 下载 `DiffGuardSetup-0.2.0.exe`（Windows 安装包）。
3. 双击运行安装程序，一路点"下一步"即可。
4. 安装完成后，桌面或开始菜单会出现 **DiffGuard** 图标，双击启动。

> 如果 Windows 提示"已保护你的电脑"（SmartScreen），请点击 **更多信息 → 仍要运行**。这是因为安装包尚未签名，属正常提示，非病毒。

### 方式 B：下载便携版（免安装）

1. 下载 `DiffGuard便携版-0.2.0.7z`。
2. 用压缩软件（如 7-Zip / WinRAR）解压到任意文件夹（例如 `D:\DiffGuard`）。
3. 进入解压目录，双击 `DiffGuard.exe` 即可运行。

### 方式 C：从源码运行（需要 Python）

适合想自己改代码或对 Python 熟悉的朋友（见第二部分）。

## 2. 首次配置

DiffGuard 的部分高级功能（AI 审查、决策助手）需要一个 **SiliconFlow 平台的 API Key**：

1. 打开 https://cloud.siliconflow.cn ，注册并登录。
2. 在控制台创建 API Key（一个形如 `sk-xxxxxxxx` 的字符串）。
3. 打开 DiffGuard → 点击顶部的 **设置** 按钮。
4. 把 API Key 粘贴进"API Key (SiliconFlow)"输入框，选择一个模型（默认即可），点 **保存**。

> 即使不配置 API Key，DiffGuard 的**本地风险评分**、**权限监控**等功能依然可用。

## 3. 它有什么用？

### 🔍 审查代码变更（Diff 审查）

程序员改代码时会产生"变更记录"（git diff）。把这段内容复制到剪贴板，DiffGuard 会自动读取，并告诉你：

- 这次改动**改了什么文件、加了多少行、删了多少行**
- 有没有**硬编码的密码、密钥**等危险内容
- 整体**风险有多高**（0-100 分）

点击 **开始审查**，AI 会生成一份通俗的中文报告，说明改动的影响和需要注意的地方。

### 🛡️ 监控 AI 编程助手的授权请求

现在很多人用 AI 编程工具（OpenCode、Cursor、Cline 等）。这些工具有时会请求访问文件、执行命令。DiffGuard 会在后台监控这些请求：

- 发现高风险操作（如删除系统文件、执行危险命令）时，弹出**置顶浮窗**提醒你
- 给出 0-100 的风险分数，帮你决定"允许 / 拒绝"

### 🤔 决策助手

当 AI 编程助手向你抛出"选择题"（比如"打包方式选 A 还是 B？"）时，DiffGuard 会弹出窗口，用**大白话**解释每个选项是什么意思、有什么风险，并给出推荐答案。点一下你就能做出选择。

## 4. 常用小技巧

- 复制 git diff 后按 **Ctrl+V** 可手动载入
- 按 **Ctrl+Enter** 快速开始审查
- 任务栏托盘有 DiffGuard 图标，右键可以显示/隐藏主窗口
- 设置里可以切换**深色/浅色主题**和**强调色**（蓝/绿/紫/橙）

---

# 第二部分 · 面向开发者

## 1. 项目简介

DiffGuard 是一款运行在 Windows 10/11 上的本地桌面工具，把"变更有多危险""这个授权要不要给"变成可量化的风险分数与明确提示。它面向使用 AI 编程助手（OpenCode/Cursor/Cline 等）的开发者，提供 diff 审查、权限监控、决策辅助与 Agent 双向协作能力。

- **技术栈**：Python 3.10+ · CustomTkinter · SQLModel (SQLite) · Windows UI Automation · OpenAI SDK（SiliconFlow 兼容接口）
- **许可证**：MIT
- **平台**：Windows 10 / 11（64 位）

## 2. 架构与目录结构

```
DiffGuard/
├── main.py                程序入口（日志、配置、GUI、首启引导）
├── bridge/                OpenCode 桥接层
│   ├── store.py           文件级通信（决策反馈/审查请求/状态）
│   ├── mcp_server.py      零依赖 MCP server（JSON-RPC/stdio）
│   └── cli.py             命令行入口（argparse，零第三方依赖）
├── core/                  核心逻辑
│   ├── diff_parser.py     git diff 解析（unidiff + 容错回退）
│   ├── risk_score.py      本地启发式风险评分（0-100）
│   ├── permission_parser.py / permission_risk.py / permission_watcher.py
│   ├── decision_parser.py / decision_explainer.py / decision_watcher.py
│   ├── reviewer.py        AI 流式审查（OpenAI SDK）
│   └── clipboard_watcher.py
├── models/                数据模型与持久化（config / history / permission_history / decision_history）
├── ui/                    界面（主窗口 / 浮窗 / 托盘 / 设置 / overlay）
├── opencode/              OpenCode 集成资产（SKILL.md / plugin / 配置模板）
├── tests/                 pytest 单元测试（45 个，离线可跑）
└── requirements.txt / pytest.ini / CHANGELOG.md
```

## 3. 核心功能实现要点

### 风险评分（`core/risk_score.py`）
- 纯本地启发式：硬编码密钥、配置文件变更、文件删除、依赖变更、变更规模（对数递减）、删除占比
- `score_text()` 提供对任意文本的快速风险扫描（供 MCP `scan_risk` 与 git hook 复用）

### 权限监控（`core/permission_watcher.py`）
- UIA 扫描 Agent 窗口 + 剪贴板辅助双通道
- `permission_risk.py` 基于"动作 × 目标敏感度"评分，并修复了 `~/Windows` 误判系统目录的问题

### 决策助手（`core/decision_*`）
- 三通道感知：剪贴板、UIA 窗口扫描、OpenCode 桥接文件（`agent_decision_in.json`）
- 三档措辞（beginner/normal/advanced）系统提示词
- 结构化输出协议：`#QUESTION#` / `#OPTION# <json>` / `#RECOMMEND# <json>` / `#ERROR#`

## 4. OpenCode 集成

| 能力 | 说明 |
|---|---|
| MCP Server | 零依赖 stdio 实现（JSON-RPC），9 个工具：get_status / review_diff / review_file / get_recent_reviews / get_recent_permissions / get_decision_feedback / get_decision_stats / submit_decision / scan_risk |
| 决策反馈闭环 | 用户选择写入 SQLite + `decision_feedback.json`，Agent 读取避免重复询问 |
| 决策请求通道 | Agent 写 `agent_decision_in.json`，DiffGuard 弹浮窗（比剪贴板精确） |
| pre-commit 钩子 | `python -m bridge.cli install-git-hook --dir <repo>`，高风险阻止提交 |
| CLI | review / history / permissions / decisions / decision-stats / scan / submit-decision / status / mcp / install-git-hook |

**接入 OpenCode**（`opencode.json`）：

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

详细说明见 `opencode/SKILL.md` 与 `opencode/plugin/README.md`。插件源码为 TypeScript（`opencode/plugin/src/index.ts`），通过 `DIFFGUARD_HOME` 环境变量定位 DiffGuard 目录。

## 5. 开发环境搭建

```bash
# Python 3.10+
pip install -r requirements.txt
pip install pytest

# 运行测试（45 个用例，离线）
python -m pytest tests -q

# 启动应用
python main.py
```

## 6. 构建与打包

```powershell
# 便携版（onedir）
pip install pyinstaller
pyinstaller --noconfirm --onedir --windowed --name DiffGuard --icon app.ico --collect-all customtkinter --collect-submodules uiautomation main.py

# 安装包（需 Inno Setup 6+，参考 installer.iss）
ISCC.exe installer.iss
```

注意：`DiffGuard.spec` 中 `hiddenimports` 需包含 `bridge.store / bridge.mcp_server / bridge.cli / models.decision_history`，否则打包后 MCP/CLI 模块缺失。

## 7. 运行时数据位置

| 数据 | 路径 |
|---|---|
| 配置 | `%APPDATA%\DiffGuard\config.json` |
| 数据库（审查/权限/决策历史） | `%LOCALAPPDATA%\DiffGuard\diffguard.db` |
| 日志 | `%LOCALAPPDATA%\DiffGuard\Logs\` |
| 桥接文件 | `%APPDATA%\DiffGuard\bridge\` |

## 8. 设计决策与取舍

- **MCP 零依赖**：手写 JSON-RPC/stdio 而非引入 `mcp` SDK，降低打包体积与依赖冲突
- **文件级桥接**：不要求 OpenCode 安装额外插件，通过约定 JSON 文件交换状态，Skill 文档教会 Agent 读写
- **本地优先**：风险评分全本地可复现，AI 审查仅用于生成报告（Key 未配置时功能降级可用）
- **托盘自适应**：托盘图标按系统深浅色主题自动切换黑白版本

## 9. 版本历史

- **v0.2.0**：OpenCode 深度集成（MCP/决策反馈/CLI/git hook）、决策助手、图标重设计、托盘自适应
- **v0.1.0**：设置窗口置顶修复、决策助手框架、新图标
- **v0.0.x**：初始功能（剪贴板 diff 审查、权限监控、历史记录、托盘）

## 10. 免责声明

风险评分与权限识别均为**本地启发式**，结果仅供人工决策参考，不构成安全结论。请结合自身判断处理高风险变更与授权请求。