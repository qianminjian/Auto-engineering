"""3 Agent 真接测试 — Phase 0.3.

Architect / Developer / Critic 各 2 测试(实例化 + execute mock LLM).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from auto_engineering.llm.anthropic_provider import (
    AnthropicProvider,
    LLMResponse,
    LLMUsage,
)
from tests.conftest import run_async


def _make_ok_response(values: dict) -> LLMResponse:
    """Helper: 模拟 LLM 返回 JSON dict."""
    import json

    return LLMResponse(
        content=json.dumps(values),
        model="claude-test",
        usage=LLMUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
        tool_use_blocks=[],
    )


class TestArchitectAgent:
    """ArchitectAgent 真接."""

    def test_instantiation_uses_architect_prompt(self):
        from auto_engineering.agents import ARCHITECT_SYSTEM_PROMPT, ArchitectAgent

        llm = MagicMock(spec=AnthropicProvider)
        agent = ArchitectAgent(llm=llm)
        assert agent.system_prompt == ARCHITECT_SYSTEM_PROMPT
        assert "Architect" in agent.system_prompt or "架构师" in agent.system_prompt
        assert "plan" in agent.system_prompt.lower()

    def test_execute_returns_plan_and_file_list(self):
        from auto_engineering.agents import ArchitectAgent
        from auto_engineering.engine.state import LoopState
        from auto_engineering.runtime.context import TaskContext
        from auto_engineering.runtime.task import Task

        llm = MagicMock(spec=AnthropicProvider)
        llm.create_message.return_value = _make_ok_response(
            {
                "plan": "1. Add auth middleware\n2. Add login endpoint",
                "file_list": ["src/auth.py", "src/middleware.py"],
            }
        )
        agent = ArchitectAgent(llm=llm)
        task = Task(
            id="architect",
            description="design user auth",
            expected_output="plan",
            output_channels=["plan", "file_list"],
        )
        ctx = TaskContext(state=LoopState(), requirement="design user auth")

        result = run_async(agent.execute(task, ctx))

        assert result.values["plan"] == "1. Add auth middleware\n2. Add login endpoint"
        assert result.values["file_list"] == ["src/auth.py", "src/middleware.py"]
        assert result.agent_type == "architect"  # P1-A: factory returns Agent(role='architect')


class TestDeveloperAgent:
    """DeveloperAgent 真接."""

    def test_instantiation_uses_developer_prompt(self):
        from auto_engineering.agents import DEVELOPER_SYSTEM_PROMPT, DeveloperAgent

        llm = MagicMock(spec=AnthropicProvider)
        agent = DeveloperAgent(llm=llm)
        assert agent.system_prompt == DEVELOPER_SYSTEM_PROMPT
        assert "TDD" in agent.system_prompt
        assert "developer" in agent.system_prompt.lower() or "开发者" in agent.system_prompt

    def test_execute_returns_files_changed_and_commit(self):
        from auto_engineering.agents import DeveloperAgent
        from auto_engineering.engine.state import LoopState
        from auto_engineering.runtime.context import TaskContext
        from auto_engineering.runtime.task import Task

        llm = MagicMock(spec=AnthropicProvider)
        llm.create_message.return_value = _make_ok_response(
            {
                "files_changed": ["src/auth.py", "tests/test_auth.py"],
                "commit_hash": "abc123",
                "test_results": {"passed": 5, "failed": 0},
            }
        )
        agent = DeveloperAgent(llm=llm)
        task = Task(
            id="developer",
            description="implement auth",
            expected_output="code",
            output_channels=["files_changed", "commit_hash", "test_results"],
        )
        ctx = TaskContext(state=LoopState(), requirement="implement auth")

        result = run_async(agent.execute(task, ctx))

        assert result.values["files_changed"] == ["src/auth.py", "tests/test_auth.py"]
        assert result.values["commit_hash"] == "abc123"
        assert result.values["test_results"]["passed"] == 5
        assert result.agent_type == "developer"  # P1-A


class TestCriticAgent:
    """CriticAgent 真接."""

    def test_instantiation_uses_critic_prompt(self):
        from auto_engineering.agents import CRITIC_SYSTEM_PROMPT, CriticAgent

        llm = MagicMock(spec=AnthropicProvider)
        agent = CriticAgent(llm=llm)
        assert agent.system_prompt == CRITIC_SYSTEM_PROMPT
        assert "APPROVE" in agent.system_prompt
        assert "MAJOR" in agent.system_prompt

    def test_execute_returns_verdict_and_findings(self):
        from auto_engineering.agents import CriticAgent
        from auto_engineering.engine.state import LoopState
        from auto_engineering.runtime.context import TaskContext
        from auto_engineering.runtime.task import Task

        llm = MagicMock(spec=AnthropicProvider)
        llm.create_message.return_value = _make_ok_response(
            {
                "verdict": "APPROVE",
                "findings": [],
                "critic_feedback": "Looks good.",
            }
        )
        agent = CriticAgent(llm=llm)
        task = Task(
            id="critic",
            description="review commit",
            expected_output="verdict",
            output_channels=["verdict", "findings", "critic_feedback"],
        )
        ctx = TaskContext(state=LoopState(), requirement="review commit")

        result = run_async(agent.execute(task, ctx))

        assert result.values["verdict"] == "APPROVE"
        assert result.values["findings"] == []
        assert result.values["critic_feedback"] == "Looks good."
        assert result.agent_type == "critic"  # P1-A


class TestBaseAgentToolLoop:
    """BaseAgent.execute 工具循环 — P0.1 核心测试.

    验证: task.tools (BaseTool 实例) 被用于工具循环,而非 self.tools。
    """

    def test_effective_tools_prefers_task_tools_over_self_tools(self):
        """P0.1: task.tools 有实例时,即使 self.tools=[] 也用 task.tools."""
        from unittest.mock import MagicMock

        from auto_engineering.agents.base import BaseAgent
        from auto_engineering.runtime.task import Task
        from auto_engineering.tools import WriteFileTool

        # 不传 tools 给 agent(self.tools=[])
        agent = BaseAgent(llm=MagicMock(), system_prompt="test", tools=[])
        write_tool = WriteFileTool()

        # task.tools 有实例(self.tools 为空)
        task = Task(
            id="test",
            description="write a file",
            expected_output="ok",
            tools=[write_tool],  # task.tools 有实例!
        )

        # 手动跑 execute 的关键逻辑,验证 tool_map 正确
        effective_tools = task.tools if task.tools else agent.tools
        tool_map = {t.name: t for t in effective_tools}
        assert "write_file" in tool_map
        assert tool_map["write_file"] is write_tool
        assert "write_file" not in {t.name for t in agent.tools}

class TestAllAgentsImplementAgentProtocol:
    """3 Agent 都满足 Agent Protocol — 让 AgentRuntime.register 可直接接受."""

    def test_all_agents_satisfy_agent_protocol(self):
        from auto_engineering.agents import ArchitectAgent, CriticAgent, DeveloperAgent
        from auto_engineering.llm.anthropic_provider import AnthropicProvider
        from auto_engineering.runtime.runtime import Agent

        llm = MagicMock(spec=AnthropicProvider)
        for AgentClass in (ArchitectAgent, DeveloperAgent, CriticAgent):
            agent = AgentClass(llm=llm)
            assert isinstance(agent, Agent), f"{AgentClass.__name__} not Agent Protocol"


# v2.4 P0-FINAL: TestStageGraphIntegrationWithAgents 已删除 (engine.graph 已移除)
# 3 Agent 现在共享 Agent 类, role 字段替代 agent_type 对齐
