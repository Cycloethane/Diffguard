# -*- coding: utf-8 -*-
"""ZCode hooks 执行器:PreToolUse 风险扫描与 PermissionRequest 审计。

由 zcode/bootstrap.py 以进程方式拉起(hooks.json 的 process 型钩子),
stdin 收到事件 JSON,退出码表达决策:

    0   放行(默认;审计失败也不阻断)
    2   阻断(仅 PreToolUse 且本地风险评分 level == high)

stdout 保持为空(输出协议要求为空或严格 JSON),提示信息写 stderr。
跳过扫描的两种方式(与 git 钩子一致 + 文件级逃生通道):
    1. 环境变量 DIFFGUARD_HOOK_SKIP=1
    2. 标记文件 %APPDATA%/DiffGuard/hook_skip 存在

事件 JSON 的字段名按 ZCode 约定解析,兼容 tool_name/tool_input 与
tool/input 两种写法;工具别名 ApplyPatch 视作 Write/Edit。
"""

import json
import os
import sys
from typing import Any

# PreToolUse 扫描的工具与文本字段映射
_BASH_TEXT_FIELDS: tuple[str, ...] = ("command", "cmd", "script")
_FILE_PATH_FIELDS: tuple[str, ...] = ("file_path", "path", "filename")
_FILE_TEXT_FIELDS: tuple[str, ...] = ("content", "new_string", "newStr", "diff", "edits")

# 视为文件写入类的工具名(含别名)
_WRITE_TOOLS: frozenset[str] = frozenset({"Write", "Edit", "ApplyPatch", "MultiEdit"})
# 视为命令执行类的工具名
_BASH_TOOLS: frozenset[str] = frozenset({"Bash", "Execute", "Terminal"})


def _extract_text(tool_name: str, tool_input: dict) -> str:
    """从工具入参中提取待扫描文本(命令行或文件路径+新内容)。"""
    if not isinstance(tool_input, dict):
        return ""
    parts: list[str] = []
    if tool_name in _BASH_TOOLS:
        for field in _BASH_TEXT_FIELDS:
            value = tool_input.get(field)
            if isinstance(value, str) and value.strip():
                parts.append(value)
                break
    elif tool_name in _WRITE_TOOLS:
        for field in _FILE_PATH_FIELDS:
            value = tool_input.get(field)
            if isinstance(value, str) and value.strip():
                parts.append(value)
                break
        for field in _FILE_TEXT_FIELDS:
            value = tool_input.get(field)
            if isinstance(value, str) and value.strip():
                parts.append(value)
                break
            if isinstance(value, list):  # MultiEdit 的 edits 数组
                try:
                    parts.append(json.dumps(value, ensure_ascii=False))
                except (TypeError, ValueError):
                    pass
                break
    return "\n".join(p for p in parts if p)


def _parse_payload(stdin_text: str) -> tuple[str, dict]:
    """解析事件 JSON,返回 (tool_name, tool_input);解析失败返回空值。"""
    try:
        payload: dict = json.loads(stdin_text or "{}")
    except json.JSONDecodeError:
        return "", {}
    if not isinstance(payload, dict):
        return "", {}
    tool_name: str = str(payload.get("tool_name") or payload.get("tool") or "")
    tool_input: Any = payload.get("tool_input") or payload.get("input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    return tool_name, tool_input


def _hook_skipped() -> bool:
    """是否跳过扫描:环境变量或标记文件。"""
    if os.environ.get("DIFFGUARD_HOOK_SKIP") == "1":
        return True
    marker = os.path.join(os.environ.get("APPDATA", ""), "DiffGuard", "hook_skip")
    return os.path.isfile(marker)


def pre_tool_use_main() -> int:
    """PreToolUse 钩子:对命令/写入内容做本地风险扫描,高风险阻断。"""
    if _hook_skipped():
        return 0

    from core.risk_score import score_text

    tool_name, tool_input = _parse_payload(sys.stdin.read())
    text: str = _extract_text(tool_name, tool_input)
    if not text:
        return 0
    try:
        res = score_text(text, None)
    except Exception:
        return 0  # 扫描失败不阻断工具调用

    if res.get("level") == "high":
        findings = "、".join(str(f) for f in res.get("findings", [])) or "无明细"
        sys.stderr.write(
            f"[DiffGuard] 高风险操作已阻断（score={res.get('score')}）：{findings}\n"
            f"[DiffGuard] 如确需执行，请设置环境变量 DIFFGUARD_HOOK_SKIP=1 后重试。\n"
        )
        return 2
    return 0


def permission_request_main() -> int:
    """PermissionRequest 钩子:把权限请求写入权限审计库(仅记录,不决策)。"""
    from models.permission_history import save_permission
    from models.permission_prompt import PermissionPrompt, PromptAction, PromptType

    tool_name, tool_input = _parse_payload(sys.stdin.read())
    try:
        raw = json.dumps({"tool": tool_name, "input": tool_input}, ensure_ascii=False)
        prompt = PermissionPrompt(
            source="ZCode",
            prompt_type=(
                PromptType.COMMAND_EXEC if tool_name in _BASH_TOOLS else PromptType.UNKNOWN
            ),
            action=PromptAction.UNKNOWN,
            target=tool_name,
            raw_text=raw[:4000],
        )
        from core.risk_score import score_text

        res = score_text(_extract_text(tool_name, tool_input), None)
        prompt.risk_score = int(res.get("score", 0))
        prompt.breakdown = [str(f) for f in res.get("findings", [])]
        save_permission(prompt)
    except Exception:
        # 审计失败不影响权限流程
        pass
    return 0


def main() -> None:
    """命令行入口:python -m bridge.hooks_runner <pre_tool_use|permission_request>"""
    command: str = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "pre_tool_use":
        sys.exit(pre_tool_use_main())
    elif command == "permission_request":
        sys.exit(permission_request_main())
    else:
        sys.stderr.write("用法: python -m bridge.hooks_runner <pre_tool_use|permission_request>\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
