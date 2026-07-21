"""OpenAIProvider — OpenAI API backend implementing LLMProvider Protocol.

V8-4: Anthropic↔OpenAI tool schema bidirectional conversion + factory.
Design ref: v5.6-Design-Loop.md appendix D §4.
"""

from __future__ import annotations

import json
import logging

from auto_engineering.providers.base import ChatCompletionLike, LLMProvider, LLMResponse, ToolUseBlock

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
    """Convert OpenAI API response → LLMResponse."""
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
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
        } if response.usage else {},
    )


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
