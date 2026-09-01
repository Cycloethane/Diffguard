# -*- coding: utf-8 -*-
"""AI 审查模块：调用 SiliconFlow 大模型，以流式方式生成中文结构化审查报告。

analyze_diff() 是一个生成器函数，通过 yield 逐段返回模型输出，
便于 GUI 在线程中进行流式展示；所有异常被捕获并转为友好的错误文本。
"""

from collections.abc import Iterator
from typing import Any

from loguru import logger
from openai import (
    APIConnectionError,
    APITimeoutError,
    APIStatusError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from models.config import Config, provider_base_url

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
    if not config.api_key or not config.api_key.strip():
        logger.warning("未配置 API Key，跳过 AI 审查")
        yield "\n\n[错误] 尚未配置 API Key，请在“设置”中填写后重试。\n"
        return

    base_url: str = provider_base_url(getattr(config, "provider", ""))
    client: OpenAI = OpenAI(api_key=config.api_key, base_url=base_url)

    try:
        logger.info("开始调用模型 {} 审查 diff（提供方 {}）", config.model, getattr(config, "provider", "siliconflow"))
        response: Any = client.chat.completions.create(
            model=config.model,
            temperature=0.2,
            max_tokens=4096,
            stream=True,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(diff_text)},
            ],
        )
        for chunk in response:
            if not chunk.choices:
                continue
            delta: Any = chunk.choices[0].delta
            content: str = delta.content if (delta and delta.content) else ""
            if content:
                yield content
        logger.info("AI 审查完成")
    except AuthenticationError as exc:
        logger.error("API Key 无效: {}", exc)
        yield "\n\n[错误] API Key 无效或已过期，请在设置中检查。\n"
    except RateLimitError as exc:
        logger.error("请求频率超限: {}", exc)
        yield "\n\n[错误] 请求频率超限，请稍后重试。\n"
    except (APITimeoutError, APIConnectionError) as exc:
        logger.error("网络连接失败/超时: {}", exc)
        yield "\n\n[错误] 网络连接失败或超时，请检查网络后重试。\n"
    except APIStatusError as exc:
        logger.error("API 返回异常状态码 {}: {}", exc.status_code, exc)
        yield "\n\n[错误] 服务暂时不可用（HTTP {}），可能原因：余额不足或模型不可用。\n".format(
            exc.status_code
        )
    except Exception as exc:  # 兜底捕获，避免线程崩溃
        logger.exception("AI 审查发生未知异常: {}", exc)
        yield "\n\n[错误] 审查过程发生未知异常，请查看日志。\n"