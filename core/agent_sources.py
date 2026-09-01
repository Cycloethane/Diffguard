# -*- coding: utf-8 -*-
"""Agent 来源注册表:各 AI 编程助手识别标记的单一数据源。

此前 permission_parser 与 decision_parser 各维护一份 _SOURCE_MARKERS,
内容相近但判定规则不同(权限侧按标记计数 ≥2 归属,决策侧按来源名匹配);
本模块收敛数据、保留各解析器的判定规则,新增客户端(如 ZCode)只需
在此登记一处。
"""

# 权限请求来源识别标记(权限解析器按"累计命中 ≥2"归属来源,
# 因此这里含按钮文案类强证据:allow once / reject 等)
PERMISSION_SOURCE_MARKERS: dict[str, tuple[str, ...]] = {
    "OpenCode": ("opencode", "permission required", "allow once", "allow always", "reject"),
    "ZCode": ("zcode", "z-code"),
    "Cursor": ("cursor", "composer", "auto-review"),
    "Cline": ("cline", "api request", "terminal command"),
}

# 决策来源识别:决策解析器按来源名(dict 键)在文本中匹配,
# 迭代顺序即匹配优先级。
DECISION_SOURCE_ORDER: tuple[str, ...] = tuple(PERMISSION_SOURCE_MARKERS)

# Agent / 终端窗口标题特征词(UIA 通道前置过滤,减少无关窗口误报)
AGENT_WINDOW_TITLE_MARKERS: tuple[str, ...] = (
    "opencode",
    "open code",
    "zcode",
    "z-code",
    "cursor",
    "cline",
    "windsurf",
    "codex",
    "copilot",
    "gemini",
    "aider",
    "codeium",
    "trae",
    "agent",
    "终端",
    "terminal",
    "command prompt",
    "powershell",
    "cmd",
    "vscode",
)


def looks_like_agent_window(title: str) -> bool:
    """判断窗口标题是否像 AI 编程 Agent / 终端(UIA 通道前置过滤)。"""
    lower: str = title.lower()
    return any(m in lower for m in AGENT_WINDOW_TITLE_MARKERS)
