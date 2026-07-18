"""Tests for auto_engineering.providers.glm + qwen — domestic model adapters."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from auto_engineering.providers.base import LLMResponse
from auto_engineering.providers.glm import GLMProvider
from auto_engineering.providers.qwen import QwenProvider


def _make_mock_response(content: str = "OK", model: str = "glm-4", finish_reason: str = "stop") -> AsyncMock:
    resp = AsyncMock()
    resp.choices = [AsyncMock()]
    resp.choices[0].message.content = content
    resp.choices[0].message.tool_calls = None
    resp.choices[0].finish_reason = finish_reason
    resp.model = model
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    return resp


class TestGLMProvider:
    """GLM (智谱) provider tests."""

    @pytest.fixture
    def mock_openai(self) -> AsyncMock:
        with patch("openai.AsyncOpenAI", autospec=True) as mock_cls:
            client = AsyncMock()
            mock_cls.return_value = client
            yield client

    @pytest.fixture
    def provider(self, mock_openai: AsyncMock) -> GLMProvider:
        return GLMProvider()

    @pytest.mark.asyncio
    async def test_create_message(self, provider: GLMProvider, mock_openai: AsyncMock) -> None:
        """Basic text completion."""
        mock_openai.chat.completions.create = AsyncMock(return_value=_make_mock_response("你好"))
        result = await provider.create_message(system="", messages=[{"role": "user", "content": "Hi"}])
        assert result.content == "你好"
        assert result.model == "glm-4"

    @pytest.mark.asyncio
    async def test_tool_use_conversion(self, provider: GLMProvider, mock_openai: AsyncMock) -> None:
        """Anthropic tools are converted to OpenAI function tools."""
        create_mock = AsyncMock(return_value=_make_mock_response())
        mock_openai.chat.completions.create = create_mock
        await provider.create_message(
            system="",
            messages=[{"role": "user", "content": "Test"}],
            tools=[{"name": "bash", "description": "Run shell", "input_schema": {"type": "object", "properties": {}}}],
        )
        kwargs = create_mock.call_args.kwargs
        assert kwargs["tools"][0]["type"] == "function"
        assert kwargs["tools"][0]["function"]["name"] == "bash"

    def test_default_base_url(self) -> None:
        """Default base_url targets Zhipu API."""
        with patch("openai.AsyncOpenAI", autospec=True) as mock_cls:
            GLMProvider()
            assert "bigmodel.cn" in mock_cls.call_args.kwargs["base_url"]

    @pytest.mark.asyncio
    async def test_close(self, provider: GLMProvider, mock_openai: AsyncMock) -> None:
        provider.close()
        mock_openai.close.assert_called_once()


class TestQwenProvider:
    """Qwen (通义千问) provider tests."""

    @pytest.fixture
    def mock_openai(self) -> AsyncMock:
        with patch("openai.AsyncOpenAI", autospec=True) as mock_cls:
            client = AsyncMock()
            mock_cls.return_value = client
            yield client

    @pytest.fixture
    def provider(self, mock_openai: AsyncMock) -> QwenProvider:
        return QwenProvider()

    @pytest.mark.asyncio
    async def test_create_message(self, provider: QwenProvider, mock_openai: AsyncMock) -> None:
        """Basic text completion."""
        mock_openai.chat.completions.create = AsyncMock(return_value=_make_mock_response("你好", model="qwen-turbo"))
        result = await provider.create_message(system="", messages=[{"role": "user", "content": "Hi"}])
        assert result.content == "你好"

    @pytest.mark.asyncio
    async def test_tool_use_roundtrip(self, provider: QwenProvider, mock_openai: AsyncMock) -> None:
        """Tool use response is correctly parsed."""
        tcr = AsyncMock()
        tcr.id = "call_1"; tcr.function.name = "read"; tcr.function.arguments = '{"path":"/x"}'
        resp = _make_mock_response(content="", model="qwen-turbo", finish_reason="tool_calls")
        resp.choices[0].message.tool_calls = [tcr]
        mock_openai.chat.completions.create = AsyncMock(return_value=resp)
        result = await provider.create_message(system="", messages=[{"role": "user", "content": "read /x"}])
        assert result.stop_reason == "tool_use"
        assert result.tool_use_blocks[0].name == "read"

    def test_default_base_url(self) -> None:
        """Default base_url targets DashScope API."""
        with patch("openai.AsyncOpenAI", autospec=True) as mock_cls:
            QwenProvider()
            assert "dashscope.aliyuncs.com" in mock_cls.call_args.kwargs["base_url"]

    @pytest.mark.asyncio
    async def test_close(self, provider: QwenProvider, mock_openai: AsyncMock) -> None:
        provider.close()
        mock_openai.close.assert_called_once()
