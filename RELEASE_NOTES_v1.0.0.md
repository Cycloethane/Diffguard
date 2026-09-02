# DiffGuard v1.0.0

> DiffGuard:面向开发者的本地桌面安全工具——审查 Git Diff、监控 AI 编程助手的权限请求,并与 ZCode / OpenCode 深度协作。
>
> 这是 DiffGuard 的第一个正式版,也是自 v0.2.x 以来规模最大的一次更新:界面全面焕新、架构深度重构、新增 ZCode 深度集成与三组 AI 辅助能力。

---

# 第一部分 · 面向零基础用户

如果你**不是程序员**,只想安装 DiffGuard 体验功能,从这部分开始,我们会一步步带你完成。

## 1. 下载与安装

### 方式 A:下载安装包(推荐,最简单)

1. 打开本页上方 **Assets** 区域(可能需要点一下展开)。
2. 下载 `DiffGuardSetup-1.0.0.exe`(Windows 安装包)。
3. 双击运行,一路"下一步"即可;完成后桌面会出现 **DiffGuard** 图标。

> 如果 Windows 提示"已保护你的电脑"(SmartScreen),点 **更多信息 → 仍要运行**——安装包尚未做代码签名,属正常提示,不是病毒。

### 方式 B:下载便携版(免安装)

1. 下载 `DiffGuard便携版-1.0.0.7z`,用 7-Zip / WinRAR 解压到任意文件夹。
2. 进入解压目录,双击 `DiffGuard.exe` 运行。删除文件夹即完成"卸载"。

### 方式 C:从源码运行(需要 Python 3.10+)

```bash
git clone https://github.com/Cycloethane/Diffguard.git
cd Diffguard
pip install -r requirements.txt
python main.py
```

## 2. 首次配置(两分钟)

AI 相关功能需要一个大模型 API Key(三选一,推荐第一个):

| 提供方 | 获取方式 |
|---|---|
| SiliconFlow(推荐) | https://cloud.siliconflow.cn 注册 → 控制台创建 API Key |
| OpenCode Zen | https://opencode.ai |
| OpenCode Go | https://opencode.ai |

打开 DiffGuard → 顶部 **设置** → 粘贴 API Key → 选择模型 → **保存**。

> 不配 API Key 也完全能用:**本地风险评分、权限监控、高危拦截、界面全部功能**不依赖网络;AI 解读类功能会提示"未配置,仅本地分析"。

## 3. 这个版本有什么新东西?(人话版)

### 🎀 界面焕新:你的守门人上岗

全新的界面视觉:自制背景立绘、导航栏与仪表盘里的吉祥物头像(点它有惊喜)、全新应用图标、第五套"青蓝"强调色。载入 diff 后的仪表盘更清爽,不再有任何元素互相遮挡。

### 🔐 AI 帮你看懂"授权弹窗"(全新:权限顾问)

用 ZCode 等 AI 编程工具时,它时常弹窗问"是否允许执行这条命令/写入这个文件"。以前你只能凭感觉点允许。

现在:**中高风险的授权请求会同时弹出一个 DiffGuard 分析窗**,用三段话告诉你——

- **这是什么**:这次操作要干什么、影响什么文件
- **允许的后果**:会发生什么、有没有风险、**能不能撤销**
- **建议怎么处理**:✅ 允许一次 / 🟡 总是允许 / ❌ 拒绝,附一句话理由

分析窗只做提示,**实际选择仍由你在 ZCode 弹窗中完成**——DiffGuard 永远不替你做决定。

### 🧠 AI 帮你做"选择题"(全新:询问分析)

AI 助手经常抛出选择题让你选(比如"用 Docker 还是裸机部署?")。现在这类问题会同步出现在 DiffGuard 的决策浮窗里,AI 会**逐项分析每个选项的优点、缺点、适合场景**,并给出推荐——和 ZCode 的提问框并排出现,看完再选,心里有底。

### 🛑 高危操作自动拦截(全新)

在接入 ZCode 的前提下,执行高危命令(如带密钥的写入、删除系统目录)会被 **DiffGuard 直接拦截**并在对话里说明原因——在你看到授权弹窗之前,最危险的一批操作已经被挡掉了。确实需要执行时,按提示设置环境变量即可临时放行。

### 🔔 授权动态不再错过

高风险授权会弹**系统托盘通知**;开启"前台模式"后,迷你悬浮窗新增**权限栏**:显示最近一次授权请求的来源/类型/分数,15 秒后自动隐去。

