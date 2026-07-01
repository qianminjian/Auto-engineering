"""Tests for agents/base.py — LLM 异常分支 (P1-3).

目标: agents/base.py 覆盖率 43% → ≥70%.

覆盖维度:
1. _map_llm_exception 异常分类 (5 个 anthropic SDK 异常 + 1 兜底)
2. _parse_final_response 双层解析失败 (4 种坏输出)
3. _validate_tool_input schema 校验 (5 类: 缺失/类型×2/None/skip)
4. execute() 工具循环边界 (max_tool_calls 超限)
5. contract_gate 拒绝 / 通过
6. token_tracker 超限
7. cancellation 协作
8. TaskResult 字段完整性
9. _build_system_prompt schema 注入

设计: 不依赖真实 anthropic SDK,通过 mock 注入 LLM 异常 / 响应.
authz_check 全局 monkeypatch 为 True (测试用 stub_tool 默认不在授权矩阵).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from auto_engineering.agents.base import BaseAgent
from auto_engineering.errors import AEError, ErrorCode
from auto_engineering.llm.anthropic_provider import LLMResponse, LLMUsage
from auto_engineering.runtime.cancellation import CancellationToken
from auto_engineering.runtime.context import TaskContext
from auto_engineering.runtime.task import Task, TaskResult
from auto_engineering.tools.base import BaseTool, ToolResult
from tests.conftest import run_async


# 全局 monkeypatch: 让所有 authz_check 返回 True,简化测试
# (stub_tool 不在 AUTHZ_MATRIX,默认会拒绝)
_AUTHZ_PATCH = patch(
    "auto_engineering.agents.base.authz_check", return_value=True
)
_AUTHZ_PATCH.start()


# =============================================================================
# Helpers
# =============================================================================


def _make_llm_response(
    content: str = "",
    stop_reason: str = "end_turn",
    tool_use_blocks: list[dict] | None = None,
    usage_input: int = 10,
    usage_output: int = 5,
) -> LLMResponse:
    """构造 LLMResponse — 注入到 MagicMock llm.create_message.return_value."""
    return LLMResponse(
        content=content,
        model="claude-test",
        usage=LLMUsage(input_tokens=usage_input, output_tokens=usage_output),
        stop_reason=stop_reason,
        tool_use_blocks=tool_use_blocks or [],
    )


def _make_task(task_id: str = "t1", description: str = "test") -> Task:
    return Task(
        id=task_id,
        description=description,
        expected_output="result",
        tools=[],
        input_channels=[],
        output_channels=[],
    )


def _make_ctx() -> TaskContext:
    from auto_engineering.engine.state import LoopState

    return TaskContext(state=LoopState(), requirement="test")


def _make_agent(
    llm: Any | None = None,
    max_tool_calls: int = 10,
    role: str = "BaseAgent",
    contract_gate: Any = None,
) -> BaseAgent:
    """BaseAgent 实例, llm 默认 MagicMock."""
    if llm is None:
        llm = MagicMock()
    return BaseAgent(
        llm=llm,
        system_prompt="you are test agent",
        tools=[],
        max_tool_calls=max_tool_calls,
        role=role,
        contract_gate=contract_gate,
    )


# 简单 stub tool 用于工具循环测试
# P1.7 schema 校验期望 dict 格式: {"x": {"type": "integer", "required": True}}
class _StubTool(BaseTool):
    name = "stub_tool"
    description = "stub"
    parameters: Any = {"x": {"type": "integer", "required": True}}

    async def execute(self, x: int = 0, **kwargs) -> ToolResult:
        return ToolResult(success=True, content=f"got {x}")


class _StubOptionalTool(BaseTool):
    """schema 必填: optional_param required=False."""

    name = "stub_optional"
    description = "stub optional"
    parameters: Any = {
        "opt": {"type": "boolean", "required": False},
        "req": {"type": "string", "required": True},
    }

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, content=json.dumps(kwargs))


# =============================================================================
# 1. _map_llm_exception: 5 类 anthropic SDK 异常 + 1 兜底
# =============================================================================


class TestMapLLMException:
    """_map_llm_exception 异常分类: 6 条路径.

    Note: base.py 用 type(exc).__name__ 匹配,需要可变的 __name__.
    Exception 是 C 内置类型,__name__ 不可变,所以用动态创建的 class.
    """

    def _make_named_exc(self, class_name: str, msg: str = "simulated") -> Any:
        """动态创建类,设置 __name__,模拟 anthropic SDK 异常类型."""
        cls = type(class_name, (Exception,), {})
        return cls(msg)

    def test_api_timeout_error_maps_to_llm_timeout(self):
        agent = _make_agent()
        exc = self._make_named_exc("APITimeoutError", "simulated timeout")
        result = agent._map_llm_exception(exc)
        assert isinstance(result, AEError)
        assert result.code == ErrorCode.LLM_TIMEOUT
        assert "timeout" in result.message.lower()

    def test_api_connection_error_maps_to_llm_network_error(self):
        agent = _make_agent()
        exc = self._make_named_exc("APIConnectionError", "connection refused")
        result = agent._map_llm_exception(exc)
        assert result.code == ErrorCode.LLM_NETWORK_ERROR
        assert "connection" in result.message.lower() or "network" in result.message.lower()

    def test_api_status_error_maps_to_llm_invalid_response(self):
        agent = _make_agent()
        exc = self._make_named_exc("APIStatusError", "500")
        result = agent._map_llm_exception(exc)
        assert result.code == ErrorCode.LLM_INVALID_RESPONSE

    def test_authentication_error_maps_to_llm_auth_error(self):
        agent = _make_agent()
        exc = self._make_named_exc("AuthenticationError", "401")
        result = agent._map_llm_exception(exc)
        assert result.code == ErrorCode.LLM_AUTH_ERROR

    def test_rate_limit_error_maps_to_llm_rate_limit(self):
        agent = _make_agent()
        exc = self._make_named_exc("RateLimitError", "429")
        result = agent._map_llm_exception(exc)
        assert result.code == ErrorCode.LLM_RATE_LIMIT

    def test_unknown_exception_maps_to_llm_unknown_error(self):
        agent = _make_agent()
        exc = RuntimeError("random failure")
        result = agent._map_llm_exception(exc)
        assert result.code == ErrorCode.LLM_UNKNOWN_ERROR

    def test_keeps_original_exception_as_cause(self):
        """验证 _map_llm_exception 返回的 AEError.message 含原始信息."""
        agent = _make_agent()
        exc = self._make_named_exc("APITimeoutError", "boom")
        result = agent._map_llm_exception(exc)
        assert "boom" in result.message


# =============================================================================
# 2. _parse_final_response: 4 种解析失败
# =============================================================================


class TestParseFinalResponse:
    """_parse_final_response 双层防御失败路径."""

    def test_completely_no_json_raises_invalid_output(self):
        agent = _make_agent()
        with pytest.raises(AEError) as exc_info:
            agent._parse_final_response("hello world no json here")
        assert exc_info.value.code == ErrorCode.INVALID_AGENT_OUTPUT

    def test_empty_string_raises_invalid_output(self):
        agent = _make_agent()
        with pytest.raises(AEError) as exc_info:
            agent._parse_final_response("")
        assert exc_info.value.code == ErrorCode.INVALID_AGENT_OUTPUT

    def test_fence_with_non_json_raises_invalid_output(self):
        agent = _make_agent()
        with pytest.raises(AEError) as exc_info:
            agent._parse_final_response("```json\nnot valid json {[}\n```")
        assert exc_info.value.code == ErrorCode.INVALID_AGENT_OUTPUT

    def test_partial_broken_json_raises_invalid_output(self):
        agent = _make_agent()
        with pytest.raises(AEError) as exc_info:
            agent._parse_final_response('{"key": "val')  # unterminated
        assert exc_info.value.code == ErrorCode.INVALID_AGENT_OUTPUT

    def test_valid_plain_json_returns_dict(self):
        agent = _make_agent()
        result = agent._parse_final_response('{"a": 1, "b": "x"}')
        assert result == {"a": 1, "b": "x"}

    def test_valid_fenced_json_returns_dict(self):
        agent = _make_agent()
        content = "Here is the result:\n```json\n{\"k\": 42}\n```\nDone."
        result = agent._parse_final_response(content)
        assert result == {"k": 42}

    def test_error_message_truncates_long_content(self):
        agent = _make_agent()
        long_text = "x" * 500 + " no json at all"
        with pytest.raises(AEError) as exc_info:
            agent._parse_final_response(long_text)
        # 错误消息应含 truncated (≤ 200 字符 截断)
        assert exc_info.value.code == ErrorCode.INVALID_AGENT_OUTPUT
        # 截断后总长 <= 200 + 前缀 + 后缀
        assert len(exc_info.value.message) < 500


# =============================================================================
# 3. _validate_tool_input: 5 类场景
# =============================================================================


class TestValidateToolInput:
    """_validate_tool_input schema 校验."""

    def test_missing_required_field_raises(self):
        agent = _make_agent()
        tool = _StubTool()  # parameters: {"x": "integer"} required=True
        with pytest.raises(AEError) as exc_info:
            agent._validate_tool_input(tool, {}, "stub_tool")
        assert exc_info.value.code == ErrorCode.INVALID_AGENT_OUTPUT
        assert "x" in exc_info.value.message

    def test_string_for_integer_raises(self):
        agent = _make_agent()
        tool = _StubTool()
        with pytest.raises(AEError) as exc_info:
            agent._validate_tool_input(tool, {"x": "not_int"}, "stub_tool")
        assert exc_info.value.code == ErrorCode.INVALID_AGENT_OUTPUT
        assert "integer" in exc_info.value.message.lower()

    def test_integer_for_boolean_raises(self):
        agent = _make_agent()
        tool = _StubOptionalTool()  # opt: boolean
        with pytest.raises(AEError) as exc_info:
            agent._validate_tool_input(tool, {"opt": 1, "req": "ok"}, "stub_optional")
        assert exc_info.value.code == ErrorCode.INVALID_AGENT_OUTPUT
        assert "boolean" in exc_info.value.message.lower()

    def test_none_value_skips_type_check(self):
        agent = _make_agent()
        tool = _StubOptionalTool()  # opt: boolean, req: string
        # 传 opt=None, req="ok" → opt 是 None → skip type check
        agent._validate_tool_input(tool, {"opt": None, "req": "ok"}, "stub_optional")

    def test_no_schema_tool_skips_validation(self):
        agent = _make_agent()

        class NoSchemaTool(BaseTool):
            name = "no_schema"
            description = "no schema"
            parameters: Any = {}

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(success=True, content="ok")

        tool = NoSchemaTool()
        # 空 schema → 直接 return,不抛
        agent._validate_tool_input(tool, {"anything": 1}, "no_schema")

    def test_optional_missing_field_skips(self):
        agent = _make_agent()
        tool = _StubOptionalTool()  # opt required=False, req required=True
        # 不传 opt (optional) → 跳过; 传 req → OK
        agent._validate_tool_input(tool, {"req": "ok"}, "stub_optional")  # 不抛

    def test_extra_fields_allowed(self):
        """LLM 可能传 schema 之外的字段 (Anthropic 允许 extras),不抛."""
        agent = _make_agent()
        tool = _StubTool()
        agent._validate_tool_input(tool, {"x": 5, "extra": "ignored"}, "stub_tool")


# =============================================================================
# 4. execute() 工具循环 / max_tool_calls
# =============================================================================


class TestExecuteMaxToolCalls:
    """max_tool_calls 超限 → MAX_TOOL_CALLS_EXCEEDED."""

    def test_max_tool_calls_exceeded_raises(self):
        llm = MagicMock()
        # 永远返回 tool_use,让循环耗尽
        llm.create_message.return_value = _make_llm_response(
            stop_reason="tool_use",
            tool_use_blocks=[
                {"id": "t1", "name": "stub_tool", "input": {"x": 1}},
            ],
        )
        agent = _make_agent(llm=llm, max_tool_calls=2)
        task = _make_task()
        task.tools = [_StubTool()]
        ctx = _make_ctx()
        with pytest.raises(AEError) as exc_info:
            run_async(agent.execute(task, ctx))
        assert exc_info.value.code == ErrorCode.MAX_TOOL_CALLS_EXCEEDED
        # 调用次数 == max_tool_calls + 1
        assert llm.create_message.call_count == 3

    def test_normal_completion_returns_task_result(self):
        llm = MagicMock()
        llm.create_message.return_value = _make_llm_response(
            content='{"result": "ok"}',
            stop_reason="end_turn",
        )
        agent = _make_agent(llm=llm, max_tool_calls=5)
        task = _make_task()
        ctx = _make_ctx()
        result = run_async(agent.execute(task, ctx))
        assert isinstance(result, TaskResult)
        assert result.values == {"result": "ok"}
        assert result.task_id == "t1"
        assert result.agent_type == "BaseAgent"
        assert result.tool_calls == []

    def test_tool_call_then_final_response(self):
        """第一次返回 tool_use,第二次返回 end_turn."""
        llm = MagicMock()
        llm.create_message.side_effect = [
            _make_llm_response(
                stop_reason="tool_use",
                tool_use_blocks=[
                    {"id": "t1", "name": "stub_tool", "input": {"x": 7}},
                ],
            ),
            _make_llm_response(content='{"done": true}', stop_reason="end_turn"),
        ]
        agent = _make_agent(llm=llm, max_tool_calls=5)
        task = _make_task()
        task.tools = [_StubTool()]
        ctx = _make_ctx()
        result = run_async(agent.execute(task, ctx))
        assert result.values == {"done": True}
        # tool_calls 记录了 stub_tool 调用
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "stub_tool"
        assert result.tool_calls[0]["input"] == {"x": 7}
        assert llm.create_message.call_count == 2


# =============================================================================
# 5. contract_gate 拒绝 / 通过
# =============================================================================


class TestContractGate:
    """contract_gate 钩子."""

    def test_contract_gate_rejects_raises(self):
        gate = MagicMock(return_value=False)
        agent = _make_agent(contract_gate=gate)
        task = _make_task()
        ctx = _make_ctx()
        with pytest.raises(AEError) as exc_info:
            run_async(agent.execute(task, ctx))
        assert exc_info.value.code == ErrorCode.CONTRACT_REJECTED
        gate.assert_called_once_with(task, ctx)
        # LLM 不应被调用
        agent.llm.create_message.assert_not_called()

    def test_contract_gate_passes_calls_llm(self):
        gate = MagicMock(return_value=True)
        llm = MagicMock()
        llm.create_message.return_value = _make_llm_response(
            content='{"ok": 1}', stop_reason="end_turn"
        )
        agent = _make_agent(llm=llm, contract_gate=gate)
        task = _make_task()
        ctx = _make_ctx()
        result = run_async(agent.execute(task, ctx))
        assert result.values == {"ok": 1}
        assert llm.create_message.call_count == 1

    def test_no_contract_gate_default_approve(self):
        """contract_gate=None → auto-approve,直接调 LLM."""
        llm = MagicMock()
        llm.create_message.return_value = _make_llm_response(
            content='{"x": 1}', stop_reason="end_turn"
        )
        agent = _make_agent(llm=llm, contract_gate=None)
        task = _make_task()
        ctx = _make_ctx()
        result = run_async(agent.execute(task, ctx))
        assert result.values == {"x": 1}


# =============================================================================
# 6. token_tracker 超限
# =============================================================================


class TestTokenTracker:
    """token_tracker.add() 抛 AEError(BUDGET_EXCEEDED) → 透传."""

    def test_token_tracker_exceeded_propagates(self):
        llm = MagicMock()
        llm.create_message.return_value = _make_llm_response(
            content='{"x": 1}', stop_reason="end_turn"
        )

        class BudgetExceededTracker:
            def add(self, response):
                raise AEError(ErrorCode.BUDGET_EXCEEDED, "budget blown")

        agent = _make_agent(llm=llm)
        task = _make_task()
        ctx = _make_ctx()
        with pytest.raises(AEError) as exc_info:
            run_async(agent.execute(task, ctx, token_tracker=BudgetExceededTracker()))
        assert exc_info.value.code == ErrorCode.BUDGET_EXCEEDED

    def test_token_tracker_within_budget_succeeds(self):
        llm = MagicMock()
        llm.create_message.return_value = _make_llm_response(
            content='{"ok": 1}', stop_reason="end_turn"
        )

        calls: list[Any] = []

        class SimpleTracker:
            def add(self, response):
                calls.append(response)

        agent = _make_agent(llm=llm)
        task = _make_task()
        ctx = _make_ctx()
        result = run_async(agent.execute(task, ctx, token_tracker=SimpleTracker()))
        assert result.values == {"ok": 1}
        assert len(calls) == 1


# =============================================================================
# 7. cancellation 协作
# =============================================================================


class TestCancellation:
    """CancellationToken.check() 抛 AEError(TASK_CANCELLED)."""

    def test_cancellation_before_first_call_raises(self):
        llm = MagicMock()
        token = CancellationToken()
        token.cancel()
        agent = _make_agent(llm=llm)
        task = _make_task()
        ctx = _make_ctx()
        with pytest.raises(AEError) as exc_info:
            run_async(agent.execute(task, ctx, cancellation=token))
        assert exc_info.value.code == ErrorCode.TASK_CANCELLED
        llm.create_message.assert_not_called()

    def test_cancellation_during_tool_loop_raises(self):
        llm = MagicMock()
        # 第一次返回 tool_use,第二次前应触发 cancellation
        llm.create_message.return_value = _make_llm_response(
            stop_reason="tool_use",
            tool_use_blocks=[
                {"id": "t1", "name": "stub_tool", "input": {"x": 1}},
            ],
        )
        token = CancellationToken()
        # 安排: 第一次 tool 循环后取消
        # 取消在第二次循环开始前 check
        original_execute = _StubTool.execute

        async def delayed_execute(self, **kwargs):
            token.cancel()  # 第一次工具执行时取消
            return await original_execute(self, **kwargs)

        # 类级覆盖,让 instance 调用时 self 被绑定
        _StubTool.execute = delayed_execute  # type: ignore[method-assign]
        try:
            tool = _StubTool()
            agent = _make_agent(llm=llm, max_tool_calls=5)
            task = _make_task()
            task.tools = [tool]
            ctx = _make_ctx()
            with pytest.raises(AEError) as exc_info:
                run_async(agent.execute(task, ctx, cancellation=token))
            assert exc_info.value.code == ErrorCode.TASK_CANCELLED
        finally:
            _StubTool.execute = original_execute  # type: ignore[method-assign]

    def test_no_cancellation_runs_to_completion(self):
        llm = MagicMock()
        llm.create_message.return_value = _make_llm_response(
            content='{"done": 1}', stop_reason="end_turn"
        )
        agent = _make_agent(llm=llm)
        task = _make_task()
        ctx = _make_ctx()
        result = run_async(agent.execute(task, ctx, cancellation=None))
        assert result.values == {"done": 1}


# =============================================================================
# 8. LLM 异常路径在 execute() 中透传
# =============================================================================


class TestLLMExceptionInExecute:
    """execute() 内部 llm.create_message 抛异常 → _map_llm_exception."""

    def test_timeout_exception_raises_ae_error(self):
        llm = MagicMock()

        class FakeTimeout(Exception):
            pass

        FakeTimeout.__name__ = "APITimeoutError"
        llm.create_message.side_effect = FakeTimeout("simulated")
        agent = _make_agent(llm=llm)
        task = _make_task()
        ctx = _make_ctx()
        with pytest.raises(AEError) as exc_info:
            run_async(agent.execute(task, ctx))
        assert exc_info.value.code == ErrorCode.LLM_TIMEOUT
        # __cause__ 应为原始异常
        assert exc_info.value.__cause__ is not None

    def test_unknown_llm_exception_maps_to_unknown(self):
        llm = MagicMock()
        llm.create_message.side_effect = ValueError("weird value")
        agent = _make_agent(llm=llm)
        task = _make_task()
        ctx = _make_ctx()
        with pytest.raises(AEError) as exc_info:
            run_async(agent.execute(task, ctx))
        assert exc_info.value.code == ErrorCode.LLM_UNKNOWN_ERROR


# =============================================================================
# 9. 工具循环: 未知工具 + 工具异常 + 工具 error_code
# =============================================================================


class TestToolLoopEdgeCases:
    """execute() 工具循环的边界."""

    def test_unknown_tool_returns_error_tool_result(self):
        llm = MagicMock()
        llm.create_message.side_effect = [
            _make_llm_response(
                stop_reason="tool_use",
                tool_use_blocks=[
                    {"id": "t1", "name": "ghost_tool", "input": {}},
                ],
            ),
            _make_llm_response(content='{"done": true}', stop_reason="end_turn"),
        ]
        agent = _make_agent(llm=llm)
        task = _make_task()
        ctx = _make_ctx()
        result = run_async(agent.execute(task, ctx))
        assert result.values == {"done": True}
        # tool_calls 仍记录调用(用于调试)
        assert result.tool_calls[0]["name"] == "ghost_tool"

    def test_tool_exception_continues_loop(self):
        llm = MagicMock()

        class BoomTool(BaseTool):
            name = "boom"
            description = "always fails"
            parameters: Any = {}

            async def execute(self, **kwargs) -> ToolResult:
                raise RuntimeError("kaboom")

        llm.create_message.side_effect = [
            _make_llm_response(
                stop_reason="tool_use",
                tool_use_blocks=[{"id": "t1", "name": "boom", "input": {}}],
            ),
            _make_llm_response(content='{"recovered": true}', stop_reason="end_turn"),
        ]
        agent = _make_agent(llm=llm)
        task = _make_task()
        task.tools = [BoomTool()]
        ctx = _make_ctx()
        result = run_async(agent.execute(task, ctx))
        assert result.values == {"recovered": True}

    def test_tool_error_code_raises_ae_error(self):
        llm = MagicMock()

        class ErrorTool(BaseTool):
            name = "err_tool"
            description = "returns error_code"
            parameters: Any = {}

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(
                    success=False,
                    content="",
                    error="business error",
                    error_code=ErrorCode.INVALID_AGENT_OUTPUT,
                )

        llm.create_message.return_value = _make_llm_response(
            stop_reason="tool_use",
            tool_use_blocks=[{"id": "t1", "name": "err_tool", "input": {}}],
        )
        agent = _make_agent(llm=llm)
        task = _make_task()
        task.tools = [ErrorTool()]
        ctx = _make_ctx()
        with pytest.raises(AEError) as exc_info:
            run_async(agent.execute(task, ctx))
        assert exc_info.value.code == ErrorCode.INVALID_AGENT_OUTPUT


# =============================================================================
# 10. _build_system_prompt: schema 注入
# =============================================================================


class TestBuildSystemPrompt:
    """_build_system_prompt 注入 output_schema."""

    def test_no_schema_returns_original_prompt(self):
        agent = _make_agent()
        task = _make_task()
        # output_schema 默认 None
        prompt = agent._build_system_prompt(task)
        assert prompt == "you are test agent"

    def test_schema_injected_into_prompt(self):
        agent = _make_agent()
        task = _make_task()
        task.output_schema = {
            "type": "object",
            "properties": {"verdict": {"type": "string"}},
        }
        prompt = agent._build_system_prompt(task)
        assert "Output Schema" in prompt
        assert "verdict" in prompt
        assert "```json" in prompt


# =============================================================================
# 11. 工具 schema 校验在 execute() 真实流程中触发
# =============================================================================


class TestValidationInExecute:
    """_validate_tool_input 在 execute 工具循环中被调用 → 抛错."""

    def test_missing_required_field_in_execute_raises(self):
        llm = MagicMock()
        llm.create_message.return_value = _make_llm_response(
            stop_reason="tool_use",
            tool_use_blocks=[
                {"id": "t1", "name": "stub_tool", "input": {}},  # 缺 x
            ],
        )
        agent = _make_agent(llm=llm)
        task = _make_task()
        task.tools = [_StubTool()]  # parameters: {"x": "integer"} required
        ctx = _make_ctx()
        with pytest.raises(AEError) as exc_info:
            run_async(agent.execute(task, ctx))
        assert exc_info.value.code == ErrorCode.INVALID_AGENT_OUTPUT
        assert "x" in exc_info.value.message


# =============================================================================
# 12. task.tools 优先于 self.tools
# =============================================================================


class TestTaskToolsPriority:
    """P0.1: task.tools (BaseTool 实例) 优先于 self.tools."""

    def test_task_tools_used_when_self_tools_empty(self):
        llm = MagicMock()
        llm.create_message.side_effect = [
            _make_llm_response(
                stop_reason="tool_use",
                tool_use_blocks=[
                    {"id": "t1", "name": "stub_tool", "input": {"x": 1}},
                ],
            ),
            _make_llm_response(content='{"ok": 1}', stop_reason="end_turn"),
        ]
        agent = _make_agent(llm=llm, role="developer")
        agent.tools = []  # self.tools 为空
        task = _make_task()
        task.tools = [_StubTool()]  # task.tools 有实例
        ctx = _make_ctx()
        result = run_async(agent.execute(task, ctx))
        # tool_calls 来自 task.tools
        assert result.tool_calls[0]["name"] == "stub_tool"


# =============================================================================
# 13. 角色 / agent_type 字段
# =============================================================================


class TestAgentType:
    """TaskResult.agent_type 取自 self.role (P1-A)."""

    def test_agent_type_uses_role_field(self):
        llm = MagicMock()
        llm.create_message.return_value = _make_llm_response(
            content='{"x": 1}', stop_reason="end_turn"
        )
        agent = _make_agent(llm=llm, role="architect")
        task = _make_task()
        ctx = _make_ctx()
        result = run_async(agent.execute(task, ctx))
        assert result.agent_type == "architect"

    def test_agent_type_default_role(self):
        llm = MagicMock()
        llm.create_message.return_value = _make_llm_response(
            content='{"x": 1}', stop_reason="end_turn"
        )
        agent = _make_agent(llm=llm)  # role 默认 "BaseAgent"
        task = _make_task()
        ctx = _make_ctx()
        result = run_async(agent.execute(task, ctx))
        assert result.agent_type == "BaseAgent"


# =============================================================================
# 14. raw_response 透传
# =============================================================================


class TestRawResponse:
    """TaskResult.raw_response 是 LLMResponse 引用."""

    def test_raw_response_set_from_llm(self):
        llm = MagicMock()
        expected = _make_llm_response(content='{"x": 1}', stop_reason="end_turn")
        llm.create_message.return_value = expected
        agent = _make_agent(llm=llm)
        task = _make_task()
        ctx = _make_ctx()
        result = run_async(agent.execute(task, ctx))
        assert result.raw_response is expected
