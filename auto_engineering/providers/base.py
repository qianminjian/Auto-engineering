"""Provider abstraction layer — LLM provider protocol + unified response types.

V8-3: LLMProvider Protocol + LLMResponse + ToolUseBlock.
Design ref: v5.6-Design-Loop.md appendix D §3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolUseBlock:
    """Unified tool-use representation across LLM providers.

    Anthropic SDK: block.id / block.name / block.input
    OpenAI SDK: tool_call.id / tool_call.function.name / json.loads(tool_call.function.arguments)
    """

    id: str
    name: str
    input: dict = field(default_factory=dict)


@dataclass
class LLMResponse:
    """Unified LLM response across providers.

    Replaces anthropic_provider.LLMResponse (which had tool_use_blocks: list[dict]).
    This version uses list[ToolUseBlock] for type safety.
    """

    content: str = ""
    model: str = ""
    stop_reason: str = "end_turn"
    tool_use_blocks: list[ToolUseBlock] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


class LLMProvider(Protocol):
    """Protocol for LLM provider backends.

    Structural subtyping — any class with create_message() + close() satisfies this.
    AnthropicProvider and OpenAIProvider both conform.
    """

    async def create_message(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str = "",
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send a message to the LLM and return a unified response."""
        ...

    def close(self) -> None:
        """Release underlying connections."""
        ...
