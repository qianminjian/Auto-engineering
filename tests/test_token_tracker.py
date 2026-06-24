"""TokenTracker 真接测试 — Phase 1.3.

覆盖: BaseAgent.execute 接受 token_tracker,累加 LLMUsage,超 max_tokens 抛 BUDGET_EXCEEDED.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from auto_engineering.agents.base import BaseAgent
from auto_engineering.engine.state import LoopState
from auto_engineering.errors import AEError, ErrorCode
from auto_engineering.llm.anthropic_provider import (
    AnthropicProvider,
    LLMResponse,
    LLMUsage,
)
from auto_engineering.runtime.context import TaskContext
from auto_engineering.runtime.task import Task
from tests.conftest import run_async


class TokenTracker:
    """最小测试用 TokenTracker(对齐 cli.py 实现)."""

    def __init__(self, max_tokens: int = 0):
        self.max_tokens = max_tokens
        self.input_tokens = 0
        self.output_tokens = 0

    @property
    def total_tokens(self):
        return self.input_tokens + self.output_tokens

    def add(self, response: LLMResponse):
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens
        if self.max_tokens > 0 and self.total_tokens > self.max_tokens:
            raise AEError(
                ErrorCode.BUDGET_EXCEEDED,
                f"Token budget exceeded: {self.total_tokens} > {self.max_tokens}",
            )


class TestTokenTrackerIntegration:
    """BaseAgent.execute + TokenTracker."""

    def test_execute_without_token_tracker_runs_normally(self):
        """不传 token_tracker → 正常运行,无累加."""
        llm = MagicMock(spec=AnthropicProvider)
        llm.create_message = AsyncMock(return_value=LLMResponse(
            content='{"x": 1}', model="m",
            usage=LLMUsage(input_tokens=100, output_tokens=50),
            stop_reason="end_turn",
        ))
        agent = BaseAgent(llm=llm, system_prompt="test")
        task = Task(id="t", description="x", expected_output="y", output_channels=["x"])
        ctx = TaskContext(state=LoopState(), requirement="r")

        result = run_async(agent.execute(task, ctx))

        assert result.values["x"] == 1

    def test_execute_with_token_tracker_accumulates(self):
        """传 token_tracker → 累加 LLMUsage."""
        llm = MagicMock(spec=AnthropicProvider)
        llm.create_message = AsyncMock(return_value=LLMResponse(
            content='{"x": 1}', model="m",
            usage=LLMUsage(input_tokens=100, output_tokens=50),
            stop_reason="end_turn",
        ))
        agent = BaseAgent(llm=llm, system_prompt="test")
        task = Task(id="t", description="x", expected_output="y", output_channels=["x"])
        ctx = TaskContext(state=LoopState(), requirement="r")

        tracker = TokenTracker()
        run_async(agent.execute(task, ctx, token_tracker=tracker))

        assert tracker.input_tokens == 100
        assert tracker.output_tokens == 50
        assert tracker.total_tokens == 150

    def test_token_tracker_multiple_calls_accumulate(self):
        """多次 LLM 调用(工具循环)累加 token."""
        llm = MagicMock(spec=AnthropicProvider)
        # 第一次 tool_use,第二次 final
        tool_use = {"id": "t1", "name": "x", "input": {}}
        llm.create_message = AsyncMock(side_effect=[
            LLMResponse(content="", model="m",
                usage=LLMUsage(input_tokens=100, output_tokens=10),
                stop_reason="tool_use",
                tool_use_blocks=[tool_use]),
            LLMResponse(content='{"plan": "p"}', model="m",
                usage=LLMUsage(input_tokens=200, output_tokens=20),
                stop_reason="end_turn"),
        ])

        from auto_engineering.tools.base import BaseTool, ToolResult
        tool = MagicMock(spec=BaseTool)
        tool.name = "x"

        async def mock_execute(**kwargs):
            return ToolResult(success=True, content="ok")
        tool.execute = mock_execute

        agent = BaseAgent(llm=llm, system_prompt="test", tools=[tool])
        task = Task(id="t", description="x", expected_output="y", output_channels=["plan"])
        ctx = TaskContext(state=LoopState(), requirement="r")

        tracker = TokenTracker()
        run_async(agent.execute(task, ctx, token_tracker=tracker))

        # 2 次调用累加
        assert tracker.input_tokens == 300  # 100 + 200
        assert tracker.output_tokens == 30  # 10 + 20

    def test_token_tracker_exceeds_budget_raises(self):
        """超 max_tokens → 抛 BUDGET_EXCEEDED."""
        llm = MagicMock(spec=AnthropicProvider)
        llm.create_message = AsyncMock(return_value=LLMResponse(
            content='{"x": 1}', model="m",
            usage=LLMUsage(input_tokens=200, output_tokens=0),
            stop_reason="end_turn",
        ))
        agent = BaseAgent(llm=llm, system_prompt="test")
        task = Task(id="t", description="x", expected_output="y", output_channels=["x"])
        ctx = TaskContext(state=LoopState(), requirement="r")

        tracker = TokenTracker(max_tokens=100)  # 上限 100,但 LLM 用了 200

        with pytest.raises(AEError) as exc_info:
            run_async(agent.execute(task, ctx, token_tracker=tracker))
        assert exc_info.value.code == ErrorCode.BUDGET_EXCEEDED

    def test_token_tracker_unlimited_no_raise(self):
        """max_tokens=0 (无限制) → 不抛."""
        llm = MagicMock(spec=AnthropicProvider)
        llm.create_message = AsyncMock(return_value=LLMResponse(
            content='{"x": 1}', model="m",
            usage=LLMUsage(input_tokens=10000, output_tokens=10000),
            stop_reason="end_turn",
        ))
        agent = BaseAgent(llm=llm, system_prompt="test")
        task = Task(id="t", description="x", expected_output="y", output_channels=["x"])
        ctx = TaskContext(state=LoopState(), requirement="r")

        tracker = TokenTracker(max_tokens=0)  # 0 = 无限制
        result = run_async(agent.execute(task, ctx, token_tracker=tracker))
        assert result.values["x"] == 1
        assert tracker.total_tokens == 20000
