"""QwenProvider — Alibaba Qwen (通义千问) adapter implementing LLMProvider Protocol.

Design ref: v5.6-Design-Loop.md appendix E §E.5.2 (T58).

DashScope exposes an OpenAI-compatible API at
https://dashscope.aliyuncs.com/compatible-mode/v1.
信创合规 P0 — domestic model support for regulated environments.
"""

from __future__ import annotations

import json
import logging

from auto_engineering.providers.base import ChatCompletionLike, LLMProvider, LLMResponse, ToolUseBlock
from auto_engineering.providers._openai_adapters import (
    anthropic_messages_to_openai as _anthropic_messages_to_openai,
    anthropic_tools_to_openai as _anthropic_tools_to_openai,
)

_logger = logging.getLogger("ae.providers.qwen")

_QWEN_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_QWEN_DEFAULT_MODEL = "qwen-turbo"

_FINISH_REASON_MAP: dict[str, str] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
}


def _openai_response_to_llm(response: ChatCompletionLike) -> LLMResponse:
    choice = response.choices[0]
    content = choice.message.content or ""
    finish_reason = choice.finish_reason or "stop"

    tool_blocks: list[ToolUseBlock] = []
    if choice.message.tool_calls:
        for tc in choice.message.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}
            tool_blocks.append(ToolUseBlock(id=tc.id, name=tc.function.name, input=args))

    return LLMResponse(
        content=content,
        model=response.model or "",
        stop_reason=_FINISH_REASON_MAP.get(finish_reason, finish_reason),
        tool_use_blocks=tool_blocks,
        usage={
            "input_tokens": response.usage.prompt_tokens if response.usage else 0,
            "output_tokens": response.usage.completion_tokens if response.usage else 0,
        },
    )


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
