"""OpenAIProvider — OpenAI API backend implementing LLMProvider Protocol.

V8-4: Anthropic↔OpenAI tool schema bidirectional conversion + factory.
Design ref: v5.6-Design-Loop.md appendix D §4.
"""

from __future__ import annotations

import logging

from auto_engineering.providers.base import ChatCompletionLike, LLMResponse, ToolUseBlock
from auto_engineering.providers._response_adapter import openai_response_to_llm
from auto_engineering.providers._openai_compatible_base import OpenAICompatibleProvider

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


class OpenAIProvider(OpenAICompatibleProvider):
    """OpenAI API client wrapper implementing LLMProvider Protocol.

    Handles Anthropic↔OpenAI schema conversion transparently.
    """

    _FINISH_REASON_MAP = _FINISH_REASON_MAP
    _DEFAULT_MODEL: str = "gpt-5"

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        super().__init__(api_key=api_key, base_url=base_url)
