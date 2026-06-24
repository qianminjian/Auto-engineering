"""AnthropicProvider — LLM 调用封装.

设计参考: design/LOOP-DEVELOPMENT-PLAN.md Phase 3 文件 18.
封装 anthropic SDK,提供 LLMResponse/LLMUsage 数据类,统一接口给 Agent 调用.

v3.1 扩展 (Phase 0.1 dev-loop 真接):
    - LLMResponse 加 stop_reason + tool_use_blocks(支持 BaseAgent 工具循环)
    - create_message 加 tools 参数 + 解析 SDK content blocks(text + tool_use)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import anthropic


@dataclass
class LLMUsage:
    """Token 用量统计."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LLMResponse:
    """LLM 调用结构化响应.

    字段:
        content          — text block 拼接的纯文本(text 类型)
        model            — 调用的模型名
        usage            — token 用量
        stop_reason      — SDK 返回的停止原因("end_turn" | "tool_use" | "max_tokens")
        tool_use_blocks  — tool_use 类型 block 解析结果(每个 dict 含 id/name/input)
    """

    content: str = ""
    model: str = ""
    usage: LLMUsage = field(default_factory=LLMUsage)
    stop_reason: str = "end_turn"
    tool_use_blocks: list[dict] = field(default_factory=list)


class AnthropicProvider:
    """Anthropic Claude API 客户端封装."""

    def __init__(
        self,
        api_key: str | None = None,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        if client is not None:
            self._client = client
        else:
            self._client = anthropic.Anthropic(api_key=api_key)

    def create_message(
        self,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """调用 Claude API.

        Args:
            model    — 模型名(例 "claude-sonnet-4-6")
            max_tokens — 最大输出 token
            system   — system prompt
            messages — 对话历史 [{"role": ..., "content": ...}]
            tools    — 可选,工具 schema 列表(Anthropic tool format)

        Returns:
            LLMResponse(content/model/usage/stop_reason/tool_use_blocks)
        """
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        response = self._client.messages.create(**kwargs)

        content_text = ""
        tool_use_blocks: list[dict] = []
        for block in response.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_use_blocks.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        return LLMResponse(
            content=content_text,
            model=response.model,
            usage=LLMUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            stop_reason=response.stop_reason,
            tool_use_blocks=tool_use_blocks,
        )
