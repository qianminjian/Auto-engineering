"""Tests for AnthropicProvider — Phase 3 C1.

TDD protocol: 写测试 → 确认 FAIL → 写实现 → 确认 PASS.

设计参考: design/LOOP-DEVELOPMENT-PLAN.md Phase 3 文件 18.

测试策略: mock anthropic.Anthropic 客户端,验证 create_message 返回
LLMResponse 结构化数据. 不发真实 API 调用（mock-friendly per
engineering-practices.md §1.2).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestLLMUsageDataclass:
    """LLMUsage 数据类 — 记录 token 用量."""

    def test_usage_default_zeros(self):
        from auto_engineering.llm.anthropic_provider import LLMUsage

        u = LLMUsage()
        assert u.input_tokens == 0
        assert u.output_tokens == 0

    def test_usage_explicit_values(self):
        from auto_engineering.llm.anthropic_provider import LLMUsage

        u = LLMUsage(input_tokens=100, output_tokens=50)
        assert u.input_tokens == 100
        assert u.output_tokens == 50

    def test_total_tokens_sum(self):
        from auto_engineering.llm.anthropic_provider import LLMUsage

        u = LLMUsage(input_tokens=120, output_tokens=80)
        assert u.total_tokens == 200


class TestLLMResponseDataclass:
    """LLMResponse 数据类 — API 调用结果."""

    def test_response_required_fields(self):
        from auto_engineering.llm.anthropic_provider import LLMResponse, LLMUsage

        usage = LLMUsage(input_tokens=10, output_tokens=20)
        r = LLMResponse(content="hello", model="claude-test", usage=usage)
        assert r.content == "hello"
        assert r.model == "claude-test"
        assert r.usage.input_tokens == 10


class TestAnthropicProvider:
    """AnthropicProvider — 封装 anthropic SDK 的客户端."""

    def test_create_message_returns_llm_response(self):
        """RED: provider.create_message 必须返回 LLMResponse (含 content/usage/model)."""
        from auto_engineering.llm.anthropic_provider import (
            AnthropicProvider,
            LLMResponse,
        )

        # Mock anthropic.Anthropic client
        mock_client = MagicMock()
        mock_response = MagicMock()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "hi there"
        mock_response.content = [text_block]
        mock_response.model = "claude-test-model"
        mock_response.stop_reason = "end_turn"
        mock_response.usage.input_tokens = 5
        mock_response.usage.output_tokens = 3
        mock_client.messages.create.return_value = mock_response

        provider = AnthropicProvider(client=mock_client)
        result = provider.create_message(
            model="claude-test-model",
            max_tokens=100,
            system="you are a helper",
            messages=[{"role": "user", "content": "say hi"}],
        )

        assert isinstance(result, LLMResponse)
        assert result.content == "hi there"
        assert result.model == "claude-test-model"
        assert result.usage.input_tokens == 5
        assert result.usage.output_tokens == 3

    def test_create_message_passes_kwargs_to_sdk(self):
        """验证 model/max_tokens/system/messages 都传给 SDK."""
        from auto_engineering.llm.anthropic_provider import AnthropicProvider

        mock_client = MagicMock()
        mock_response = MagicMock()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "x"
        mock_response.content = [text_block]
        mock_response.model = "m"
        mock_response.stop_reason = "end_turn"
        mock_response.usage.input_tokens = 0
        mock_response.usage.output_tokens = 0
        mock_client.messages.create.return_value = mock_response

        provider = AnthropicProvider(client=mock_client)
        provider.create_message(
            model="claude-x",
            max_tokens=2048,
            system="sys-prompt",
            messages=[{"role": "user", "content": "q"}],
        )

        mock_client.messages.create.assert_called_once_with(
            model="claude-x",
            max_tokens=2048,
            system="sys-prompt",
            messages=[{"role": "user", "content": "q"}],
        )

    def test_create_message_default_client_uses_api_key(self):
        """不传 client 时,从环境变量 ANTHROPIC_API_KEY 构造默认 client."""
        from auto_engineering.llm.anthropic_provider import AnthropicProvider

        mock_anthropic_class = MagicMock()
        with patch(
            "auto_engineering.llm.anthropic_provider.anthropic.Anthropic",
            mock_anthropic_class,
        ):
            provider = AnthropicProvider(api_key="sk-test-123")
            # 不实际调用 create_message,只验证 client 构造路径
            mock_anthropic_class.assert_called_once_with(api_key="sk-test-123")
            assert provider is not None


class TestLLMResponseToolFields:
    """LLMResponse 扩展字段 — 工具调用支持."""

    def test_response_default_stop_reason(self):
        """LLMResponse.stop_reason 默认 'end_turn'."""
        from auto_engineering.llm.anthropic_provider import LLMResponse, LLMUsage

        r = LLMResponse(content="x", model="m", usage=LLMUsage())
        assert r.stop_reason == "end_turn"
        assert r.tool_use_blocks == []

    def test_response_with_tool_use_blocks(self):
        """LLMResponse 可带 tool_use_blocks."""
        from auto_engineering.llm.anthropic_provider import LLMResponse, LLMUsage

        blocks = [{"id": "toolu_1", "name": "read_file", "input": {"path": "x.py"}}]
        r = LLMResponse(
            content="",
            model="m",
            usage=LLMUsage(),
            stop_reason="tool_use",
            tool_use_blocks=blocks,
        )
        assert r.stop_reason == "tool_use"
        assert len(r.tool_use_blocks) == 1
        assert r.tool_use_blocks[0]["name"] == "read_file"


class TestAnthropicProviderToolsSupport:
    """AnthropicProvider 支持 tools 参数 + tool_use_blocks 解析."""

    def test_create_message_accepts_tools_kwarg(self):
        """create_message 接受 tools 参数并传给 SDK."""
        from auto_engineering.llm.anthropic_provider import AnthropicProvider

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="x")]
        mock_response.model = "m"
        mock_response.usage.input_tokens = 0
        mock_response.usage.output_tokens = 0
        mock_client.messages.create.return_value = mock_response

        provider = AnthropicProvider(client=mock_client)
        tools = [{"name": "read_file", "description": "Read a file"}]
        provider.create_message(
            model="m",
            max_tokens=100,
            system="sys",
            messages=[{"role": "user", "content": "q"}],
            tools=tools,
        )
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "tools" in call_kwargs
        assert call_kwargs["tools"] == tools

    def test_create_message_parses_tool_use_blocks(self):
        """SDK 返回 tool_use block 时, LLMResponse.tool_use_blocks 包含解析结果."""
        from auto_engineering.llm.anthropic_provider import AnthropicProvider

        mock_client = MagicMock()
        mock_response = MagicMock()
        # mock SDK response: 包含 text block + tool_use block
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "I'll read the file"
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.id = "toolu_abc123"
        tool_use_block.name = "read_file"
        tool_use_block.input = {"path": "x.py"}
        mock_response.content = [text_block, tool_use_block]
        mock_response.model = "m"
        mock_response.stop_reason = "tool_use"
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        mock_client.messages.create.return_value = mock_response

        provider = AnthropicProvider(client=mock_client)
        result = provider.create_message(
            model="m",
            max_tokens=100,
            system="sys",
            messages=[{"role": "user", "content": "q"}],
        )
        assert result.stop_reason == "tool_use"
        assert result.content == "I'll read the file"
        assert len(result.tool_use_blocks) == 1
        assert result.tool_use_blocks[0]["id"] == "toolu_abc123"
        assert result.tool_use_blocks[0]["name"] == "read_file"
        assert result.tool_use_blocks[0]["input"] == {"path": "x.py"}

    def test_create_message_text_only_response(self):
        """SDK 返回纯 text block (无 tool_use) 时, tool_use_blocks 为空."""
        from auto_engineering.llm.anthropic_provider import AnthropicProvider

        mock_client = MagicMock()
        mock_response = MagicMock()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Final answer"
        mock_response.content = [text_block]
        mock_response.model = "m"
        mock_response.stop_reason = "end_turn"
        mock_response.usage.input_tokens = 5
        mock_response.usage.output_tokens = 3
        mock_client.messages.create.return_value = mock_response

        provider = AnthropicProvider(client=mock_client)
        result = provider.create_message(
            model="m",
            max_tokens=100,
            system="sys",
            messages=[],
        )
        assert result.stop_reason == "end_turn"
        assert result.content == "Final answer"
        assert result.tool_use_blocks == []


class TestAnthropicProviderKwargs:
    """AnthropicProvider.create_message 参数扩展 - kwargs (model/max_tokens/system/messages/tools)."""

    def test_create_message_passes_all_kwargs(self):
        """验证 model/max_tokens/system/messages/tools 都传给 SDK."""
        from auto_engineering.llm.anthropic_provider import AnthropicProvider

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="x")]
        mock_response.model = "m"
        mock_response.stop_reason = "end_turn"
        mock_response.usage.input_tokens = 0
        mock_response.usage.output_tokens = 0
        mock_client.messages.create.return_value = mock_response

        provider = AnthropicProvider(client=mock_client)
        tools = [{"name": "x"}]
        provider.create_message(
            model="claude-x",
            max_tokens=2048,
            system="sys-prompt",
            messages=[{"role": "user", "content": "q"}],
            tools=tools,
        )
        mock_client.messages.create.assert_called_once_with(
            model="claude-x",
            max_tokens=2048,
            system="sys-prompt",
            messages=[{"role": "user", "content": "q"}],
            tools=tools,
        )