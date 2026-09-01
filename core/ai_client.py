# -*- coding: utf-8 -*-
"""共享 OpenAI 兼容流式客户端。

reviewer(diff 审查)与 decision_explainer(决策解析)共用同一调用骨架:
客户端构建、流式消费、五类异常到友好错误文案的映射。差异点(提示词、
max_tokens、错误行前缀/后缀、日志标签)全部参数化,错误文本不再两处维护。
"""

from collections.abc import Iterator
from typing import Any

from loguru import logger
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from models.config import Config, provider_base_url


def stream_chat(
    config: Config,
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int = 4096,
    error_prefix: str = "\n\n[错误] ",
    error_suffix: str = "\n",
    label: str = "调用",
) -> Iterator[str]:
    """流式对话:逐段 yield 模型输出;异常转友好错误文本,不向上抛。

    未配置 API Key 时直接 yield 一条错误并返回。
    """
    if not config.api_key or not config.api_key.strip():
        logger.warning("未配置 API Key，跳过 {}", label)
        yield error_prefix + "尚未配置 API Key，请在“设置”中填写后重试。" + error_suffix
        return

    base_url: str = provider_base_url(getattr(config, "provider", ""))
    client: OpenAI = OpenAI(api_key=config.api_key, base_url=base_url)
    try:
        logger.info(
            "开始调用模型 {} {}（提供方 {}）",
            config.model, label, getattr(config, "provider", "siliconflow"),
        )
        response: Any = client.chat.completions.create(
            model=config.model,
            temperature=0.2,
            max_tokens=max_tokens,
            stream=True,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        for chunk in response:
            if not chunk.choices:
                continue
            delta: Any = chunk.choices[0].delta
            content: str = delta.content if (delta and delta.content) else ""
            if content:
                yield content
        logger.info("{}完成", label)
    except AuthenticationError as exc:
        logger.error("API Key 无效: {}", exc)
        yield error_prefix + "API Key 无效或已过期，请在设置中检查。" + error_suffix
    except RateLimitError as exc:
        logger.error("请求频率超限: {}", exc)
        yield error_prefix + "请求频率超限，请稍后重试。" + error_suffix
    except (APITimeoutError, APIConnectionError) as exc:
        logger.error("网络连接失败/超时: {}", exc)
        yield error_prefix + "网络连接失败或超时，请检查网络后重试。" + error_suffix
    except APIStatusError as exc:
        logger.error("API 返回异常状态码 {}: {}", exc.status_code, exc)
        yield (
            error_prefix
            + "服务暂时不可用（HTTP {}），可能原因：余额不足或模型不可用。".format(exc.status_code)
            + error_suffix
        )
    except Exception as exc:  # 兜底捕获，避免线程崩溃
        logger.exception("{}发生未知异常: {}", label, exc)
        yield error_prefix + f"{label}过程发生未知异常，请查看日志。" + error_suffix


def stream_lines(chunks: Iterator[str]) -> Iterator[str]:
    """把流式片段重组为逐行输出(strip 后丢弃空行),供决策解析协议使用。"""
    buf: str = ""
    for content in chunks:
        buf += content
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            line = line.strip()
            if line:
                yield line
    if buf.strip():
        yield buf.strip()
