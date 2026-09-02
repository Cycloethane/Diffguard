# -*- coding: utf-8 -*-
"""决策解释模块：调用 SiliconFlow 大模型，为决策选项生成通俗解析与推荐。

与 core/reviewer.py 的 diff 审查不同，本模块聚焦"面向不同水平用户的选项
解读"，按配置的措辞水平（beginner/normal/advanced）切换提示词风格。

输出协议（供流式 UI 增量解析）：
    - 每行一条，三行式：
        #QUESTION# <问题确认>
        #OPTION# <json: {"key":..,"text":..,"meaning":..,"risk":..,"reason":..}>
        #RECOMMEND# <json: {"option":..,"conclusion":..}>
    UI 端按行解析，边到边展示。
"""

import json
from collections.abc import Iterator
from typing import Any

from loguru import logger

from core.ai_client import stream_chat, stream_lines
from models.config import Config
from models.decision_prompt import DecisionLevel, DecisionPrompt

# 三档措辞风格说明（注入系统提示词）
_LEVEL_DESCRIPTIONS: dict[str, str] = {
    DecisionLevel.BEGINNER.value: (
        "目标读者：完全没有编程经验的零基础用户。"
        "要求：全部使用大白话和生活化比喻，禁止出现任何英文术语、编程名词、"
        "技术缩写；每个解释都以「你可以把它想成……」开场；"
        "用「简单来说」总结。总字数控制在最短。"
    ),
    DecisionLevel.NORMAL.value: (
        "目标读者：有一点经验、但不算精通编程的普通用户。"
        "要求：用通俗中文解释，允许出现少量常见术语但必须用一句话解释；"
        "每个选项的优缺点各至少一条且具体（影响什么、多麻烦/多省事）；语气平实。"
    ),
    DecisionLevel.ADVANCED.value: (
        "目标读者：熟悉开发流程的进阶用户。"
        "要求：直接使用准确的技术术语，从底层原理、性能、生态、维护成本、"
        "可逆性等专业角度逐项分析利弊；信息密度高，不需要照顾零基础读者。"
    ),
}

_SYSTEM_PROMPT_TEMPLATE: str = """你是一位耐心的「决策解说员」，帮助用户理解编程 Agent 抛出的选择题。
用户会给你一个待决策问题及其选项列表。你的任务是逐个**详细分析**这些选项，
让用户（按指定水平）能看懂并作出明智决定。

## 措辞水平要求
{level_desc}

## 输出格式（严格逐行，不要输出其它内容）
第一行输出：#QUESTION# 用一句话复述你理解的问题
然后每个选项一行：#OPTION# 后跟一个 JSON 对象，字段：
  key: 选项标记
  text: 选项原文
  meaning: 面向目标读者的详细分析——这个选项是什么、做什么、
    优点（至少一条）、缺点或代价（至少一条）、适合什么情况，
    用「优点：…；缺点：…；适合：…」的行内结构组织
  risk: low / medium / high 三选一
  reason: 为什么是这个风险等级（面向目标读者，点出具体后果）
最后一行：#RECOMMEND# 后跟一个 JSON 对象，字段：
  option: 你推荐的关键（若都不推荐填空字符串）
  conclusion: 一句话结论，明确告诉用户选哪个；若选哪个都各有道理，
    说明判断依据（什么情况选什么）

注意：
- 每个 JSON 必须合法，字段值用双引号，不要换行。
- 分析要具体，结合选项本身内容（技术含义、影响范围、后续成本），
  不要泛泛而谈；利弊必须针对本选项，而非套话。
"""

# 单次解析的原始文本长度上限
_MAX_PROMPT_LEN: int = 4000


def build_system_prompt(level: str) -> str:
    """按措辞水平生成系统提示词；未知水平回退 normal。"""
    desc: str = _LEVEL_DESCRIPTIONS.get(level, _LEVEL_DESCRIPTIONS["normal"])
    return _SYSTEM_PROMPT_TEMPLATE.format(level_desc=desc)


def _build_user_prompt(prompt: DecisionPrompt) -> str:
    """构造用户提示词：问题 + 选项列表。"""
    lines: list[str] = [f"问题：{prompt.question}"]
    for opt in prompt.options:
        marker: str = f"{opt.key}) " if opt.key else "- "
        lines.append(f"{marker}{opt.text}")
    text: str = "\n".join(lines)
    return text[:_MAX_PROMPT_LEN]


def explain_decision(prompt: DecisionPrompt, config: Config) -> Iterator[str]:
    """流式解析决策，逐行 yield 结构化文本行（见模块 docstring 协议）。

    配置了 API Key 直接调用；异常均被捕获并 yield 友好错误行，不向上抛。
    """
    level: str = getattr(config, "decision_level", DecisionLevel.NORMAL.value)
    yield from stream_lines(
        stream_chat(
            config,
            system_prompt=build_system_prompt(level),
            user_prompt=_build_user_prompt(prompt),
            max_tokens=2048,
            error_prefix="#ERROR# ",
            error_suffix="",
            label="解析决策",
        )
    )


def parse_opt_line(line: str) -> dict[str, Any]:
    """解析 #OPTION# 行，返回 dict；格式错误返回空 dict。"""
    if not line.startswith("#OPTION#"):
        return {}
    try:
        data: dict[str, Any] = json.loads(line[len("#OPTION#") :].strip())
        return {
            "key": str(data.get("key", "")),
            "text": str(data.get("text", "")),
            "meaning": str(data.get("meaning", "")),
            "risk": str(data.get("risk", "")),
            "reason": str(data.get("reason", "")),
        }
    except (json.JSONDecodeError, AttributeError):
        logger.debug("解析 #OPTION# 行失败: {}", line[:120])
        return {}


def parse_recommend_line(line: str) -> dict[str, Any]:
    """解析 #RECOMMEND# 行，返回 dict；格式错误返回空 dict。"""
    if not line.startswith("#RECOMMEND#"):
        return {}
    try:
        data: dict[str, Any] = json.loads(line[len("#RECOMMEND#") :].strip())
        return {
            "option": str(data.get("option", "")),
            "conclusion": str(data.get("conclusion", "")),
        }
    except (json.JSONDecodeError, AttributeError):
        logger.debug("解析 #RECOMMEND# 行失败: {}", line[:120])
        return {}


def parse_question_line(line: str) -> str:
    """解析 #QUESTION# 行，返回问题确认文本；不是该行返回空串。"""
    if line.startswith("#QUESTION#"):
        return line[len("#QUESTION#") :].strip()
    return ""


def parse_error_line(line: str) -> str:
    """解析 #ERROR# 行，返回错误文本；不是该行返回空串。"""
    if line.startswith("#ERROR#"):
        return line[len("#ERROR#") :].strip()
    return ""
