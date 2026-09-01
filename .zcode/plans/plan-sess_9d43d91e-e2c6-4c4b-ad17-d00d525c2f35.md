# DiffGuard 全面重构 + ZCode 深度绑定 实施计划

## 目标与原则

1. **全面重构**:拆分 2243 行的 `ui/app.py` 上帝类、统一 3 个 watcher、收敛 3 份 DB engine、抽取共享 AI 客户端、清理死代码与已知 bug。
2. **多客户端架构**:OpenCode 与 ZCode 平级接入,配置键中立化(`agent_bridge`/`agent_mcp`),来源标识全链路透传。
3. **ZCode 全绑定面**:MCP Server + Skill + 斜杠命令 + Hooks 联动 + 插件包,四层全做。
4. **开源友好(对"利于开源的方向"的回答)**:让 **DiffGuard 仓库本身就是一个 ZCode 插件源**——`zcode/` 目录符合 `.zcode-plugin/plugin.json` 插件规范,其他用户把本仓库(或其 release zip)作为本地/GitHub marketplace 添加即可一键安装,零手工配置;彻底消除 `D:/SP_DiffGuard` 硬编码;补 LICENSE/.gitignore/CI。CLI 安装器(`install-zcode --scope workspace|user`)作为辅助分发路径,与 `install-git-hook` 对称。

每阶段完成后跑 pytest + GUI 冒烟,任何时刻 `main.py` 可启动(绞杀者模式:先建新结构、迁移调用、再删旧代码)。

---

## Phase 0:安全网(前置,约 0.5 天)

- **git init** + `.gitignore`(`__pycache__/`、`dist/`、`build/`、`.pytest_cache/`、`*.db`、`opencode/plugin/dist/`、`*.spec`)+ 初始提交。
- 新建 `tests/` 目录,为纯逻辑层补最小 pytest 基线(这些模块不依赖 Tk,可测性最好),锁定**重构前行为**:
  - `tests/test_risk_score.py`:分带/等级映射、`compute_risk_score` 各触发因素、`score_text` 危险命令与敏感路径。
  - `tests/test_diff_parser.py`:strict/lenient 双路径、风险标记(密钥/配置/删除/依赖)、新文件识别。
  - `tests/test_permission_parser.py` 与 `tests/test_decision_parser.py`:证据判定、选项提取、来源识别、豁免词。
  - `tests/test_permission_risk.py`:动作基础分 + 敏感路径叠加。
  - `tests/test_store.py`:monkeypatch `bridge_dir()` 到 tmp_path,覆盖 5 个 JSON 文件的读写协议与 500 条截断。
  - `tests/test_mcp_server.py`:JSON-RPC 分发(initialize/tools/list/tools/call/未知方法 -32601/异常 -32603)。
  - `tests/test_cli.py`:scan/submit-decision 基本路径。
- 运行 pytest 全绿,作为后续每阶段的回归门禁。

## Phase 1:core/models 基础层重构(约 1 天)

