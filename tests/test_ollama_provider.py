"""Tests for auto_engineering.providers.ollama — OllamaProvider."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from auto_engineering.providers.base import LLMResponse
from auto_engineering.providers.ollama import OllamaProvider, _is_ollama_available


class TestOllamaProvider:
    """OllamaProvider tests with mocked AsyncOpenAI."""

    @pytest.fixture
    def mock_openai(self) -> AsyncMock:
        with patch("openai.AsyncOpenAI", autospec=True) as mock_cls:
            client = AsyncMock()
            mock_cls.return_value = client
            yield client

    @pytest.fixture
    def provider(self, mock_openai: AsyncMock) -> OllamaProvider:
        return OllamaProvider()

    @pytest.mark.asyncio
    async def test_create_message_simple(self, provider: OllamaProvider, mock_openai: AsyncMock) -> None:
        """Basic text completion round-trips through Ollama."""
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = "Hello from Ollama!"
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "llama3"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await provider.create_message(
            system="You are helpful.",
            messages=[{"role": "user", "content": "Hi"}],
        )
        assert isinstance(result, LLMResponse)
        assert result.content == "Hello from Ollama!"
        assert result.model == "llama3"
        assert result.stop_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_create_message_with_tool_use(self, provider: OllamaProvider, mock_openai: AsyncMock) -> None:
        """Tool-use calls are converted to ToolUseBlock correctly."""
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = ""
        tc = AsyncMock()
        tc.id = "call_1"
        tc.function.name = "read_file"
        tc.function.arguments = '{"path": "/tmp/test.py"}'
        mock_response.choices[0].message.tool_calls = [tc]
        mock_response.choices[0].finish_reason = "tool_calls"
        mock_response.model = "llama3"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await provider.create_message(
            system="",
            messages=[{"role": "user", "content": "Read /tmp/test.py"}],
            tools=[{"name": "read_file", "description": "Read a file", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}}}],
        )
        assert result.stop_reason == "tool_use"
        assert len(result.tool_use_blocks) == 1
        assert result.tool_use_blocks[0].name == "read_file"
        assert result.tool_use_blocks[0].input == {"path": "/tmp/test.py"}

    @pytest.mark.asyncio
    async def test_create_message_with_tools_converted(self, provider: OllamaProvider, mock_openai: AsyncMock) -> None:
        """Anthropic-format tools are converted to OpenAI function tools."""
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = "OK"
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "llama3"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        create_mock = AsyncMock(return_value=mock_response)
        mock_openai.chat.completions.create = create_mock

        tools = [
            {"name": "bash", "description": "Run command", "input_schema": {"type": "object", "properties": {"cmd": {"type": "string"}}}},
        ]
        await provider.create_message(system="", messages=[{"role": "user", "content": "Run ls"}], tools=tools)

        call_kwargs = create_mock.call_args.kwargs
        assert "tools" in call_kwargs
        assert call_kwargs["tools"][0]["type"] == "function"
        assert call_kwargs["tools"][0]["function"]["name"] == "bash"

    def test_custom_base_url(self) -> None:
        """Custom base_url is passed to AsyncOpenAI."""
        with patch("openai.AsyncOpenAI", autospec=True) as mock_cls:
            OllamaProvider(base_url="http://gpu-server:11434/v1")
            mock_cls.assert_called_once_with(
                api_key="ollama",
                base_url="http://gpu-server:11434/v1",
            )

    def test_default_base_url(self) -> None:
        """Default base_url targets localhost:11434."""
        with patch("openai.AsyncOpenAI", autospec=True) as mock_cls:
            OllamaProvider()
            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["base_url"] == "http://localhost:11434/v1"

    def test_is_ollama_available_true(self) -> None:
        """_is_ollama_available() returns True when ollama is importable."""
        assert _is_ollama_available() is True

    @pytest.mark.asyncio
    async def test_close_releases_client(self, provider: OllamaProvider, mock_openai: AsyncMock) -> None:
        """close() calls the underlying client close."""
        provider.close()
        mock_openai.close.assert_called_once()


class TestOllamaProviderEdgeCases:
    """Edge case handling."""

    @pytest.fixture
    def mock_openai(self) -> AsyncMock:
        with patch("openai.AsyncOpenAI", autospec=True) as mock_cls:
            client = AsyncMock()
            mock_cls.return_value = client
            yield client

    @pytest.fixture
    def provider(self, mock_openai: AsyncMock) -> OllamaProvider:
        return OllamaProvider()

    @pytest.mark.asyncio
    async def test_system_message_injected(self, provider: OllamaProvider, mock_openai: AsyncMock) -> None:
        """System prompt is injected as first message (OpenAI format)."""
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = "OK"
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "llama3"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        create_mock = AsyncMock(return_value=mock_response)
        mock_openai.chat.completions.create = create_mock

        await provider.create_message(
            system="You are a bank compliance officer.",
            messages=[{"role": "user", "content": "Check this transaction."}],
        )
        messages = create_mock.call_args.kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a bank compliance officer."

    @pytest.mark.asyncio
    async def test_custom_model(self, provider: OllamaProvider, mock_openai: AsyncMock) -> None:
        """Custom model name is passed through."""
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = "OK"
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "qwen2.5"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        create_mock = AsyncMock(return_value=mock_response)
        mock_openai.chat.completions.create = create_mock

        await provider.create_message(
            system="",
            messages=[{"role": "user", "content": "Hello"}],
            model="qwen2.5:7b",
        )
        assert create_mock.call_args.kwargs["model"] == "qwen2.5:7b"
