"""P1.4 — Tool 错误 AEError 化测试.

验收:
- ToolResult 带 error_code → BaseAgent 抛 AEError(INVALID_AGENT_OUTPUT)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from auto_engineering.agents.base import BaseAgent
from auto_engineering.engine.state import LoopState
from auto_engineering.errors import AEError, ErrorCode
from auto_engineering.runtime.context import TaskContext
from auto_engineering.runtime.task import Task
from auto_engineering.tools.base import BaseTool, ToolResult
from tests.conftest import run_async


class TestToolErrorAEError:
    """P1.4: ToolResult.error_code → AEError."""

    def _run_agent_with_tool(self, tool: BaseTool) -> BaseAgent:
        llm = MagicMock()
        # LLM 要求调用 tool
        llm.create_message = AsyncMock(
            return_value=MagicMock(
                content="",
                model="m",
                usage=MagicMock(input_tokens=0, output_tokens=0),
                stop_reason="tool_use",
                tool_use_blocks=[
                    {"id": "x", "name": tool.name, "input": {}}
                ],
            )
        )
        return BaseAgent(llm=llm, system_prompt="test", tools=[tool])

    async def _execute(self, agent: BaseAgent):
        task = Task(id="t", description="x", expected_output="y", output_channels=["x"])
        ctx = TaskContext(state=LoopState(), requirement="r")
        return await agent.execute(task, ctx)

    def test_tool_with_error_code_raises_aeerror(self):
        """ToolResult(error_code=TOOL_NOT_FOUND) → AEError(INVALID_AGENT_OUTPUT)."""

        class FakeTool(BaseTool):
            name = "fake_tool"
            parameters = {}
            async def execute(self, **kwargs):
                return ToolResult(
                    success=False,
                    content="",
                    error="tool not found",
                    error_code=ErrorCode.TASK_NOT_FOUND,
                )

        agent = self._run_agent_with_tool(FakeTool())
        with pytest.raises(AEError) as ctx:
            run_async(self._execute(agent))
        assert ctx.value.code == ErrorCode.INVALID_AGENT_OUTPUT

    def test_tool_without_error_code_no_raise(self):
        """ToolResult 无 error_code → 不抛 AEError,正常结束."""

        class OkTool(BaseTool):
            name = "ok_tool"
            parameters = {}
            async def execute(self, **kwargs):
                return ToolResult(success=True, content="ok")

        # LLM: 第一轮 tool_use,第二轮 end_turn
        llm = MagicMock()
        call_count = [0]

        async def mock_create_message(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return MagicMock(
                    content="",
                    model="m",
                    usage=MagicMock(input_tokens=0, output_tokens=0),
                    stop_reason="tool_use",
                    tool_use_blocks=[{"id": "x", "name": "ok_tool", "input": {}}],
                )
            return MagicMock(
                content='{"result": "ok"}',
                model="m",
                usage=MagicMock(input_tokens=0, output_tokens=0),
                stop_reason="end_turn",
                tool_use_blocks=[],
            )

        llm.create_message = AsyncMock(side_effect=mock_create_message)
        agent = BaseAgent(llm=llm, system_prompt="test", tools=[OkTool()])
        result = run_async(self._execute(agent))
        assert result.values.get("result") == "ok"
