# -*- coding: utf-8 -*-
"""AI 审查模块：调用大模型，以流式方式生成中文结构化审查报告。

analyze_diff() 是一个生成器函数，通过 yield 逐段返回模型输出，
便于 GUI 在线程中进行流式展示；调用与异常处理由 core.ai_client.stream_chat
统一提供，本模块只维护审查提示词。
"""

from collections.abc import Iterator

from core.ai_client import stream_chat
from models.config import Config

SYSTEM_PROMPT: str = """
你是一位资深代码审查专家。请分析以下 git diff，提供中文结构化审查报告。


## 输出格式（必须严格遵守）


### 📌 变更摘要
1-2句话概括。


### 📁 文件级变更
对每个文件说明：路径、类型、影响行数、风险标记。


### 🔍 关键逻辑解释
解释新增/修改/删除的逻辑，特别关注删除的内容。


### ⚠️ 风险评估
🔴 高危：删除文件、改配置、硬编码密钥、权限代码
🟡 中危：核心逻辑变更、数据库操作、新依赖
🟢 低危：格式化、注释、重命名


### 💡 决策建议
- ✅ 建议批准：无风险，符合预期
- ⚠️ 建议谨慎：存在需要确认的问题
- ❌ 建议拒绝：高风险或变更与目的不符


### ❓ 需要确认的问题
列出必须确认的问题。
"""


def _build_user_prompt(diff_text: str) -> str:
    """构造用户提示词：包含待审查的 diff 全文。"""
    return f"请审查以下 git diff：\n\n{diff_text}"


def analyze_diff(diff_text: str, config: Config) -> Iterator[str]:
    """流式分析 diff 文本，逐段 yield 审查报告文本片段。

    配置了 API Key 直接调用；异常（认证失败、超时、限流、余额不足等）
    均被捕获，并 yield 友好的错误提示，不向上抛异常。
    """
    yield from stream_chat(
        config,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=_build_user_prompt(diff_text),
        max_tokens=4096,
        label="审查",
    )