1. **`models/db.py` 单一 engine**:新增 `get_engine()` 惰性创建(建目录 + create_engine + 一次 `create_all`),消除 `history.py:57-68`、`permission_history.py:66-77`、`decision_history.py:58-69` 三份模块导入期副作用的 engine 样板;三个模块的查询函数签名不变。
2. **`core/ai_client.py` 共享流式客户端**:`make_client(config)` + `stream_chat(...)` 生成器 + 统一 5 分支异常处理(错误行前缀参数化:`"\n\n[错误] "` vs `"#ERROR# "`);`reviewer.py` 与 `decision_explainer.py` 只保留各自 SYSTEM_PROMPT 与输出协议(顺带删 decision_explainer.py:29 死导入)。
3. **`core/agent_sources.py` 来源注册表**:单一数据源定义各 Agent 的来源标记(OpenCode/Cursor/Cline/…/**新增 ZCode**),`permission_parser.py:22` 与 `decision_parser.py:361` 的两份 `_SOURCE_MARKERS` 改从注册表读取(保留两者不同的判定规则);`decision_watcher.py:304` `_AGENT_TITLE_MARKERS` 加入 `"zcode"`。
4. **解除 core↔bridge 包级环**:`decision_watcher.py:230` 延迟导入 `bridge.store` 改为构造注入(回调 `poll_bridge: Optional[Callable]`,由 app.py 组装),core 不再依赖 bridge。
5. **`core/watchers/base.py` watcher 基类**:抽取三处重复的线程骨架(stop_event/daemon/循环/异常吞噬)、UIA/COM 初始化上下文、`_seen` 去重预算 + `_prune_seen`、`_collect_texts`、`_own_pid`、排除自身窗口;三个 watcher 变为薄子类,只声明通道差异。
   - **统一降级语义(有意的行为变更)**:UIA 不可用时改为"UIA 通道禁用、其余通道照常",`PermissionWatcher` 不再整条死掉(`permission_watcher.py:91`),保留 `available` 标志供 UI 状态栏显示;`ClipboardWatcher` 无 UIA 需求,不受影响。
   - 修复 `decision_watcher.py:31` 死常量 `_BRIDGE_INTERVAL`(真正用于 bridge 轮询节流)。

## Phase 2:客户端中立化(约 0.5 天)

1. **配置迁移**:`models/config.py` 的 `opencode_bridge`/`opencode_mcp` → `agent_bridge`/`agent_mcp`;`load_config()` 读到旧键自动映射并回写新 config.json。注意与 AI 提供方常量 `opencode_zen`/`opencode_go` 语义无关,不动。
2. **让开关真正生效**:关闭 `agent_bridge` 时 `decision_watcher` 不轮询 `agent_decision_in.json`、`app._on_decision_chosen` 不回写 `decision_feedback.json`;关闭 `agent_mcp` 时 MCP server 对 `submit_decision`/`review_*` 返回提示文本(当前两个开关纯装饰,不 gate 任何行为)。
3. **source 透传**:`store.write_agent_decision()` 增加 `source` 参数;`decision_watcher._poll_bridge_decision`(`decision_watcher.py:252`)改为使用文件里的 `source` 字段而非硬编码 `"OpenCode"`。
4. **UI 文案**:`settings_view.py:306-321` "OpenCode 集成" 区块改 "Agent 集成(OpenCode / ZCode / Cursor…)",开关文案与说明同步。

## Phase 3:ZCode 深度绑定(约 1.5 天)

新增 `zcode/` 目录,**本身即一个合规 ZCode 插件包**:

```
zcode/
├── .zcode-plugin/plugin.json        # name: diffguard-zcode;声明 skills/commands/hooks/mcpServers
├── skills/diffguard/SKILL.md        # 由 opencode/SKILL.md 中立化改编:审查前自查/决策先查偏好/submit_decision 闭环
├── commands/
│   ├── review.md                    # /diffguard:review —— 审查当前 git diff(调 review_diff)
│   ├── scan.md                      # /diffguard:scan —— 本地风险扫描(scan_risk)
│   ├── status.md                    # /diffguard:status —— 状态与配置快照(get_status)
│   └── decide.md                    # /diffguard:decide —— 提交决策请求给 DiffGuard 浮窗
├── hooks/hooks.json                 # PreToolUse / PermissionRequest 事件注册
└── mcp/diffguard.json               # stdio server:python -m bridge.mcp_server
```

- **MCP(零代码改动)**:`bridge/mcp_server.py` 本身客户端无关,ZCode 以 stdio 拉起即可;仅把 docstring/serverInfo 文案中立化,顺手清理未用导入 `get_review_by_id`。
- **Hooks 联动(比 OpenCode TS 插件更深)**:新增 `bridge/hooks_runner.py`:
  - `PreToolUse`:解析工具调用入参(Bash command / Write·Edit 的 path+content),调 `core.risk_score.score_text`,high 时按 ZCode hooks 阻断约定 exit 非零并输出原因(实现时对照 ZCode hooks 规范确认退出码/JSON 格式),中低风险放行;
  - `PermissionRequest`:把事件内容写入 `permission_history`(审计入库),与 GUI 浮窗通道互补。
- **决策闭环**:ZCode Agent 调 `submit_decision(source="ZCode")` → `agent_decision_in.json` → DecisionWatcher 弹浮窗 → 用户选择 → `decision_feedback.json` + DecisionRecord → Agent 用 `get_decision_feedback` 读回,避免重复询问。
- **路径无关(开源关键)**:所有注册处不再硬编码 `D:/SP_DiffGuard`——MCP 命令统一 `python -m bridge.mcpServer`,`cwd` 由插件安装/安装器按实际部署路径生成;若插件规范支持 `${DIR}` 类插值则优先使用(实现时验证,不支持则安装器展开绝对路径)。同步修 `opencode/plugin/src/index.ts:14,37` 的 cwd 硬编码(改读 `DIFFGUARD_HOME` 环境变量,回退自动探测),并消除 TS 中 `JSON.stringify` 拼命令的注入隐患(改 spawn 数组参数)。
- **CLI 安装器(辅助分发)**:`bridge/cli.py` 新增:
  - `install-zcode --dir <目标仓库> --scope workspace|user`:workspace 写 `<目标>/.zcode/config.json`(mcp.servers + hooks 且 `hooks.enabled: true`)并复制 skill/commands;user 写 `~/.zcode/cli/config.json` 与 `~/.zcode/skills/`;
  - `uninstall-zcode` 反向清理;与 `install-git-hook` 风格对称。
- **本仓库自绑定**:在 D:\SP_DiffGuard 加 `.zcode/config.json`(注册 mcp + hooks),开发者克隆后开箱即用。
- **补齐/清理 bridge 半成品**:`status.json` 由 GUI 启动/退出时 `write_status`(让 `get_status` 的 bridge_status 不再恒空)或删除该字段;`report_requests/results` 读函数无调用者——补 CLI `review-requests` 查询或删除,二选一(默认:删除死函数,保留协议写入侧)。

## Phase 4:UI 重构,app.py 拆分(约 2 天,风险最高放后)

1. **落地 `ui/modules/` 空包计划**:
   - `ui/modules/base.py`:Module 协议(`key/title/icon/build(container)`);
   - `review_module.py`(仪表盘+文件列表+diff 高亮渲染+报告区)、`history_module.py`、`permission_module.py`、`decision_module.py`、`settings_module.py`;
   - `_on_module_selected` 改注册表驱动,消除 if/elif。
2. **控制器抽取**(app.py 降为薄壳组装,约 2243 行 → 预计 <400 行):
   - `ui/controllers/watcher_manager.py`:3 个 watcher 的 start/stop/restart + 配置热切换(**消灭 settings_view 保存回调里 46 行的 `_on_config_saved` 闭包**);
   - `ui/controllers/review_flow.py`:diff 载入/仪表/文件列表/审查流式;合并 `_apply_diff` 与 `_restore_review` 的重复重置逻辑;
   - `ui/controllers/permission_flow.py`:自动放行/托盘/浮窗/UIA 回写;
   - `ui/controllers/decision_flow.py`:决策浮窗/AI 解析流/决策闭环(bridge + DB);
   - `ui/poller.py`:通用 queue→after 轮询器,**修复 `restart_decision_watching` 双调度 bug**(app.py:997-998 会二次调度轮询循环),并支持 watcher 停止时取消轮询(当前 6 个轮询循环空转不停)。
3. **组件归位与解耦**:
   - `HistoryDialog`/`DetailDialog`/`PermissionHistoryDialog`(app.py:1910-2243)迁出 → `ui/dialogs.py`;与 `HistoryView`/`PermissionHistoryView` 双轨并存统一(导航用 View,工具栏入口收敛到一处);
   - `_bind_tooltip`/`_icon_button` 等工具 → `ui/widgets.py`,消除 `nav_frame.py:93 → app.py` 私有函数反向导入;
   - `overlay.py`/`decision_view.py` 改依赖控制器公开 API,不再鸭子类型访问 `app._decision_pending` 等私有属性;`main.py` 改调公开方法 `on_wizard_done`。
4. **死代码清理**:`ui/mascot.py`(全项目无引用)、`_make_toolbar_button`、RiskGauge 死导入、`_watcher_online` 死属性、`_current_report_id` 只写不读、`_make_option` 等孤儿函数。

## Phase 5:文档、开源就绪与验证(约 0.5 天)

- **README 重写**:新架构图、模块职责表、ZCode 三种接入方式(插件包 marketplace / `install-zcode` 安装器 / 手动注册)、OpenCode 兼容说明、贡献指南入口;`使用说明书.md` 与 `opencode/SKILL.md` 同步中立化。
- **开源就绪**:LICENSE(**待定:默认建议 MIT,执行时确认一次**)、"仅供内部测试"字样改为开源声明、可选 GitHub Actions(pytest + pyinstaller 构建)。
- **验证清单**:
  - pytest 全量回归;
  - GUI 冒烟:载入 diff→本地评分→AI 审查→导出;粘贴权限文本→浮窗→回写;`agent_decision_in.json` 手写→决策闭环;
  - ZCode 实装端到端:插件/安装器接入 → MCP 工具可见 → `/diffguard:scan` 可用 → PreToolUse 对高危 Bash 命令阻断演示 → submit_decision 决策闭环回读;
  - OpenCode 回归:MCP 注册示例仍可用,TS 插件在新 cwd 逻辑下工作。

---

## 关键风险与对策

| 风险 | 对策 |
|---|---|
| 全项目零测试,重构无护栏 | Phase 0 先建纯逻辑层测试基线;UI 层靠冒烟清单 |
| app.py 拆分牵一发动全身 | 绞杀者模式:控制器先并行存在,逐模块迁移调用,最后删旧代码;每步可启动 |
| PermissionWatcher 降级语义变更 | 属有意改进,在状态栏明示 "UIA 不可用",CHANGELOG 记录 |
| ZCode hooks/插件的阻断格式细节未定 | 实现时对照 ZCode hooks 规范文档验证;不支持阻断时降级为"告警不阻断" |
| 旧 config.json 兼容 | load_config 旧键自动迁移并回写 |

## 待定项(不阻塞批准,执行时确认)

1. LICENSE 类型(默认 MIT)。
2. `report_requests` 半成品协议:删除死读函数(默认)还是补全查询命令。
3. ZCode 插件 mcpServers 是否支持路径插值;不支持则由安装器展开绝对路径。
