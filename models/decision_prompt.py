# -*- coding: utf-8 -*-
"""决策助手数据模型：描述 CodingAgent 向用户抛出的"需要决策"的问题与选项。

与 models/permission_prompt.py 区分：
    - PermissionPrompt 描述"权限审批请求"（允许/拒绝型，有明确按钮）。
    - DecisionPrompt 描述"开放式决策"（多选一，如打包方式、部署目标），
      选项语义不明、需要 AI 通俗解释，是本次新增功能的核心载体。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class DecisionLevel(str, Enum):
    """措辞水平：决定 AI 解释的通俗程度。"""

    BEGINNER = "beginner"
    NORMAL = "normal"
    ADVANCED = "advanced"


class DecisionMode(str, Enum):
    """决策助手启用模式（三态）。"""

    OFF = "off"
    ASK = "ask"
    ON = "on"


@dataclass
class DecisionOption:
    """一个待决策选项。

    属性:
        key: 选项标记（如 A / B / C 或 1 / 2 / 3），无标记时为空。
        text: 选项原始文本。
        meaning: AI 解释后"通俗含义"（流式填充）。
        risk: AI 评估的风险等级（low / medium / high）。
        risk_reason: 该风险等级的理由。
    """

    key: str = ""
    text: str = ""
    meaning: str = ""
    risk: str = ""
    risk_reason: str = ""


@dataclass
class DecisionPrompt:
    """一次完整的决策请求。

    属性:
        question: 提取到的问题文本。
        options: 候选选项列表（至少 2 个才构成有效决策）。
        source: 来源（OpenCode / Cursor / Cline / Clipboard / Unknown）。
        raw_text: 送入解析的原始文本（截断后）。
        window_handle: UIA 通道的窗口句柄（剪贴板通道为 None）。
        recommendation: AI 给出的整体推荐（流式填充）。
        conclusion: AI 的一句话结论。
        explained: 是否已完成 AI 解析。
        user_decision: 用户最终选择（如 "A" / "B" / "C"，用于记录）。
    """

    question: str = ""
    options: List[DecisionOption] = field(default_factory=list)
    source: str = "Unknown"
    raw_text: str = ""
    window_handle: Optional[int] = None
    recommendation: str = ""
    conclusion: str = ""
    explained: bool = False
    user_decision: Optional[str] = None
