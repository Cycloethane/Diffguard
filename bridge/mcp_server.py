# -*- coding: utf-8 -*-
"""DiffGuard MCP Server：向 AI Agent（ZCode / OpenCode 等）暴露审查/权限/决策能力。

实现方式：
    - 零第三方依赖的最小 MCP 服务器：基于 JSON-RPC 2.0，stdio 传输。
    - 协议子集：initialize / tools/list / tools/call / notifications/initialized。
    - 可在 Agent 配置中以 command 方式拉起（ZCode 经 zcode/ 插件或
      install-zcode 注册；OpenCode 在 opencode.json 的 mcp 段注册）。
    也可手动运行：python -m bridge.mcp_server

暴露工具：
    get_status                  获取当前状态快照（模式、监听、最近决策数）。
    review_diff                 审查一段 diff（流式收集后整段返回）。
    review_file                 审查工作区内某个文件的当前 diff（需 git）。
    get_recent_reviews          查询最近 AI 审查历史。
    get_recent_permissions      查询最近权限审批记录。
    get_decision_feedback       读取用户最近的决策偏好（决策反馈闭环）。
    get_decision_stats          用户决策偏好统计。
    submit_decision             向 DiffGuard 提交一个待决策请求（精确通道）。
    scan_risk                   对文本做本地风险评分（不调用 AI）。
"""

import json
import os
import sys
import traceback
from collections.abc import Iterator
from typing import Any, Optional

# 保证可以以 python -m bridge.mcp_server 或直接运行方式导入项目包
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from bridge import store
from core.risk_score import score_text  # type: ignore
from models.config import load_config
from models.history import get_recent as get_recent_reviews
from models.permission_history import get_recent_permissions
from models.decision_history import get_recent_decisions, decision_stats

_PROTOCOL_VERSION: str = "2024-11-05"
_SERVER_VERSION: str = "0.3.0"


# ----------------------------------------------------------------------
# 工具实现
# ----------------------------------------------------------------------
def _get_status() -> dict:
    cfg = load_config()
    status = store.read_status()
    try:
        recents = get_recent_decisions(20)
        last_decision = None
        if recents:
            last = recents[0]
            last_decision = {
                "question": last.question,
                "chosen": last.user_decision,
                "timestamp": last.timestamp.isoformat(),
            }
    except Exception:
        last_decision = None
    return {
        "configured": bool(cfg.api_key),
        "model": cfg.model,
        "decision_assistant": cfg.decision_assistant,
        "decision_level": cfg.decision_level,
        "permission_monitor": cfg.permission_monitor,
        "auto_clipboard": cfg.auto_clipboard,
        "agent_bridge": cfg.agent_bridge,
        "agent_mcp": cfg.agent_mcp,
        "bridge_status": status,
        "recent_decision_count": len(recents) if "recents" in locals() else None,
        "last_decision": last_decision,
    }


def _mcp_disabled_hint() -> str:
    """agent_mcp 关闭时返回给 Agent 的提示文本。"""
    return "[提示] Agent 决策请求通道已在 DiffGuard 设置中关闭（agent_mcp=False），本工具不可用。"


def _review_diff(diff_text: str, title: str = "") -> str:
    """调用 AI 审查一段 diff，收集全部流式输出后返回。"""
    from core.reviewer import analyze_diff

    cfg = load_config()
    if not cfg.agent_mcp:
        return _mcp_disabled_hint()
    parts: list[str] = []
    for chunk in analyze_diff(diff_text or "", cfg):
        parts.append(chunk)
    report = "".join(parts)
    if title:
        store.mark_review_request_done(int(title), report) if title.isdigit() else None
    return report or "[无输出]"


def _review_file(path: str, base_ref: str = "HEAD") -> str:
    """审查某文件的 git diff（相对工作区根目录）。"""
    import subprocess

    cfg = load_config()
    if not cfg.agent_mcp:
        return _mcp_disabled_hint()
    cwd = os.getcwd()
    try:
        proc = subprocess.run(
            ["git", "diff", base_ref, "--", path],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=30,
        )
        diff_text = proc.stdout or ""
        if not diff_text.strip():
            # 可能是未跟踪文件，尝试取完整内容
            proc2 = subprocess.run(
                ["git", "status", "--porcelain", "--", path],
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=15,
            )
            if proc2.stdout.strip().startswith("??"):
                if os.path.isfile(path):
                    diff_text = f"# 新文件：{path}\n" + open(path, encoding="utf-8", errors="ignore").read()
        if not diff_text.strip():
            return f"[提示] 未获取到 {path} 的 diff（可能无变更或不在 git 仓库）。"
    except Exception as exc:
        return f"[错误] 获取 git diff 失败: {exc}"
    from core.reviewer import analyze_diff

    parts = list(analyze_diff(diff_text, cfg))
    return "".join(parts) or "[无输出]"


