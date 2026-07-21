"""Anthropic ↔ OpenAI format adapters — shared by all OpenAI-compatible providers.

Used by: OpenAIProvider, OllamaProvider, GLMProvider, QwenProvider.
Extracted from openai_provider.py (P1-14 dedup).
"""

from __future__ import annotations

import json


def anthropic_tool_to_openai(tool: dict) -> dict:
    """Convert single Anthropic tool schema → OpenAI function tool schema."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
        },
    }


def anthropic_tools_to_openai(tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool schemas → OpenAI function tool schemas."""
    return [anthropic_tool_to_openai(t) for t in tools]


def anthropic_messages_to_openai(messages: list[dict]) -> list[dict]:
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
