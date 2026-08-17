# OpenCode 插件：DiffGuard 集成

本插件为 OpenCode 提供三项能力：

1. **权限联动（功能4）**：拦截 `tool.execute` 中的高危命令，调用 DiffGuard 本地风险扫描，检测到高风险时输出告警。
2. **决策反馈注入（功能7）**：会话开始时提示 Agent 先读取用户决策偏好，避免重复询问。
3. **自动推送 diff 审查（功能3）**：工具执行产生代码变更时，可调用 `diffguardReview` 把 diff 交 DiffGuard 审查。

## 构建与安装

```bash
cd opencode/plugin
npm install
npm run build   # 生成 dist/index.js
```

在 `opencode.json` 中启用：

```jsonc
{
  "plugin": ["opencode/plugin/dist/index.js"]
}
```

## 配置前提

- DiffGuard 源码目录可通过环境变量 `DIFFGUARD_HOME` 指定；未设置时默认取插件目录的上两级。
- 打包版可改用 `DiffGuard.exe` 的 CLI 入口或 MCP。

## 注意

这是示例实现，按你的 OpenCode 插件 SDK 版本调整 hook 签名。若 SDK 版本不同，请参考 `opencode` 官方插件文档。
