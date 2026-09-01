# -*- coding: utf-8 -*-
"""权限风险评分模块：基于 PermissionPrompt 计算 0-100 的量化风险分数。

与 diff 风险评分（core/risk_score.py）独立，聚焦"目标敏感度 x 动作"的
本地启发式：可复现、可单测。历史经验修正点：
    1. 用 target_expanded（展开后的绝对路径）判定系统目录，避免把
       ~/Windows 误判为 C:\\Windows；~ 只展开到用户目录。
    2. 系统目录只认展开后的真实绝对路径，原始 target 含 ~ 时不判系统路径。
"""

import os
import re
from typing import Optional

from models.permission_prompt import PermissionPrompt, PromptAction, PromptType
from core.risk_score import clamp

# 敏感文件名正则（命中即视为敏感文件）
_SENSITIVE_FILE_RE = re.compile(
    r"(\.env(\..+)?|\.aws/|\.ssh/|id_rsa|id_ed25519|\.gpg|\.key$|\.pem$|"
    r"credentials|secrets?|token|\.gitconfig|\.npmrc|\.kube/config|"
    r"webhook|passwd|shadow|api[_-]?key|secret[_-]?file)",
    re.IGNORECASE,
)

# 系统目录前缀列表（target_expanded 在此前缀下即判定为"系统目录"）
_SYSTEM_DIR_PREFIXES: tuple[str, ...] = (
    r"C:\Windows",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\ProgramData",
    r"C:\Windows\System32",
    r"C:\Windows\System",
)

# 用户目录下的敏感子目录（命中则中等加分）
_HOME_SENSITIVE_SUBDIRS: tuple[str, ...] = (
    "Documents",
    "Desktop",
    "Downloads",
    ".\\.ssh",
    ".\\.aws",
)

# 动作基础分
_ACTION_BASE: dict[PromptAction, int] = {
    PromptAction.READ: 10,
    PromptAction.WRITE: 35,
    PromptAction.DELETE: 65,
    PromptAction.EXECUTE: 60,
    PromptAction.FETCH: 30,
    PromptAction.UNKNOWN: 25,
}

# 类型基础修正
_TYPE_BONUS: dict[PromptType, int] = {
    PromptType.CONFIG_CHANGE: 15,
    PromptType.UNKNOWN: 0,
}


def _norm(path: str) -> str:
    """规范化路径：去除引号、统一大小写与分隔符，用于前缀比较。"""
    p: str = path.strip().strip("\"'`")
    p = p.replace("/", "\\")
    return os.path.normcase(p)


def _is_system_path(path: str) -> bool:
    """判断 path（应为展开后的绝对路径）是否属于系统目录前缀。"""
    norm: str = _norm(path)
    return any(norm.startswith(_norm(prefix)) for prefix in _SYSTEM_DIR_PREFIXES)


def sensitive_file_hit(path: str) -> Optional[str]:
    """命中敏感文件命名规则时返回命中文件名（用于展示），否则 None。"""
    norm: str = _norm(path)
    m: Optional[re.Match[str]] = _SENSITIVE_FILE_RE.search(norm)
    return m.group(0) if m else None


def score_prompt(prompt: PermissionPrompt) -> tuple[int, list[str]]:
    """计算权限请求的风险分数与评分明细。

    返回:
        (score, contributions)：score 为 0-100 整数；contributions 为
        可展示的加分原因列表，例如 "动作:删除 (+65)"。
    """
    contributions: list[str] = []

    action: PromptAction = prompt.action or PromptAction.UNKNOWN
    prompt_type: PromptType = prompt.prompt_type or PromptType.UNKNOWN

    # 1. 动作基础分
    base: int = _ACTION_BASE.get(action, _ACTION_BASE[PromptAction.UNKNOWN])
    if base:
        contributions.append(f"动作:{action.value} (+{base})")

    # 2. 类型加分
    type_bonus: int = _TYPE_BONUS.get(prompt_type, 0)
    if type_bonus:
        contributions.append(f"类型:{prompt_type.value} (+{type_bonus})")

    score: int = base + type_bonus

    # 3. 目标敏感度（基于展开后的绝对路径；~/Windows 不会命中系统前缀）
    target: str = prompt.target_expanded or prompt.target or ""
    if target and target != "unknown":
        if _is_system_path(target):
            score += 30
            contributions.append(f"系统目录: {target} (+30)")
        elif sensitive_file_hit(target):
            score += 25
            contributions.append(
                f"敏感文件: {sensitive_file_hit(target)} (+25)"
            )
        else:
            home: str = os.path.expanduser("~")
            if home and _norm(target).startswith(_norm(home)):
                rel: str = _norm(target)[len(_norm(home)):]
                if any(_norm(s).lstrip("\\") in rel for s in _HOME_SENSITIVE_SUBDIRS):
                    score += 15
                    contributions.append(f"用户目录敏感位置{rel} (+15)")
    elif prompt.prompt_type == PromptType.FILE_ACCESS:
        # 无法展开路径时给出保守基础加分
        score += 10
        contributions.append("路径解析失败，保守加分 (+10)")

    # 4. 原始文本含危险关键词
    text: str = (prompt.raw_text or "").lower()
    danger_words: dict[str, str] = {
        "format /": "格式化分区",
        "rm -rf": "删除根目录",
        "--force": "强制覆盖",
        "overwrite": "覆盖已有文件",
    }
    for token, label in danger_words.items():
        if token in text:
            score += 20
            contributions.append(f"危险操作:{label} (+20)")
            break

    return clamp(score), contributions


def risk_level(prompt: PermissionPrompt) -> str:
    """将风险分数映射为三档等级（low/medium/high），与历史记录一致。"""
    if prompt.risk_score < 40:
        return "low"
    if prompt.risk_score < 60:
        return "medium"
    return "high"