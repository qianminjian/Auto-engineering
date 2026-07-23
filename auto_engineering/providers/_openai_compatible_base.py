"""OpenAI-compatible provider base class.

Shared by GLMProvider, QwenProvider, OllamaProvider, OpenAIProvider.
Refactored from 4 duplicate provider files (2026-07-23 audit P0-9 dedup).

Each concrete provider now only needs:
  1. __init__ — resolve api_key, set base_url, call super().__init__()
  2. Class-level _FINISH_REASON_MAP dict
  3. Class-level _DEFAULT_MODEL str
"""

from __future__ import annotations

import logging
from typing import ClassVar

from auto_engineering.providers.base import LLMResponse
from auto_engineering.providers._openai_adapters import (
    anthropic_messages_to_openai,
    anthropic_tools_to_openai,
)
from auto_engineering.providers._response_adapter import openai_response_to_llm

_logger = logging.getLogger("ae.providers.base")


class OpenAICompatibleProvider:
    """Base class for providers targeting OpenAI-compatible APIs.

    Subclasses define _FINISH_REASON_MAP and _DEFAULT_MODEL as class attributes
    and override __init__ to resolve api_key from config/env before calling
    super().__init__().
    """

    _FINISH_REASON_MAP: ClassVar[dict[str, str]] = {
        "stop": "end_turn",
        "tool_calls": "tool_use",
        "length": "max_tokens",
    }
    _DEFAULT_MODEL: ClassVar[str] = ""

    def __init__(self, api_key: str, base_url: str | None) -> None:
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
        model: str = "",
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send message via OpenAI-compatible API.

        Handles Anthropic↔OpenAI schema conversion transparently.
        """
        openai_messages = anthropic_messages_to_openai(messages)
        if system:
            openai_messages.insert(0, {"role": "system", "content": system})

        kwargs: dict = {
            "model": model or self._DEFAULT_MODEL,
            "max_tokens": max_tokens,
            "messages": openai_messages,
        }
        if tools:
            kwargs["tools"] = anthropic_tools_to_openai(tools)

        response = await self._client.chat.completions.create(**kwargs)
        return openai_response_to_llm(response, self._FINISH_REASON_MAP)

    def close(self) -> None:
        """Release underlying connection."""
        if hasattr(self._client, "close"):
            self._client.close()
