"""OllamaProvider — Ollama local LLM backend implementing LLMProvider Protocol.

Design ref: v5.6-Design-Loop.md appendix E §E.5.1 (T55).

Ollama exposes an OpenAI-compatible API at http://localhost:11434/v1.
This provider reuses the Anthropic↔OpenAI tool schema conversion from
openai_provider.py and targets the Ollama base URL by default.

Bank intranet P0: offline deployment without external API dependencies.
"""

from __future__ import annotations

import logging
from auto_engineering.providers.base import ChatCompletionLike, LLMProvider, LLMResponse, ToolUseBlock
from auto_engineering.providers._openai_adapters import (
    anthropic_messages_to_openai as _anthropic_messages_to_openai,
    anthropic_tools_to_openai as _anthropic_tools_to_openai,
)
from auto_engineering.providers._response_adapter import openai_response_to_llm

_logger = logging.getLogger("ae.providers.ollama")

_OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434/v1"
_OLLAMA_DEFAULT_MODEL = "llama3"

_FINISH_REASON_MAP: dict[str, str] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "content_filter",
}


def _openai_response_to_llm(response: ChatCompletionLike) -> LLMResponse:
    """Convert Ollama API response → LLMResponse (delegates to shared adapter)."""
    return openai_response_to_llm(response, _FINISH_REASON_MAP)


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
