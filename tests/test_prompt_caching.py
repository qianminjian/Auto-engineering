"""Tests for prompt caching — cache_control injection in Anthropic provider (T63)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestPromptCaching:
    """cache_control injection in create_message()."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        client = MagicMock()
        response = MagicMock()
        response.content = [MagicMock(type="text", text="OK")]
        response.model = "claude-sonnet-4-6"
        response.stop_reason = "end_turn"
        response.usage.input_tokens = 100
        response.usage.output_tokens = 50
        client.messages.create.return_value = response
        return client

    @pytest.fixture
    def provider(self, mock_client: MagicMock):
        from auto_engineering.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(client=mock_client, max_retries=0)

    @pytest.mark.asyncio
    async def test_injects_cache_control_on_last_system_block(self, provider, mock_client) -> None:
        """System string → content blocks with cache_control on last block."""
        await provider.create_message(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system="You are a helpful assistant.",
            messages=[{"role": "user", "content": "Hello"}],
        )
        call_kwargs = mock_client.messages.create.call_args.kwargs
        system_blocks = call_kwargs["system"]
        assert isinstance(system_blocks, list)
        assert len(system_blocks) >= 1
        last_block = system_blocks[-1]
        assert last_block.get("cache_control") == {"type": "ephemeral"}

    @pytest.mark.asyncio
    async def test_injects_cache_control_on_last_tool(self, provider, mock_client) -> None:
        """Last tool in tools array gets cache_control."""
        tools = [
            {"name": "bash", "description": "Run command", "input_schema": {"type": "object", "properties": {}}},
            {"name": "edit", "description": "Edit file", "input_schema": {"type": "object", "properties": {}}},
        ]
        await provider.create_message(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system="You are a helpful assistant.",
            messages=[{"role": "user", "content": "Hello"}],
            tools=tools,
        )
        call_kwargs = mock_client.messages.create.call_args.kwargs
        tools_sent = call_kwargs["tools"]
        assert len(tools_sent) == 2
        last_tool = tools_sent[-1]
        assert last_tool.get("cache_control") == {"type": "ephemeral"}

    @pytest.mark.asyncio
    async def test_no_cache_control_when_no_tools(self, provider, mock_client) -> None:
        """No tools → no tools injection needed (only system block gets it)."""
        await provider.create_message(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system="You are a helpful assistant.",
            messages=[{"role": "user", "content": "Hello"}],
            tools=None,
        )
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "tools" not in call_kwargs or call_kwargs["tools"] is None

    @pytest.mark.asyncio
    async def test_system_already_list_preserved_with_cache_control(self, provider, mock_client) -> None:
        """If system is already a list of blocks, cache_control added to last."""
        system_blocks = [
            {"type": "text", "text": "You are an architect."},
            {"type": "text", "text": "Additional guidelines..."},
        ]
        await provider.create_message(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_blocks,
            messages=[{"role": "user", "content": "Design"}],
        )
        call_kwargs = mock_client.messages.create.call_args.kwargs
        sent_system = call_kwargs["system"]
        assert isinstance(sent_system, list)
        assert sent_system[-1].get("cache_control") == {"type": "ephemeral"}
        # First block should NOT have cache_control (only last)
        assert "cache_control" not in sent_system[0]

    @pytest.mark.asyncio
    async def test_does_not_modify_original_system_list(self, provider, mock_client) -> None:
        """Original system list is not mutated (defensive copy)."""
        system_blocks = [
            {"type": "text", "text": "You are an architect."},
            {"type": "text", "text": "Guidelines."},
        ]
        original = [dict(b) for b in system_blocks]
        await provider.create_message(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_blocks,
            messages=[{"role": "user", "content": "Hi"}],
        )
        assert system_blocks == original

    @pytest.mark.asyncio
    async def test_cache_control_disabled_by_env_var(self, provider, mock_client, monkeypatch) -> None:
        """AE_CACHE_CONTROL=0 disables cache_control injection."""
        monkeypatch.setenv("AE_CACHE_CONTROL", "0")
        await provider.create_message(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system="You are a helpful assistant.",
            messages=[{"role": "user", "content": "Hello"}],
        )
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "You are a helpful assistant."
