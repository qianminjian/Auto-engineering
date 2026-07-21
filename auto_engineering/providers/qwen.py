"""QwenProvider — Alibaba Qwen (通义千问) adapter implementing LLMProvider Protocol.

Design ref: v5.6-Design-Loop.md appendix E §E.5.2 (T58).

DashScope exposes an OpenAI-compatible API at
https://dashscope.aliyuncs.com/compatible-mode/v1.
信创合规 P0 — domestic model support for regulated environments.
"""

from __future__ import annotations

import logging

from auto_engineering.providers.base import ChatCompletionLike, LLMProvider, LLMResponse, ToolUseBlock
from auto_engineering.providers._openai_adapters import (
    anthropic_messages_to_openai as _anthropic_messages_to_openai,
    anthropic_tools_to_openai as _anthropic_tools_to_openai,
)
from auto_engineering.providers._response_adapter import openai_response_to_llm

_logger = logging.getLogger("ae.providers.qwen")

_QWEN_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_QWEN_DEFAULT_MODEL = "qwen-turbo"

_FINISH_REASON_MAP: dict[str, str] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
}


def _openai_response_to_llm(response: ChatCompletionLike) -> LLMResponse:
    """Convert Qwen API response → LLMResponse (delegates to shared adapter)."""
    return openai_response_to_llm(response, _FINISH_REASON_MAP)


class QwenProvider:
    """Alibaba Qwen (通义千问) client implementing LLMProvider Protocol."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = _QWEN_DEFAULT_BASE_URL,
    ) -> None:
        import os

        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError("openai package not installed. Install with: uv sync --extra openai")

        from auto_engineering.config.runtime_config import get_default_config
        key = api_key or get_default_config().dashscope_api_key
        self._client = AsyncOpenAI(api_key=key, base_url=base_url)

    async def create_message(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str = _QWEN_DEFAULT_MODEL,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        openai_messages = _anthropic_messages_to_openai(messages)
        if system:
            openai_messages.insert(0, {"role": "system", "content": system})

        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": openai_messages,
        }
        if tools:
            kwargs["tools"] = _anthropic_tools_to_openai(tools)

        response = await self._client.chat.completions.create(**kwargs)
        return _openai_response_to_llm(response)

    def close(self) -> None:
        if hasattr(self._client, "close"):
            self._client.close()
