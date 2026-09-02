# DiffGuard

DiffGuard 是一款面向开发者的**开源**本地桌面工具,用于**审查 Git Diff** 与**监控 AI 编程助手的权限请求**,把"变更有多危险""这个授权要不要给"变成可量化的风险分数与明确提示;并可与 AI 编程 Agent(ZCode / OpenCode 等)双向协作,形成"高风险先自查、决策先查偏好"的闭环。

- 技术栈:Python 3.13 + CustomTkinter + SQLModel + Windows UI Automation
- 平台:Windows 10 / 11(64 位)
- 许可证:MIT(见 LICENSE)

---

## 功能一览

| 功能 | 说明 |
|---|---|
| AI 审查 Diff | 粘贴 git diff,调用大模型流式生成审查报告,指出硬编码密钥、配置泄漏等风险 |
| 本地风险评分 | 不联网也能算出 0-100 风险分(密钥/配置文件/删除占比/变更规模等启发式) |
| 剪贴板自动监听 | 复制 git diff 即自动载入;同步识别剪贴板中的权限请求文本 |
| 权限审批监控 | 通过 Windows UI Automation 扫描窗口,识别 AI 工具(OpenCode/ZCode/Cursor/Cline)的授权请求并弹出置顶浮窗 |
| 风险仪表盘 | 载入 diff 后顶部显示总分、风险等级、文件数与主要风险点 |
| 自动放行 | 低风险权限请求(风险分低于阈值)可自动放行并记录,减少打扰 |
| 托盘通知 | 高风险权限请求(≥60 分)在系统托盘弹出气球提醒 |
| 历史记录 | 审查记录与权限审批记录分表持久化到 SQLite,支持搜索、风险过滤、回看与改决策 |
| 导出报告 | 一键将审查结果导出为 Markdown / HTML / 纯文本 |
| 快捷键 | Ctrl+V 载入 · Ctrl+Enter 审查 · Ctrl+S 保存 · Ctrl+E 导出 |
| 强调色 | 界面主色支持 墨蓝 / 雾蓝 / 青蓝 / 蓝紫 / 暖粉 五套方案(取自吉祥物色板) |
| 前台模式 | 迷你悬浮窗,把当前 diff 的风险状态常驻显示在最前 |

## 快速上手

1. 安装依赖并启动:`pip install -r requirements.txt && python main.py`(或使用打包版 `DiffGuard.exe`)。
2. 首次使用点击 **设置**,填入 API Key 并选择模型,保存。
3. 复制任意 git diff 到剪贴板,程序自动载入;点击 **开始审查**(Ctrl+Enter)生成 AI 报告。
4. 检测到权限请求时,屏幕会弹出**权限审批浮窗**,选择"允许一次 / 总是允许 / 拒绝"。

完整操作手册见 **使用说明书.md**。

## 架构

```
main.py            入口:DPI/日志/配置/首启向导
core/              纯逻辑层(无 UI 依赖)
  ├ diff_parser / risk_score        diff 解析 + 本地风险评分
  ├ permission_parser/_risk/_watcher 权限识别/评分/UIA 监听
  ├ decision_parser/_watcher/_explainer 决策识别/监听/AI 解析
  ├ clipboard_watcher               剪贴板监听
  ├ watchers/base.py                监视线程公共骨架(线程/UIA会话/去重)
  ├ agent_sources.py                Agent 来源注册表(单点新增客户端)
  └ ai_client.py                    共享 OpenAI 兼容流式客户端
models/            数据层:pydantic-settings 配置 + SQLModel 三张历史表
                   (models/db.py 单一惰性 engine)
ui/                界面层
  ├ app.py                         主窗口薄壳(组装/托盘/前台窗/设置)
  ├ controllers/                   WatcherManager / Review / Permission / Decision 四控制器
  ├ modules/                       导航模块注册表(审查/历史/权限/决策/设置)
  ├ poller.py                      通用 queue→after 轮询器(幂等)
  ├ dialogs.py / widgets.py        弹窗与公共控件
  └ ...                            浮窗/仪表/主题/动画等组件
bridge/            对外集成层:零依赖 MCP server、CLI、文件桥接、hooks 执行器
zcode/             ZCode 插件包(MCP + Skill + 命令 + Hooks)
opencode/          OpenCode 兼容集成(SKILL + TS 插件示例)
tests/             pytest 测试(纯逻辑层全覆盖)+ GUI 冒烟脚本
```

