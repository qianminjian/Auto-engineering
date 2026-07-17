"""Tests for V8-5: BaseAgent + LLMProvider Protocol integration.

TDD protocol: 写测试 → 确认 FAIL → 写实现 → 确认 PASS.
"""

from __future__ import annotations

import pytest


class TestBaseAgentLLMProviderTypeAnnotation:
    """V8-5: BaseAgent.llm 类型注解从 AnthropicProvider → LLMProvider Protocol."""

    def test_anthropic_provider_assignable(self) -> None:
        """AnthropicProvider 可赋值给 BaseAgent.llm."""
        from auto_engineering.agents.base import BaseAgent
        from auto_engineering.llm.anthropic_provider import AnthropicProvider

        agent = BaseAgent.__new__(BaseAgent)
        agent.llm = AnthropicProvider(api_key="test-key")
        assert agent.llm is not None

    def test_llm_has_create_message_and_close(self) -> None:
        """BaseAgent.llm 依赖 create_message() + close() 方法."""
        from auto_engineering.agents.base import BaseAgent
        from auto_engineering.llm.anthropic_provider import AnthropicProvider

        agent = BaseAgent.__new__(BaseAgent)
        agent.llm = AnthropicProvider(api_key="test-key")
        assert callable(agent.llm.create_message)
        assert callable(agent.llm.close)

    def test_base_agent_accepts_llm_provider_protocol(self) -> None:
        """BaseAgent 接受 AnthropicProvider 作为 llm (满足 LLMProvider Protocol)."""
        import dataclasses

        from auto_engineering.agents.base import BaseAgent
        from auto_engineering.llm.anthropic_provider import AnthropicProvider

        fields = {f.name for f in dataclasses.fields(BaseAgent)}
        assert "llm" in fields

        agent = BaseAgent(
            system_prompt="You are helpful.",
            role="architect",
            llm=AnthropicProvider(api_key="test-key"),
        )
        assert agent.llm is not None

    def test_base_agent_close_calls_llm_close(self) -> None:
        """BaseAgent.close() → llm.close() (兼容任何 LLMProvider)."""
        from unittest.mock import MagicMock

        from auto_engineering.agents.base import BaseAgent

        mock_llm = MagicMock()
        agent = BaseAgent.__new__(BaseAgent)
        agent.llm = mock_llm

        agent.close()
        mock_llm.close.assert_called_once()
