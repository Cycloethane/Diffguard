# -*- coding: utf-8 -*-
"""权限审批数据模型：定义权限请求的类型、动作与数据结构。

用于统一"Windows UI Automation 通道"与"剪贴板嗅探通道"产出的权限
审批数据，供解析层/风险层/UI 层共享。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class PromptType(str, Enum):
    """权限请求的类型。"""

    FILE_ACCESS = "file_access"
    COMMAND_EXEC = "command_exec"
    NETWORK_FETCH = "network_fetch"
    CONFIG_CHANGE = "config_change"
    UNKNOWN = "unknown"


class PromptAction(str, Enum):
    """权限请求对目标施加的动作。"""

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    DELETE = "delete"
    FETCH = "fetch"
    UNKNOWN = "unknown"


@dataclass
class PermissionPrompt:
    """一次权限审批请求的完整描述。

    属性:
        source: 来源（OpenCode / Cursor / Cline / Clipboard / Unknown）。
        prompt_type: 请求类型（文件/命令/网络/配置/未知）。
        action: 施加的动作（读/写/执行/删除/拉取）。
        target: 目标字符串（路径/URL/命令）。
        target_expanded: 展开后的绝对路径（如适用）。
        options: 检测到的用户选项按钮文本列表。
        raw_text: 检测到的原始完整文本。
        window_handle: 窗口句柄（UIA 通道检测时有值，剪贴板通道为 None）。
        risk_score: 风险评分（0-100），由风险引擎计算后回填。
        breakdown: 风险评分明细（用于详情展示）。
        user_decision: 用户决策（pending/once_allowed/always_allowed/rejected）。
    """

    source: str = "Unknown"
    prompt_type: PromptType = PromptType.UNKNOWN
    action: PromptAction = PromptAction.UNKNOWN
    target: str = ""
    target_expanded: str = ""
    options: List[str] = field(default_factory=list)
    raw_text: str = ""
    window_handle: Optional[int] = None
    risk_score: int = 0
    breakdown: List[str] = field(default_factory=list)
    user_decision: Optional[str] = None
    db_id: Optional[int] = None