数据与配置存放位置(删除安装目录不影响数据):

- 配置:`%APPDATA%\DiffGuard\config.json`
- 数据库:`%LOCALAPPDATA%\DiffGuard\diffguard.db`
- 日志:`%LOCALAPPDATA%\DiffGuard\Logs\`

---

## Agent 集成

DiffGuard 与 AI 编程 Agent 双向协作:

| 能力 | 说明 |
|---|---|
| MCP Server | 零依赖 MCP server(stdio),暴露 9 个工具:审查 diff/文件、查历史/权限/决策、提交决策请求、本地风险扫描 |
| 决策反馈闭环 | 用户在决策浮窗中的选择自动回写,Agent 可读取避免重复询问 |
| 决策请求通道 | Agent 通过 MCP/桥接文件显式提交决策,DiffGuard 弹浮窗(比剪贴板精确) |
| pre-commit 审查钩子 | 提交前自动风险扫描,高风险阻止提交 |
| CLI | `python -m bridge.cli`:review / scan / history / decisions / submit-decision / install-* 等 |

### 接入 ZCode(推荐,三种方式任选)

**方式一:插件包(本仓库即插件源)**

zcode/ 目录是合规的 ZCode 插件(`.zcode-plugin/plugin.json`):

- 本地安装:ZCode → Settings → Plugin Management → Discover → `+` → 添加本仓库根目录(含 `marketplace.json`),安装 `diffguard-zcode`;
- 推送 GitHub 后,把仓库地址作为 marketplace 添加即可随仓库更新。

插件提供:diffguard MCP server(9 工具)、`/diffguard:review|scan|status|decide` 斜杠命令、DiffGuard Skill、**PreToolUse 风险扫描钩子(高危 Bash/Write/Edit 阻断)**、**AskUserQuestion 询问镜像钩子(AI 逐项分析选项利弊/风险并推荐,与 ZCode 询问框并行)**、**PermissionRequest 权限钩子(评分审计 + 高风险托盘提醒 + 前台小窗权限栏)**、**权限顾问(中高风险授权请求弹 AI 分析:是什么/允许的后果/建议,仅提示不代答)**。

**方式二:CLI 安装器(写入配置,最可靠)**

```bash
# 当前仓库生效(.zcode/config.json + skills + commands)
python -m bridge.cli install-zcode --dir <你的仓库> --scope workspace
# 或全局生效(~/.zcode/)
python -m bridge.cli install-zcode --scope user
# 卸载
python -m bridge.cli uninstall-zcode --dir <你的仓库> --scope workspace
```

**方式三:本仓库开发自用**

仓库根已预置 `.zcode/config.json`(全模板变量,无机器特定路径),克隆即用。

插件/钩子的路径解析、逃生通道(`DIFFGUARD_HOOK_SKIP=1` 或 `%APPDATA%\DiffGuard\hook_skip` 标记文件)详见 [zcode/README.md](zcode/README.md)。

### 接入 OpenCode(兼容保留)

在 opencode.json 的 mcp 段注册(源码运行,cwd 换成你的 DiffGuard 路径):

```jsonc
{
  "mcp": {
    "diffguard": {
      "type": "stdio",
      "command": ["python", "-m", "bridge.mcp_server"],
      "cwd": "<DiffGuard 仓库路径>"
    }
  }
}
```

详细说明见 [opencode/SKILL.md](opencode/SKILL.md) 与 [opencode/plugin/README.md](opencode/plugin/README.md)(TS 插件支持 `DIFFGUARD_HOME` 环境变量定位源码)。

### 安装 git 审查钩子

```bash
python -m bridge.cli install-git-hook --dir <你的项目根目录>
```

---

## 开发

```bash
pip install -r requirements.txt
python -m pytest              # 114 个测试(纯逻辑层 + 集成层)
python tests/smoke_manual.py  # GUI 冒烟(短暂弹窗)
python main.py                # 启动应用
```

构建便携版:

```powershell
pip install pyinstaller
pyinstaller --noconfirm --onedir --windowed --name DiffGuard --icon app.ico --collect-all customtkinter --collect-submodules uiautomation --add-data "assets;assets" main.py
```

界面素材(背景立绘 / 吉祥物 / 图标)集中在 `assets/`,构建时以 `--add-data "assets;assets"` 一并打包。

## 免责声明

本工具的风险评分与权限识别均为**本地启发式**,结果仅供人工决策参考,不构成安全结论。请结合自身判断处理高风险变更与授权请求。