def _get_reviews(limit: int = 10) -> str:
    try:
        recs = get_recent_reviews(max(1, min(100, limit)))
        if not recs:
            return "暂无审查历史。"
        lines = ["最近 AI 审查历史："]
        for r in recs:
            lines.append(
                f"- [{r.timestamp:%Y-%m-%d %H:%M}] {r.title} | 文件数={r.file_count} "
                f"风险={r.risk_level} 决策={r.user_decision} id={r.id}"
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"[错误] 查询失败: {exc}"


def _get_permissions(limit: int = 10) -> str:
    try:
        recs = get_recent_permissions(max(1, min(100, limit)))
        if not recs:
            return "暂无权限审批记录。"
        lines = ["最近权限审批记录："]
        for r in recs:
            lines.append(
                f"- [{r.timestamp:%Y-%m-%d %H:%M}] {r.source} | {r.action} {r.target[:60]} "
                f"风险={r.risk_score} 决策={r.user_decision} id={r.id}"
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"[错误] 查询失败: {exc}"


def _get_feedback(limit: int = 20) -> str:
    fb = store.read_decision_feedback(limit)
    if not fb:
        return "暂无决策反馈记录。"
    lines = ["用户最近的决策偏好（供参考，避免重复询问同类问题）："]
    for d in fb:
        lines.append(
            f"- [{d.get('timestamp','')}] {d.get('question','')} "
            f"→ 用户选择 {d.get('chosen','')}（{d.get('chosen_text','')}）"
        )
    return "\n".join(lines)


def _get_decision_stats() -> str:
    try:
        stats = decision_stats(200)
        by_source = stats.get("by_source", {})
        src_line = "，".join(f"{k}:{v}" for k, v in by_source.items()) or "无"
        lines = [
            f"决策总数: {stats['total']}，已作选择: {stats['with_choice']}",
            f"来源分布: {src_line}",
            "最近偏好:",
        ]
        prefs = stats.get("recent_preferences", [])[-10:]
        for p in prefs:
            lines.append(f"  - {p['timestamp'][:16]} {p['question']} → {p['chosen']}")
        return "\n".join(lines)
    except Exception as exc:
        return f"[错误] 统计失败: {exc}"


def _submit_decision(question: str, options: list, context: str = "", source: str = "MCP") -> str:
    """向 DiffGuard 提交待决策请求；DiffGuard 前台会弹出决策浮窗。"""
    if not load_config().agent_mcp:
        return _mcp_disabled_hint()
    if not isinstance(options, list) or len(options) < 2:
        return "[错误] 选项至少需要两个：options=[{'key':'A','text':'...'}, ...]"
    ok = store.write_agent_decision(question, options, context, source=source or "MCP")
    if not ok:
        return "[错误] 写入决策请求失败。"
    return (
        f"已向 DiffGuard 提交决策请求：{question}（{len(options)} 个选项）。"
        "请等待用户在 DiffGuard 决策浮窗中作出选择，"
        "然后用 get_decision_feedback 读取结果。"
    )


def _scan_risk(text: str) -> str:
    try:
        res = score_text(text or "", load_config())
        return json.dumps(res, ensure_ascii=False, indent=2, default=str)
    except Exception as exc:
        return f"[错误] 风险评分失败: {exc}"


# 工具注册表
_TOOLS: list[dict] = [
    {
        "name": "get_status",
        "description": "获取 DiffGuard 当前状态：是否配置 API、当前模型、决策助手模式、权限监控开关、最近决策情况。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "review_diff",
        "description": "调用 AI 审查一段 git diff 文本，返回中文结构化审查报告（含风险与建议）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "diff_text": {"type": "string", "description": "待审查的 diff 全文"},
                "title": {"type": "string", "description": "可选：审查请求 id 或标题"},
            },
            "required": ["diff_text"],
        },
    },
    {
        "name": "review_file",
        "description": "审查某个文件的当前 git diff（相对当前工作目录）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "base_ref": {"type": "string", "description": "基准 git 引用，默认 HEAD"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "get_recent_reviews",
        "description": "查询最近 AI 审查历史（标题、风险、用户决策）。",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "条数，默认10"}},
        },
    },
    {
        "name": "get_recent_permissions",
        "description": "查询最近权限审批记录（来源、动作、风险分、用户决策）。",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "条数，默认10"}},
        },
    },
    {
        "name": "get_decision_feedback",
        "description": "读取用户最近的决策偏好记录，避免重复询问同类问题。",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "条数，默认20"}},
        },
    },
    {
        "name": "get_decision_stats",
        "description": "汇总用户决策偏好统计（总数、来源、最近偏好）。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "submit_decision",
        "description": "向 DiffGuard 提交一个待决策请求（精确通道），DiffGuard 将弹出决策浮窗让用户选择。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "决策问题"},
                "options": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "选项列表，如 [{'key':'A','text':'...'},{'key':'B','text':'...'}]",
                },
                "context": {"type": "string", "description": "可选上下文"},
                "source": {
                    "type": "string",
                    "description": "提交来源标识（如 'ZCode' / 'OpenCode'），默认 'MCP'",
                },
            },
            "required": ["question", "options"],
        },
    },
    {
        "name": "scan_risk",
        "description": "对文本做本地风险评分（不调用 AI）：识别密钥、危险路径、危险命令等。",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "待扫描文本"}},
            "required": ["text"],
        },
    },
]

