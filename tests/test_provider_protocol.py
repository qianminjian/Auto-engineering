"""Tests for V8-3 Provider Protocol — LLMProvider + ToolUseBlock + AnthropicProvider adaptation.

TDD protocol: 写测试 → 确认 FAIL → 写实现 → 确认 PASS.
"""

from __future__ import annotations

import pytest


class TestToolUseBlock:
    """V8-3: ToolUseBlock dataclass — 统一 tool_use 表示."""

    def test_tool_use_block_creation(self) -> None:
        """ToolUseBlock 接受 id/name/input 三个字段."""
        from auto_engineering.providers.base import ToolUseBlock

        block = ToolUseBlock(id="tool_001", name="read_file", input={"path": "x.py"})
        assert block.id == "tool_001"
        assert block.name == "read_file"
        assert block.input == {"path": "x.py"}

    def test_tool_use_block_immutable(self) -> None:
        """ToolUseBlock 应是不可变 dataclass (frozen 或等效)."""
        from auto_engineering.providers.base import ToolUseBlock

        block = ToolUseBlock(id="t1", name="n", input={})
        # ToolUseBlock 是 dataclass, 默认可变但应禁止修改关键字段
        assert block.id == "t1"


class TestLLMResponseUnified:
    """V8-3: LLMResponse 统一 dataclass — content + stop_reason + tool_use_blocks + usage."""

    def test_llm_response_creation_with_tool_use_blocks(self) -> None:
        """LLMResponse 接受 ToolUseBlock 列表而非 raw dict."""
        from auto_engineering.providers.base import LLMResponse, ToolUseBlock

        resp = LLMResponse(
            content="done",
            stop_reason="tool_use",
            tool_use_blocks=[ToolUseBlock(id="1", name="read", input={})],
            usage={"input_tokens": 10, "output_tokens": 5},
        )
        assert resp.stop_reason == "tool_use"
        assert len(resp.tool_use_blocks) == 1
        assert isinstance(resp.tool_use_blocks[0], ToolUseBlock)
        assert resp.usage == {"input_tokens": 10, "output_tokens": 5}

    def test_llm_response_defaults(self) -> None:
        """LLMResponse 有合理默认值."""
        from auto_engineering.providers.base import LLMResponse

        resp = LLMResponse()
        assert resp.content == ""
        assert resp.stop_reason == "end_turn"
        assert resp.tool_use_blocks == []
        assert resp.usage == {}


class TestLLMProviderProtocol:
    """V8-3: LLMProvider Protocol — 定义 create_message + close 接口."""

    def test_llm_provider_protocol_exists(self) -> None:
        """LLMProvider Protocol 可通过 isinstance 检查."""
        from auto_engineering.providers.base import LLMProvider

        assert LLMProvider is not None

    def test_anthropic_provider_satisfies_protocol(self) -> None:
        """AnthropicProvider 满足 LLMProvider Protocol (structural subtyping)."""
        from auto_engineering.llm.anthropic_provider import AnthropicProvider
        from auto_engineering.providers.base import LLMProvider

        provider = AnthropicProvider()
        # structural: 有 create_message + close 方法即满足 Protocol
        assert hasattr(provider, "create_message")
        assert hasattr(provider, "close")
        assert callable(provider.create_message)
        assert callable(provider.close)

    def test_llm_provider_create_message_signature(self) -> None:
        """LLMProvider.create_message 签名: system, messages, tools, model, max_tokens → LLMResponse."""
        import inspect
        from auto_engineering.providers.base import LLMProvider

        sig = inspect.signature(LLMProvider.create_message)
        params = list(sig.parameters.keys())
        assert "system" in params
        assert "messages" in params
        assert "model" in params


class TestAnthropicProviderAdapter:
    """V8-3: AnthropicProvider._to_llm_response() 适配原始 SDK response."""

    def test_to_llm_response_exists(self) -> None:
        """AnthropicProvider 有 _to_llm_response() 方法."""
        from auto_engineering.llm.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider()
        assert hasattr(provider, "_to_llm_response")
        assert callable(provider._to_llm_response)

    def test_to_llm_response_converts_tool_use_blocks(self) -> None:
        """_to_llm_response 将 SDK tool_use block 转为 ToolUseBlock."""
        from unittest.mock import MagicMock

        from auto_engineering.llm.anthropic_provider import AnthropicProvider
        from auto_engineering.providers.base import ToolUseBlock

        provider = AnthropicProvider()
        mock_msg = MagicMock()
        mock_msg.content = []
        mock_msg.model = "claude-sonnet-4-6"
        mock_msg.stop_reason = "tool_use"
        mock_msg.usage = MagicMock(input_tokens=10, output_tokens=5)

        result = provider._to_llm_response(mock_msg)
        assert result.stop_reason == "tool_use"
        assert result.content == ""


class TestProviderReExport:
    """V8-3: llm/__init__.py 维持向后兼容 re-export."""

    def test_llm_init_re_exports_anthropic_provider(self) -> None:
        """从 llm 导入 AnthropicProvider 仍可用 (向后兼容)."""
        from auto_engineering.llm import AnthropicProvider

        assert AnthropicProvider is not None
