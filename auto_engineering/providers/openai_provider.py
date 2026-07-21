"""OpenAIProvider — OpenAI API backend implementing LLMProvider Protocol.

V8-4: Anthropic↔OpenAI tool schema bidirectional conversion + factory.
Design ref: v5.6-Design-Loop.md appendix D §4.
"""

from __future__ import annotations

import logging

from auto_engineering.providers.base import ChatCompletionLike, LLMProvider, LLMResponse, ToolUseBlock
from auto_engineering.providers._response_adapter import openai_response_to_llm

_logger = logging.getLogger("ae.providers.openai")

# ── Anthropic → OpenAI tool schema conversion ──


from auto_engineering.providers._openai_adapters import (
    anthropic_messages_to_openai,
    anthropic_tool_to_openai,
    anthropic_tools_to_openai,
)

# Backward-compatible aliases for existing callers.
_anthropic_tool_to_openai = anthropic_tool_to_openai
_anthropic_tools_to_openai = anthropic_tools_to_openai
_anthropic_messages_to_openai = anthropic_messages_to_openai


# ── OpenAI response → LLMResponse ──


_FINISH_REASON_MAP: dict[str, str] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "content_filter",
}


def _openai_response_to_llm(response: ChatCompletionLike) -> LLMResponse:
    """Convert OpenAI API response → LLMResponse (delegates to shared adapter)."""
    return openai_response_to_llm(response, _FINISH_REASON_MAP)


# ── OpenAIProvider ──


class OpenAIProvider:
    """OpenAI API client wrapper implementing LLMProvider Protocol.

    Handles Anthropic↔OpenAI schema conversion transparently.
    """

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError(
                "openai package not installed. Install with: uv sync --extra openai"
            )
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def create_message(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str = "gpt-5",
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send message to OpenAI API with transparent schema conversion."""
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
        """Release underlying httpx connection."""
        if hasattr(self._client, "close"):
            self._client.close()
