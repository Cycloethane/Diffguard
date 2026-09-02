# DiffGuard × ZCode 插件

把 DiffGuard 的安全审查能力接入 ZCode:AI 审查、本地风险扫描、权限审计、决策闭环。

## 提供什么

| 组件 | 说明 |
|---|---|
| MCP server(`diffguard`) | 9 个工具:`review_diff` / `scan_risk` / `submit_decision` / `get_decision_feedback` / 历史查询等 |
| PreToolUse 钩子 | Bash / Write / Edit / ApplyPatch 调用前做本地风险扫描,**高危(≥60 分)阻断** |
| AskUserQuestion 钩子 | Agent 原生询问自动镜像到 DiffGuard 决策浮窗:AI **逐项分析各选项的优点/缺点/风险并给出推荐**,与 ZCode 询问框并行展示;用户选择写入决策反馈 |
| PermissionRequest 钩子 | 权限请求评分入库 + 写桥接事件;**高风险(≥60)弹托盘提醒**,前台小窗显示"最近权限请求"栏(15 秒自动隐藏) |
| Skill(`diffguard`) | 教 Agent 在高风险操作前自查、决策先查用户偏好 |
| 斜杠命令 | `/diffguard:review` `/diffguard:scan` `/diffguard:status` `/diffguard:decide` |

> 询问决策分析需要 DiffGuard 设置中**决策助手模式 ≠ 关闭**(建议"自动解析"开启)。
> UIA 扫窗通道对 Electron 应用(ZCode)不可读,询问分析走 PreToolUse 钩子通道,稳定可靠。

## 安装方式

### 方式一:插件包(推荐,开源分发)

本目录是一个合规的 ZCode 插件(`.zcode-plugin/plugin.json`)。任选其一:

- **本地目录**:ZCode → Settings → Plugin Management → Discover → `+` → 添加本仓库根目录
  (含 `marketplace.json`),然后安装 `diffguard-zcode`。
- **GitHub**:把仓库地址作为 marketplace 添加,后续随仓库更新。

### 方式二:CLI 安装器(写入配置文件,最可靠)

```bash
# 写入当前仓库(.zcode/config.json + skills + commands)
python -m bridge.cli install-zcode --dir <你的仓库> --scope workspace

# 或全局生效(~/.zcode/cli/config.json + ~/.zcode/skills)
python -m bridge.cli install-zcode --scope user

# 卸载
python -m bridge.cli uninstall-zcode --dir <你的仓库> --scope workspace
```

### 方式三:本仓库开发自用

仓库根的 `.zcode/config.json` 已预置(使用 `${ZCODE_PROJECT_DIR}` 模板变量,无机器特定路径),克隆即用。

## 前置条件与路径解析

- 依赖 DiffGuard 源码(或运行环境)。`zcode/bootstrap.py` 按以下顺序定位 DiffGuard 根目录:
  1. 环境变量 `DIFFGUARD_HOME`
  2. 插件目录上级(开发模式)
  3. `%APPDATA%/DiffGuard/source_path.txt`(install-zcode 自动写入)
- 钩子与 MCP 以 `python` 拉起,需要 python 在 PATH 上。

## 跳过钩子

- 临时:设置环境变量 `DIFFGUARD_HOOK_SKIP=1`
- 或创建标记文件 `%APPDATA%/DiffGuard/hook_skip`(无需环境变量权限的场景)

## 已知边界

- 插件清单中的 `${ZCODE_PLUGIN_ROOT}` 若在你使用的 ZCode 版本中未被展开(MCP 未生效),
  请改用方式二安装器(写入绝对路径)。
- PreToolUse 阻断仅基于本地启发式评分(密钥/危险命令/敏感路径),误报/漏报均可能,
 逃生通道见上节。