_TOOL_HANDLERS: dict[str, Any] = {
    "get_status": lambda args: _get_status(),
    "review_diff": lambda args: _review_diff(args.get("diff_text", ""), args.get("title", "")),
    "review_file": lambda args: _review_file(args.get("path", ""), args.get("base_ref", "HEAD")),
    "get_recent_reviews": lambda args: _get_reviews(int(args.get("limit", 10) or 10)),
    "get_recent_permissions": lambda args: _get_permissions(int(args.get("limit", 10) or 10)),
    "get_decision_feedback": lambda args: _get_feedback(int(args.get("limit", 20) or 20)),
    "get_decision_stats": lambda args: _get_decision_stats(),
    "submit_decision": lambda args: _submit_decision(
        args.get("question", ""),
        args.get("options", []),
        args.get("context", ""),
        str(args.get("source", "MCP") or "MCP"),
    ),
    "scan_risk": lambda args: _scan_risk(args.get("text", "")),
}


# ----------------------------------------------------------------------
# JSON-RPC 协议处理
# ----------------------------------------------------------------------
def _result(msg_id: Any, result: Any) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}, ensure_ascii=False)


def _error(msg_id: Any, code: int, message: str) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}},
        ensure_ascii=False,
    )


def _handle_request(msg: dict) -> Optional[str]:
    """处理一条请求消息，返回要写入 stdout 的响应；通知返回 None。"""
    method: str = msg.get("method", "")
    msg_id: Any = msg.get("id")
    params: dict = msg.get("params", {}) or {}

    if method == "initialize":
        return _result(
            msg_id,
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "diffguard-mcp", "version": _SERVER_VERSION},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, {"tools": _TOOLS})
    if method == "tools/call":
        name: str = params.get("name", "")
        args: dict = params.get("arguments", {}) or {}
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return _error(msg_id, -32601, f"Unknown tool: {name}")
        try:
            text = handler(args)
            return _result(
                msg_id,
                {"content": [{"type": "text", "text": text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)}]},
            )
        except Exception as exc:
            logger.exception("MCP 工具 {} 执行异常", name)
            return _error(msg_id, -32603, f"Tool error: {exc}\n{traceback.format_exc(limit=3)}")
    return _error(msg_id, -32601, f"Method not found: {method}")


def run_stdio_loop() -> None:
    """主循环：从 stdin 逐行读取 JSON-RPC 消息，响应写 stdout。"""
    logger.info("DiffGuard MCP server 启动（stdio）")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("忽略非 JSON 行: {}", line[:80])
            continue
        if "method" not in msg:
            continue
        try:
            resp = _handle_request(msg)
        except Exception as exc:
            logger.exception("处理消息异常")
            resp = _error(msg.get("id"), -32603, str(exc))
        if resp:
            try:
                sys.stdout.write(resp + "\n")
                sys.stdout.flush()
            except (BrokenPipeError, OSError):
                break
    logger.info("DiffGuard MCP server 退出")


def main() -> None:
    """命令行入口：python -m bridge.mcp_server"""
    from utils.logger import setup_logger

    setup_logger()
    try:
        run_stdio_loop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
