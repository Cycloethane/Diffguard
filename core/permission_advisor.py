# -*- coding: utf-8 -*-
"""权限顾问模块：调用大模型分析 ZCode 的权限请求。

与 decision_explainer(选项决策解析)并列,聚焦权限三问:
    这是什么权限/操作? 允许会有什么后果? 建议怎么处理?

输出协议(供流式 UI 增量解析,每行一条):
    #WHAT# <这是什么权限/操作,影响什么目标,一两句>
    #CONSEQUENCE# <允许的直接后果 + 潜在风险 + 是否可逆>
    #ADVICE# <json: {"decision":"allow_once"|"always_allow"|"deny","reason":"..."}>
    #ERROR# <错误文本>(由 stream_chat 错误前缀产生)

UI 端按行解析,边到边展示。建议档位与 ZCode 授权弹窗三选项对应:
    allow_once=允许一次 / always_allow=总是允许 / deny=拒绝
"""

import json
from collections.abc import Iterator
from typing import Any

from loguru import logger

from core.ai_client import stream_chat, stream_lines
from models.config import Config

# 单次分析的原始文本长度上限
_MAX_PROMPT_LEN: int = 2400

_SYSTEM_PROMPT: str = """你是一位「权限顾问」，帮助用户理解 AI 编程工具（ZCode）弹出的授权请求。
用户会给你一条权限请求：工具名、原始内容、以及本地规则引擎的评分与命中项。
你的任务是依次回答三个问题，让普通用户能看懂并作出明智决定。

## 输出格式（严格逐行，不要输出其它内容）
第一行：#WHAT# 用一两句通俗中文说明这是什么权限/操作、影响什么目标
第二行：#CONSEQUENCE# 说明"允许"会发生什么：直接后果、潜在风险、是否可逆
第三行：#ADVICE# 后跟一个 JSON 对象，字段：
  decision: "allow_once"（建议允许一次）/ "always_allow"（建议总是允许）/ "deny"（建议拒绝）三选一
  reason: 一句话理由，明确告诉用户为什么

注意：
- decision 档位与 ZCode 授权弹窗的「允许一次 / 总是允许 / 拒绝」一一对应。
- 分析要结合具体内容（命令做什么、路径在哪、影响范围），不要泛泛而谈。
- 结合本地评分与命中项，但不要照抄；必要时修正它们的过度保守或过度乐观。
- 若信息不足以判断，给保守建议（通常是 allow_once 或 deny）并在 reason 中说明不确定点。
- JSON 必须合法，字段值用双引号，不要换行。"""


def _build_user_prompt(event: dict) -> str:
    """构造用户提示词：工具 + 原始内容 + 本地评分命中项。"""
    tool: str = str(event.get("tool", "") or "未知工具")
    target: str = str(event.get("target", "") or "")
    raw: str = str(event.get("raw", "") or "") or target
    score = event.get("score", 0)
    level: str = str(event.get("level", "") or "low")
    findings = "、".join(str(f) for f in event.get("findings", []) or []) or "无"
    lines: list[str] = [
        f"工具：{tool}",
        f"本地评分：{score}/100（{level}），命中规则：{findings}",
    ]
    if target and target != raw:
        lines.append(f"目标：{target}")
    lines.append(f"原始内容：\n{raw or '（未提供）'}")
    text: str = "\n".join(lines)
    return text[:_MAX_PROMPT_LEN]


def advise_permission(event: dict, config: Config) -> Iterator[str]:
    """流式分析一条权限事件,逐行 yield 协议行;异常转 #ERROR# 行,不向上抛。"""
    yield from stream_lines(
        stream_chat(
            config,
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_build_user_prompt(event),
            max_tokens=1024,
            error_prefix="#ERROR# ",
            error_suffix="",
            label="权限分析",
        )
    )


# ----------------------------------------------------------------------
# 协议行解析
# ----------------------------------------------------------------------
def parse_what_line(line: str) -> str:
    """解析 #WHAT# 行,返回文本;不是该行返回空串。"""
    if line.startswith("#WHAT#"):
        return line[len("#WHAT#"):].strip()
    return ""


def parse_consequence_line(line: str) -> str:
    """解析 #CONSEQUENCE# 行,返回文本;不是该行返回空串。"""
    if line.startswith("#CONSEQUENCE#"):
        return line[len("#CONSEQUENCE#"):].strip()
    return ""


def parse_advice_line(line: str) -> dict[str, Any]:
    """解析 #ADVICE# 行,返回 {decision, reason};格式错误返回空 dict。"""
    if not line.startswith("#ADVICE#"):
        return {}
    try:
        data: dict[str, Any] = json.loads(line[len("#ADVICE#"):].strip())
        decision = str(data.get("decision", ""))
        if decision not in ("allow_once", "always_allow", "deny"):
            decision = "allow_once" if decision else ""
        return {"decision": decision, "reason": str(data.get("reason", ""))}
    except (json.JSONDecodeError, AttributeError):
        logger.debug("解析 #ADVICE# 行失败: {}", line[:120])
        return {}


def parse_error_line(line: str) -> str:
    """解析 #ERROR# 行,返回错误文本;不是该行返回空串。"""
    if line.startswith("#ERROR#"):
        return line[len("#ERROR#"):].strip()
    return ""
