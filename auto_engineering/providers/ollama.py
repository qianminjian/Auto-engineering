"""OllamaProvider — Ollama local LLM backend implementing LLMProvider Protocol.

Design ref: v5.6-Design-Loop.md appendix E §E.5.1 (T55).

Ollama exposes an OpenAI-compatible API at http://localhost:11434/v1.
This provider reuses the Anthropic↔OpenAI tool schema conversion from
openai_provider.py and targets the Ollama base URL by default.

Bank intranet P0: offline deployment without external API dependencies.
"""

from __future__ import annotations

import json
import logging
from auto_engineering.providers.base import LLMProvider, LLMResponse, ToolUseBlock, _ChatCompletionLike
from auto_engineering.providers.openai_provider import (
    _anthropic_messages_to_openai,
    _anthropic_tools_to_openai,
)

_logger = logging.getLogger("ae.providers.ollama")

_OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434/v1"
_OLLAMA_DEFAULT_MODEL = "llama3"

_FINISH_REASON_MAP: dict[str, str] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "content_filter",
}


def _is_ollama_available() -> bool:
    """Return True if the openai SDK is importable (Ollama uses OpenAI compat API)."""
    try:
        import openai  # noqa: F401
        return True
    except ImportError:
        return False


def _openai_response_to_llm(response: _ChatCompletionLike) -> LLMResponse:
    """Convert OpenAI-compatible response → LLMResponse."""
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


class OllamaProvider:
    """Ollama local LLM client implementing LLMProvider Protocol.

    Uses the OpenAI-compatible API exposed by Ollama at /v1.
    Anthropic↔OpenAI schema conversion is transparent.
    """

    def __init__(
        self,
        api_key: str = "ollama",
        base_url: str = _OLLAMA_DEFAULT_BASE_URL,
    ) -> None:
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
        model: str = _OLLAMA_DEFAULT_MODEL,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send message to Ollama via OpenAI-compatible endpoint."""
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