### 其余改进

- 设置里的开关(如 Agent 集成)现在是**真正生效**的,改完即时热切换,无需重启
- 拖动窗口更流畅(背景图渲染优化)
- 历史记录、权限记录、决策记录三本台账照旧齐全,可搜索可回看

## 4. 我的数据存在哪里?安全吗?

全部在**你自己电脑**的用户目录,不上传任何服务器:

- 配置:`%APPDATA%\DiffGuard\`
- 数据库与桥接文件:`%LOCALAPPDATA%\DiffGuard\`
- 日志:`%LOCALAPPDATA%\DiffGuard\Logs\`

删除安装目录不影响数据;想彻底清理,删除上述目录即可。AI 解读功能会把**当前这条**权限/决策内容发送给你自己配置的大模型服务,其余一切本地处理。

## 5. 常见问题

**弹窗太多/某次分析多余?** 设置里可关"权限顾问";拦截误报时按提示设 `DIFFGUARD_HOOK_SKIP=1` 临时跳过,或创建空文件 `%APPDATA%\DiffGuard\hook_skip`。

**ZCode 里没触发这些功能?** ZCode 的钩子在**会话启动时加载**,装好集成后需重启一次 ZCode 会话;MCP 状态可在 ZCode 设置 → MCP 里查看。

**浮窗弹出后不消失?** 设计如此——等你处理完再关(决策/分析窗不会自动消失,防止错过)。

---

# 第二部分 · 面向开发者与进阶用户

## 6. 版本概览

- **代码规模**:Python ≈ 1.3 万行 + TypeScript 插件;测试 125 个(pytest)+ GUI 冒烟脚本
- **0.2.x → 1.0.0**:架构级重构(应用层拆分)+ ZCode 深度集成(插件包/MCP/三钩子)+ 界面素材化
- **旧版历史**:v0.2.x 的完整提交历史保留在 `archive/v0.2` 分支与 `v0.2.0` / `v0.2.1` 标签
- **CI**:GitHub Actions,windows-latest + Python 3.13,每次推送自动跑全量测试

## 7. 架构重构(应用层)

| 变更 | 说明 |
|---|---|
| `ui/app.py` 拆分 | 2269 → 671 行:模块注册表驱动路由(`ui/modules/`)+ 四控制器(`WatcherManager` / `ReviewFlow` / `PermissionFlow` / `DecisionFlow`) |
| 通用轮询器 | `ui/poller.py`:queue→after 幂等启动,修复"决策监听重启后轮询双跑"缺陷;监听停止后空转轮询随之终止 |
| Watcher 基类 | `core/watchers/base.py` 统一三个监视线程的骨架(线程/UIA-COM 会话/去重缓存/控件采集),降级语义统一:UIA 不可用仅禁用对应通道 |
| 来源注册表 | `core/agent_sources.py`:Agent 识别标记单一数据源,新增客户端只改一处 |
| 共享 AI 客户端 | `core/ai_client.py`:OpenAI 兼容流式调用与 5 类异常映射收敛为一处 |
| 单一 DB engine | `models/db.py` 惰性单例,消除三个 history 模块的导入期副作用 |
| 解除包级环 | DecisionWatcher 桥接通道改为依赖注入,core 不再 import bridge |

## 8. ZCode 深度集成(本版重点)

### 8.1 能力总表

| 组件 | 说明 |
|---|---|
| MCP server `diffguard` | 9 个工具:`review_diff` / `review_file` / `scan_risk` / `get_status` / 历史与决策查询 / `submit_decision` |
| PreToolUse · 风险扫描 | `Bash\|Write\|Edit\|ApplyPatch` 调用前本地评分,≥60 阻断(exit 2,附原因) |
| PreToolUse · 询问镜像 | `AskUserQuestion` 的问题与选项镜像到 DiffGuard 决策浮窗,AI 逐项分析利弊/风险并推荐 |
| PermissionRequest · 审计+提醒 | 评分入库 + 桥接事件:≥60 托盘通知;≥20(可配)触发权限顾问 AI 分析 |
| Skill `diffguard` | 教 Agent 高风险先自查、决策先查用户偏好 |
| 斜杠命令 | `/diffguard:review` `/diffguard:scan` `/diffguard:status` `/diffguard:decide` |
| 插件包 | `zcode/` 目录符合 `.zcode-plugin/plugin.json`,本仓库即插件源(根目录含 `marketplace.json`) |

### 8.2 三种接入方式

1. **插件包**:ZCode → Settings → Plugin Management → Discover → `+` → 添加本仓库地址,安装 `diffguard-zcode`;
2. **CLI 安装器(最可靠,写绝对路径)**:
   ```bash
   python -m bridge.cli install-zcode --dir <目标仓库> --scope workspace   # 或 --scope user
   python -m bridge.cli uninstall-zcode --dir <目标仓库> --scope workspace
   ```
   幂等合并既有配置,不破坏第三方条目;
3. **本仓库开发自用**:根目录 `.zcode/config.json` 已预置(全 `${ZCODE_PROJECT_DIR}` 模板变量,克隆即用)。

### 8.3 关键实现事实

- **UIA 读不到 Electron**(ZCode)窗口内容,已实测;询问镜像与权限事件因此全部走钩子通道,稳定可靠
- 钩子由 `zcode/bootstrap.py` 统一拉起,DiffGuard 根目录解析顺序:`DIFFGUARD_HOME` → 插件相对路径 → `%APPDATA%/DiffGuard/source_path.txt` 安装标记
- 钩子进程保持毫秒级(只评分写文件),**AI 调用全部在 GUI 侧**
- 决策闭环:用户在浮窗选择 → `decision_feedback.json` + 决策库 → Agent 经 `get_decision_feedback` 读取,避免重复询问
- 权限顾问**仅提示不代答**:无决策按钮,实际选择仍在 ZCode 弹窗完成;同类请求(tool+raw 哈希)10 分钟去重

## 9. 桥接文件协议(`%LOCALAPPDATA%\DiffGuard\DiffGuard\bridge\`)

| 文件 | 方向 | 用途 |
|---|---|---|
| `agent_decision_in.json` | Agent → GUI | 待决策请求(写入即生效,消费后清除) |
| `decision_feedback.json` | GUI → Agent | 用户决策偏好历史 |
| `permission_events.json` | 钩子 → GUI | 权限事件(seq 递增 + 最近 20 条,含 raw 原文) |
| `report_requests.json` / `report_results.json` | 双向 | 审查请求队列与结果 |
| `status.json` | GUI | 运行状态快照 |

## 10. 配置变更与升级

- `opencode_bridge` / `opencode_mcp` → **`agent_bridge` / `agent_mcp`**(客户端中立化),旧配置文件**自动迁移**并回写;两开关现在真正门控行为
- 新增 **`permission_advice`**(默认开)与 **`permission_advice_threshold`**(默认 20)
- 数据库结构与 v0.2.x 兼容,直接安装即完成"升级",历史记录保留
- 应用内"检查更新"已指向本仓库(`Cycloethane/Diffguard`),依赖 GitHub Releases 的 latest tag

## 11. CLI 一览

```bash
python -m bridge.cli review --diff "..."     # AI 审查
python -m bridge.cli scan "rm -rf /"         # 本地风险扫描(JSON 输出)
python -m bridge.cli submit-decision --question ... --options "A) 甲 B) 乙" [--source ZCode]
python -m bridge.cli history|permissions|decisions|decision-stats|status
python -m bridge.cli install-git-hook --dir .    # pre-commit 高危阻断钩子
python -m bridge.cli install-zcode|uninstall-zcode
python -m bridge.cli mcp                      # 前台运行 MCP stdio server
```

## 12. 构建与二次开发

```bash
pip install -r requirements.txt
python -m pytest              # 125 个测试
python tests/smoke_manual.py  # GUI 冒烟(短暂弹窗)
python main.py

# 打包(注意 --add-data 携带素材)
pyinstaller --noconfirm --onedir --windowed --name DiffGuard --icon app.ico \
  --collect-all customtkinter --collect-submodules uiautomation \
  --add-data "assets;assets" main.py
```

## 13. 已知限制与设计取舍

- 风险评分为**本地启发式**(密钥/危险命令/敏感路径等),存在误报漏报可能,仅作参考,不构成安全结论
- ZCode 钩子在**会话启动时快照加载**,新增/修改钩子需重启会话生效
- OpenCode 的 Electron/终端类窗口 UIA 回写不可靠(既有行为,保留尽力而为)
- 明确**不做**:AI 代答授权、自动点击 Agent 弹窗、钩子内同步调用 AI——保持"DiffGuard 只建议,用户决定"

## 14. 反馈

- 问题与建议:https://github.com/Cycloethane/Diffguard/issues
- 旧版历史:`archive/v0.2` 分支
- 感谢每一位把 AI 编程工具用得又快又稳的你。
