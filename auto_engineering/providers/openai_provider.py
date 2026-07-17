"""OpenAIProvider — OpenAI API backend implementing LLMProvider Protocol.

V8-4: Anthropic↔OpenAI tool schema bidirectional conversion + factory.
Design ref: v5.6-Design-Loop.md appendix D §4.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from auto_engineering.providers.base import LLMProvider, LLMResponse, ToolUseBlock

_logger = logging.getLogger("ae.providers.openai")

# ── Anthropic → OpenAI tool schema conversion ──


def _anthropic_tool_to_openai(tool: dict) -> dict:
    """Convert single Anthropic tool schema → OpenAI function tool schema."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
        },
    }


def _anthropic_tools_to_openai(tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool schemas → OpenAI function tool schemas."""
    return [_anthropic_tool_to_openai(t) for t in tools]


# ── OpenAI → Anthropic message format conversion ──


def _anthropic_messages_to_openai(messages: list[dict]) -> list[dict]:
    """Convert Anthropic-format messages → OpenAI-format messages.

    - tool_result role → OpenAI tool role with tool_call_id
    - assistant + tool_uses content blocks → assistant + tool_calls
    - string content → content (passthrough)
    """
    converted = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "user" and isinstance(content, list):
            has_tool_result = any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in content
            )
            if has_tool_result:
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        converted.append({
                            "role": "tool",
                            "tool_call_id": block.get("tool_use_id", ""),
                            "content": block.get("content", ""),
                        })
            else:
                text = "".join(
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in content
                )
                converted.append({"role": role, "content": text})
        elif role == "assistant" and isinstance(content, list):
            text_parts = []
            tool_calls = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        tool_calls.append({
                            "id": block.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": block.get("name", ""),
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        })
            entry: dict = {"role": "assistant", "content": "".join(text_parts) or None}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            converted.append(entry)
        else:
            converted.append({"role": role, "content": content})

    return converted


# ── OpenAI response → LLMResponse ──


_FINISH_REASON_MAP: dict[str, str] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "content_filter",
}


def _openai_response_to_llm(response: Any) -> LLMResponse:
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
