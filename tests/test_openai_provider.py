"""Tests for V8-4 OpenAIProvider — Anthropic↔OpenAI tool schema conversion + factory.

TDD protocol: 写测试 → 确认 FAIL → 写实现 → 确认 PASS.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Anthropic → OpenAI tool schema conversion ──


class TestAnthropicToOpenAIToolConversion:
    """V8-4: Anthropic tool schema → OpenAI function schema 单向转换."""

    def test_basic_tool_conversion(self) -> None:
        """Anthropic tool {name, description, input_schema} → OpenAI {type, function}."""
        from auto_engineering.providers.openai_provider import _anthropic_tool_to_openai

        anthropic_tool = {
            "name": "read_file",
            "description": "Read a file",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        }
        result = _anthropic_tool_to_openai(anthropic_tool)
        assert result["type"] == "function"
        assert result["function"]["name"] == "read_file"
        assert result["function"]["description"] == "Read a file"
        assert result["function"]["parameters"]["type"] == "object"

    def test_tool_without_description(self) -> None:
        """没有 description 的 tool 也能正常转换."""
        from auto_engineering.providers.openai_provider import _anthropic_tool_to_openai

        anthropic_tool = {
            "name": "list_dir",
            "input_schema": {"type": "object", "properties": {}},
        }
        result = _anthropic_tool_to_openai(anthropic_tool)
        assert result["function"]["name"] == "list_dir"

    def test_tool_conversion_round_trip_preserves_name(self) -> None:
        """多个 tools 转换后名称均保留."""
        from auto_engineering.providers.openai_provider import _anthropic_tools_to_openai

        tools = [
            {"name": "t1", "input_schema": {"type": "object", "properties": {}}},
            {"name": "t2", "input_schema": {"type": "object", "properties": {}}},
        ]
        result = _anthropic_tools_to_openai(tools)
        assert len(result) == 2
        assert result[0]["function"]["name"] == "t1"
        assert result[1]["function"]["name"] == "t2"


# ── OpenAI → LLMResponse conversion ──


class TestOpenAIResponseConversion:
    """V8-4: OpenAI API response → LLMResponse 转换."""

    def test_simple_text_response(self) -> None:
        """纯文本 response → LLMResponse(content=text, stop_reason=end_turn)."""
        from auto_engineering.providers.openai_provider import _openai_response_to_llm

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(content="Hello", tool_calls=None),
                finish_reason="stop",
            ),
        ]
        mock_response.model = "gpt-5"
        mock_response.usage = MagicMock(
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
        )

        result = _openai_response_to_llm(mock_response)
        assert result.content == "Hello"
        assert result.stop_reason == "end_turn"
        assert result.model == "gpt-5"
        assert result.usage == {"input_tokens": 10, "output_tokens": 5}

    def test_tool_calls_response(self) -> None:
        """tool_calls response → LLMResponse(tool_use_blocks=[...], stop_reason=tool_use)."""
        import json

        from auto_engineering.providers.openai_provider import _openai_response_to_llm
        from auto_engineering.providers.base import ToolUseBlock

        # Use SimpleNamespace to avoid MagicMock.name reserved attribute
        from types import SimpleNamespace

        func = SimpleNamespace(name="read_file", arguments=json.dumps({"path": "x.py"}))
        tc = SimpleNamespace(id="call_1", function=func)
        msg = SimpleNamespace(content=None, tool_calls=[tc])
        choice = SimpleNamespace(message=msg, finish_reason="tool_calls")
        usage = SimpleNamespace(prompt_tokens=20, completion_tokens=10, total_tokens=30)
        mock_response = SimpleNamespace(choices=[choice], model="gpt-5", usage=usage)

        result = _openai_response_to_llm(mock_response)
        assert result.stop_reason == "tool_use"
        assert len(result.tool_use_blocks) == 1
        assert isinstance(result.tool_use_blocks[0], ToolUseBlock)
        assert result.tool_use_blocks[0].name == "read_file"
        assert result.tool_use_blocks[0].input == {"path": "x.py"}

    def test_max_tokens_finish_reason(self) -> None:
        """finish_reason 'length' → stop_reason 'max_tokens'."""
        from auto_engineering.providers.openai_provider import _openai_response_to_llm

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="truncated", tool_calls=None), finish_reason="length"),
        ]
        mock_response.model = "gpt-5"
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)

        result = _openai_response_to_llm(mock_response)
        assert result.stop_reason == "max_tokens"


# ── Message format conversion (Anthropic → OpenAI) ──


class TestMessageFormatConversion:
    """V8-4: Anthropic-format messages → OpenAI-format messages."""

    def test_simple_user_message_passthrough(self) -> None:
        """纯文本 user message 透传."""
        from auto_engineering.providers.openai_provider import _anthropic_messages_to_openai

        messages = [{"role": "user", "content": "hello"}]
        result = _anthropic_messages_to_openai(messages)
        assert result == [{"role": "user", "content": "hello"}]

    def test_assistant_with_tool_uses(self) -> None:
        """assistant + tool_uses → OpenAI assistant + tool_calls."""
        from auto_engineering.providers.openai_provider import _anthropic_messages_to_openai

        messages = [{
            "role": "assistant",
            "content": [{"type": "text", "text": "ok"}, {"type": "tool_use", "id": "t1", "name": "read", "input": {}}],
        }]
        result = _anthropic_messages_to_openai(messages)
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == "ok"
        assert result[0]["tool_calls"] is not None

    def test_tool_result_conversion(self) -> None:
        """tool_result role → OpenAI tool role with tool_call_id."""
        from auto_engineering.providers.openai_provider import _anthropic_messages_to_openai

        messages = [{
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "result"}],
        }]
        result = _anthropic_messages_to_openai(messages)
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "t1"


# ── OpenAIProvider class ──


class TestOpenAIProvider:
    """V8-4: OpenAIProvider — 实现 LLMProvider Protocol."""

    def test_openai_provider_satisfies_llm_provider_protocol(self) -> None:
        """OpenAIProvider 满足 LLMProvider Protocol."""
        from auto_engineering.providers.base import LLMProvider
        from auto_engineering.providers.openai_provider import OpenAIProvider

        provider = OpenAIProvider(api_key="test-key")
        assert hasattr(provider, "create_message")
        assert hasattr(provider, "close")

    @pytest.mark.asyncio
    async def test_create_message_mock(self) -> None:
        """OpenAIProvider.create_message() 用 mock OpenAI API 可正常调用."""
        from unittest.mock import AsyncMock, MagicMock

        from auto_engineering.providers.openai_provider import OpenAIProvider

        provider = OpenAIProvider(api_key="test-key")
        # Inject mock client
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content="OK", tool_calls=None), finish_reason="stop"),
        ]
        mock_completion.model = "gpt-5"
        mock_completion.usage = MagicMock(prompt_tokens=5, completion_tokens=2, total_tokens=7)
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)
        provider._client = mock_client

        result = await provider.create_message(
            system="You are helpful.",
            messages=[{"role": "user", "content": "hi"}],
            model="gpt-5",
        )
        assert result.content == "OK"
        assert result.model == "gpt-5"

    def test_openai_provider_close(self) -> None:
        """OpenAIProvider.close() 释放连接."""
        from auto_engineering.providers.openai_provider import OpenAIProvider

        provider = OpenAIProvider(api_key="test-key")
        mock_client = MagicMock()
        provider._client = mock_client
        provider.close()
        mock_client.close.assert_called_once()


# ── Factory ──


class TestProviderFactory:
    """V8-4: create_provider() 工厂函数."""

    def test_factory_creates_anthropic_provider(self) -> None:
        """create_provider('anthropic') → AnthropicProvider."""
        from auto_engineering.providers.factory import create_provider
        from auto_engineering.llm.anthropic_provider import AnthropicProvider

        provider = create_provider("anthropic", api_key="test-key")
        assert isinstance(provider, AnthropicProvider)

    def test_factory_creates_openai_provider(self) -> None:
        """create_provider('openai') → OpenAIProvider."""
        from auto_engineering.providers.factory import create_provider
        from auto_engineering.providers.openai_provider import OpenAIProvider

        provider = create_provider("openai", api_key="test-key")
        assert isinstance(provider, OpenAIProvider)

    def test_factory_unknown_provider_raises(self) -> None:
        """未知 provider → AEError."""
        from auto_engineering.providers.factory import create_provider

        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider("unknown_provider_xyz", api_key="test-key")

    def test_factory_auto_detect_from_env(self, monkeypatch) -> None:
        """无显式 provider 时从环境变量自动检测."""
        from auto_engineering.providers.factory import create_provider
        from auto_engineering.providers.openai_provider import OpenAIProvider

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

        provider = create_provider(api_key="sk-test")
        assert isinstance(provider, OpenAIProvider)
