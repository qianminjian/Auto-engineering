"""OpenAI-compatible response → LLMResponse adapter (shared, P0-9 dedup).

Extracted from glm.py / qwen.py / ollama.py / openai_provider.py (2026-07-21 audit)
to eliminate 4× duplicate ~25-line function. Each provider customizes only its
own _FINISH_REASON_MAP; the conversion logic is identical.
"""

from __future__ import annotations

import json

from auto_engineering.providers.base import ChatCompletionLike, LLMResponse, ToolUseBlock

# ── Default finish reason map (union of all provider entries) ──

DEFAULT_FINISH_REASON_MAP: dict[str, str] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "content_filter",
}


def openai_response_to_llm(
    response: ChatCompletionLike,
    finish_reason_map: dict[str, str] | None = None,
) -> LLMResponse:
    """Convert OpenAI-compatible API response → LLMResponse.

    Args:
        response: OpenAI ChatCompletion-like response object.
        finish_reason_map: Optional provider-specific finish_reason → stop_reason
            mapping. Falls back to DEFAULT_FINISH_REASON_MAP.

    Returns:
        Normalized LLMResponse with tool_use_blocks and usage parsed.
    """
    _map = finish_reason_map if finish_reason_map is not None else DEFAULT_FINISH_REASON_MAP
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
        stop_reason=_map.get(finish_reason, finish_reason),
        tool_use_blocks=tool_blocks,
        usage={
            "input_tokens": response.usage.prompt_tokens if response.usage else 0,
            "output_tokens": response.usage.completion_tokens if response.usage else 0,
        },
    )
