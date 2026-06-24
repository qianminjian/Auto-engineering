"""Tests for agents/base.py — Phase 0.1 BaseAgent 真接.

TDD Red phase: BaseAgent.execute 测试.
设计: dev-loop 真接 LLM 调用 + 工具循环 + max_tool_calls + output_schema.

API 契约(对齐 runtime/task.py TaskResult):
    - result.values        (dict, 替代旧 result.parsed)
    - result.raw_response  (LLMResponse, 替代旧 result.content)
    - result.tool_calls    (list[dict], 记录工具调用)
    - result.task_id       (str)
    - result.agent_type    (str)

修复 dev-loop-TODO.md C3c 阻塞:
    旧 test_base_agent.py 假设 result.content/result.parsed/error/usage — 与
    runtime.task.TaskResult 字段不一致. 已重写为对齐 TaskResult.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from auto_engineering.agents.base import BaseAgent
from auto_engineering.engine.state import LoopState
from auto_engineering.llm.anthropic_provider import (
    AnthropicProvider,
    LLMResponse,
    LLMUsage,
)
from auto_engineering.runtime.context import TaskContext
from auto_engineering.runtime.task import Task, TaskResult
from auto_engineering.tools.base import BaseTool, ToolResult
from tests.conftest import run_async


def _make_text_response(text: str, model: str = "claude-test") -> LLMResponse:
    """Helper: 构造纯 text LLMResponse."""
    return LLMResponse(
        content=text,
        model=model,
        usage=LLMUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
        tool_use_blocks=[],
    )


def _make_tool_use_response(blocks: list[dict], model: str = "claude-test") -> LLMResponse:
    """Helper: 构造 tool_use LLMResponse."""
    return LLMResponse(
        content="",
        model=model,
        usage=LLMUsage(input_tokens=10, output_tokens=5),
        stop_reason="tool_use",
        tool_use_blocks=blocks,
    )


class TestBaseAgentCreation:
    """BaseAgent 构造."""

    def test_minimal_creation(self):
        """BaseAgent 接受 llm + system_prompt."""
        llm = MagicMock(spec=AnthropicProvider)
        agent = BaseAgent(llm=llm, system_prompt="test prompt")
        assert agent.llm is llm
        assert agent.system_prompt == "test prompt"
        assert agent.tools == []
        assert agent.max_tool_calls == 10

    def test_with_tools(self):
        """BaseAgent 接受 tools 列表."""
        llm = MagicMock(spec=AnthropicProvider)
        tool = MagicMock(spec=BaseTool)
        tool.name = "read_file"
        agent = BaseAgent(
            llm=llm,
            system_prompt="test",
            tools=[tool],
        )
        assert len(agent.tools) == 1
        assert agent.tools[0].name == "read_file"


class TestBaseAgentExecuteSimple:
    """execute() 简单场景(无 tool_use)."""

    def test_execute_returns_parsed_values(self):
        """LLM 返回 JSON 文本 → BaseAgent 解析为 values."""
        llm = MagicMock(spec=AnthropicProvider)
        llm.create_message = AsyncMock(
            return_value=_make_text_response(
                '{"plan": "do it", "file_list": ["x.py"]}',
            )
        )
        agent = BaseAgent(llm=llm, system_prompt="test")
        task = Task(
            id="architect",
            description="analyze requirement",
            expected_output="plan",
            output_channels=["plan", "file_list"],
        )
        ctx = TaskContext(state=LoopState(requirement="r"), requirement="r")

        result = run_async(agent.execute(task, ctx))

        assert isinstance(result, TaskResult)
        assert result.task_id == "architect"
        assert result.values["plan"] == "do it"
        assert result.values["file_list"] == ["x.py"]
        assert result.agent_type == "BaseAgent"
        assert result.tool_calls == []

    def test_execute_calls_llm_with_task_description(self):
        """execute() 把 task.description 作为 user message 传给 LLM."""
        llm = MagicMock(spec=AnthropicProvider)
        llm.create_message = AsyncMock(return_value=_make_text_response('{"x": 1}'))
        agent = BaseAgent(llm=llm, system_prompt="You are an architect.")
        task = Task(
            id="t",
            description="Analyze requirement X carefully",
            expected_output="plan",
            output_channels=["x"],
        )
        ctx = TaskContext(state=LoopState(), requirement="X")

        run_async(agent.execute(task, ctx))

        call_kwargs = llm.create_message.call_args.kwargs
        assert "Analyze requirement X carefully" in str(call_kwargs["messages"])
        assert call_kwargs["system"] == "You are an architect."

    def test_execute_injects_output_schema_into_system(self):
        """有 output_schema 时,schema 注入 system prompt."""
        llm = MagicMock(spec=AnthropicProvider)
        llm.create_message = AsyncMock(return_value=_make_text_response('{"plan": "p"}'))
        agent = BaseAgent(llm=llm, system_prompt="test")
        task = Task(
            id="t",
            description="x",
            expected_output="y",
            output_channels=["plan"],
            output_schema={
                "type": "object",
                "properties": {"plan": {"type": "string"}},
                "required": ["plan"],
            },
        )
        ctx = TaskContext(state=LoopState(), requirement="r")

        run_async(agent.execute(task, ctx))

        call_kwargs = llm.create_message.call_args.kwargs
        system = call_kwargs["system"]
        assert "Output Schema" in system
        assert "plan" in system
        assert "string" in system


class TestBaseAgentExecuteWithTools:
    """execute() 工具调用场景."""

    def test_execute_passes_tools_to_llm(self):
        """tools 转 Anthropic format 传给 LLM."""
        llm = MagicMock(spec=AnthropicProvider)
        llm.create_message = AsyncMock(return_value=_make_text_response('{"plan": "p"}'))

        tool = MagicMock(spec=BaseTool)
        tool.name = "read_file"
        tool.description = "Read a file"
        tool.to_schema.return_value = {
            "name": "read_file",
            "description": "Read a file",
            "input_schema": {"type": "object", "properties": {}},
        }
        agent = BaseAgent(llm=llm, system_prompt="test", tools=[tool])
        task = Task(
            id="t",
            description="x",
            expected_output="y",
            output_channels=["plan"],
        )
        ctx = TaskContext(state=LoopState(), requirement="r")

        run_async(agent.execute(task, ctx))

        call_kwargs = llm.create_message.call_args.kwargs
        assert "tools" in call_kwargs
        assert len(call_kwargs["tools"]) == 1
        assert call_kwargs["tools"][0]["name"] == "read_file"

    def test_execute_handles_tool_use_then_final(self):
        """LLM 返回 tool_use → 执行 tool → 再次调 LLM → 返回 final."""
        llm = MagicMock(spec=AnthropicProvider)
        tool_use = {"id": "toolu_1", "name": "read_file", "input": {"path": "x.py"}}
        llm.create_message = AsyncMock(
            side_effect=[
                _make_tool_use_response([tool_use]),
                _make_text_response('{"plan": "p", "file_list": ["x.py"]}'),
            ]
        )

        tool = MagicMock(spec=BaseTool)
        tool.name = "read_file"

        async def mock_execute(**kwargs):
            return ToolResult(success=True, content="file content here")

        tool.execute = mock_execute

        agent = BaseAgent(llm=llm, system_prompt="test", tools=[tool])
        task = Task(
            id="t",
            description="x",
            expected_output="y",
            output_channels=["plan", "file_list"],
        )
        ctx = TaskContext(state=LoopState(), requirement="r")

        result = run_async(agent.execute(task, ctx))

        assert llm.create_message.call_count == 2
        assert result.values["plan"] == "p"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "read_file"


class TestBaseAgentExecuteErrors:
    """execute() 错误处理."""

    def test_execute_no_json_raises_invalid_output(self):
        """LLM 输出无 JSON → 抛 AEError(INVALID_AGENT_OUTPUT)."""
        from auto_engineering.errors import AEError, ErrorCode

        llm = MagicMock(spec=AnthropicProvider)
        llm.create_message = AsyncMock(
            return_value=_make_text_response(
                "I cannot answer this question in JSON format.",
            )
        )
        agent = BaseAgent(llm=llm, system_prompt="test")
        task = Task(
            id="t",
            description="x",
            expected_output="y",
            output_channels=["plan"],
        )
        ctx = TaskContext(state=LoopState(), requirement="r")

        with pytest.raises(AEError) as exc_info:
            run_async(agent.execute(task, ctx))
        assert exc_info.value.code == ErrorCode.INVALID_AGENT_OUTPUT

    def test_execute_max_tool_calls_exceeded(self):
        """LLM 一直返回 tool_use → 超 max_tool_calls → 抛 MAX_TOOL_CALLS_EXCEEDED."""
        from auto_engineering.errors import AEError

        llm = MagicMock(spec=AnthropicProvider)
        tool_use = {"id": "t1", "name": "x", "input": {}}
        llm.create_message = AsyncMock(return_value=_make_tool_use_response([tool_use]))

        tool = MagicMock(spec=BaseTool)
        tool.name = "x"

        async def mock_execute(**kwargs):
            return ToolResult(success=True, content="ok")

        tool.execute = mock_execute

        agent = BaseAgent(llm=llm, system_prompt="test", tools=[tool], max_tool_calls=2)
        task = Task(id="t", description="x", expected_output="y", output_channels=["p"])
        ctx = TaskContext(state=LoopState(), requirement="r")

        with pytest.raises(AEError) as exc_info:
            run_async(agent.execute(task, ctx))
        assert "exceeded" in str(exc_info.value).lower()
        assert llm.create_message.call_count == 3

    def test_execute_unknown_tool_continues_loop(self):
        """LLM 调不存在的 tool → 工具结果含 error,继续循环到 final."""
        llm = MagicMock(spec=AnthropicProvider)
        tool_use = {"id": "t1", "name": "nonexistent_tool", "input": {}}
        llm.create_message = AsyncMock(
            side_effect=[
                _make_tool_use_response([tool_use]),
                _make_text_response('{"plan": "fallback"}'),
            ]
        )

        agent = BaseAgent(llm=llm, system_prompt="test")
        task = Task(id="t", description="x", expected_output="y", output_channels=["plan"])
        ctx = TaskContext(state=LoopState(), requirement="r")

        result = run_async(agent.execute(task, ctx))

        assert llm.create_message.call_count == 2
        assert result.values["plan"] == "fallback"


class TestBaseAgentCancellation:
    """execute() 接受 cancellation token."""

    def test_execute_cancellation_check_before_llm(self):
        """cancellation 已取消 → 抛异常(不调 LLM)."""
        llm = MagicMock(spec=AnthropicProvider)
        llm.create_message = AsyncMock(return_value=_make_text_response('{"x": 1}'))

        agent = BaseAgent(llm=llm, system_prompt="test")

        cancelled_token = MagicMock()
        cancelled_token.is_cancelled.return_value = True
        cancelled_token.check.side_effect = Exception("TASK_CANCELLED")

        task = Task(id="t", description="x", expected_output="y", output_channels=["x"])
        ctx = TaskContext(state=LoopState(), requirement="r")

        with pytest.raises(Exception, match="TASK_CANCELLED"):
            run_async(agent.execute(task, ctx, cancellation=cancelled_token))

        assert llm.create_message.call_count == 0


class TestBaseAgentProtocolConformance:
    """BaseAgent 实现 Agent Protocol(让 AgentRuntime.register 可用)."""

    def test_base_agent_satisfies_agent_protocol(self):
        from auto_engineering.runtime.runtime import Agent

        llm = MagicMock(spec=AnthropicProvider)
        agent = BaseAgent(llm=llm, system_prompt="test")
        assert isinstance(agent, Agent)
