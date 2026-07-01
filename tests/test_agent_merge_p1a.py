"""P1-A: 3 Agent 类合并为 1 个 Agent(role, system_prompt, llm).

设计动机:
- ArchitectAgent / DeveloperAgent / CriticAgent 三个子类各 ~50-70 行
- 实际逻辑全在 BaseAgent (289 行), 子类仅设默认 system_prompt
- 是过度 OO 拆分 → 合并为 1 个 Agent 类, 3 个 system_prompt 提为 module-level const

TDD: RED → GREEN.
"""
from __future__ import annotations


class TestAgentClassUnification:
    """P1-A: 合并后单 Agent 类支持 3 种 role."""

    def test_architect_agent_uses_architect_prompt(self) -> None:
        """role=architect + system_prompt=ARCHITECT_SYSTEM_PROMPT."""
        from auto_engineering.agents.base import Agent
        from auto_engineering.agents.prompts import ARCHITECT_SYSTEM_PROMPT

        from unittest.mock import MagicMock

        agent = Agent(
            role="architect",
            system_prompt=ARCHITECT_SYSTEM_PROMPT,
            llm=MagicMock(),
        )
        assert agent.role == "architect"
        assert agent.system_prompt == ARCHITECT_SYSTEM_PROMPT
        assert "ArchitectAgent" not in type(agent).__name__  # 不是 ArchitectAgent 子类

    def test_developer_agent_uses_developer_prompt(self) -> None:
        from auto_engineering.agents.base import Agent
        from auto_engineering.agents.prompts import DEVELOPER_SYSTEM_PROMPT

        from unittest.mock import MagicMock

        agent = Agent(
            role="developer",
            system_prompt=DEVELOPER_SYSTEM_PROMPT,
            llm=MagicMock(),
        )
        assert agent.role == "developer"
        assert agent.system_prompt == DEVELOPER_SYSTEM_PROMPT

    def test_critic_agent_uses_critic_prompt(self) -> None:
        from auto_engineering.agents.base import Agent
        from auto_engineering.agents.prompts import CRITIC_SYSTEM_PROMPT

        from unittest.mock import MagicMock

        agent = Agent(
            role="critic",
            system_prompt=CRITIC_SYSTEM_PROMPT,
            llm=MagicMock(),
        )
        assert agent.role == "critic"
        assert agent.system_prompt == CRITIC_SYSTEM_PROMPT


class TestAgentBackwardCompat:
    """旧名 ArchitectAgent/DeveloperAgent/CriticAgent 作为 Agent 的 factory 保留."""

    def test_architect_agent_alias(self) -> None:
        """ArchitectAgent() → Agent(role='architect', system_prompt=ARCHITECT)."""
        from auto_engineering.agents.architect import ARCHITECT_SYSTEM_PROMPT
        from auto_engineering.agents.architect import ArchitectAgent
        from auto_engineering.agents.base import Agent
        from unittest.mock import MagicMock

        agent = ArchitectAgent(llm=MagicMock())
        assert isinstance(agent, Agent)
        assert agent.role == "architect"
        assert agent.system_prompt == ARCHITECT_SYSTEM_PROMPT

    def test_developer_agent_alias(self) -> None:
        from auto_engineering.agents.developer import DEVELOPER_SYSTEM_PROMPT
        from auto_engineering.agents.developer import DeveloperAgent
        from auto_engineering.agents.base import Agent
        from unittest.mock import MagicMock

        agent = DeveloperAgent(llm=MagicMock())
        assert isinstance(agent, Agent)
        assert agent.role == "developer"
        assert agent.system_prompt == DEVELOPER_SYSTEM_PROMPT

    def test_critic_agent_alias(self) -> None:
        from auto_engineering.agents.critic import CRITIC_SYSTEM_PROMPT
        from auto_engineering.agents.critic import CriticAgent
        from auto_engineering.agents.base import Agent
        from unittest.mock import MagicMock

        agent = CriticAgent(llm=MagicMock())
        assert isinstance(agent, Agent)
        assert agent.role == "critic"
        assert agent.system_prompt == CRITIC_SYSTEM_PROMPT
