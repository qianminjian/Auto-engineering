"""P1.3 — BaseAgent LLM 错误分类测试.

直接测试 _map_llm_exception 方法。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from auto_engineering.agents.base import BaseAgent
from auto_engineering.engine.state import LoopState
from auto_engineering.errors import AEError, ErrorCode
from auto_engineering.llm.anthropic_provider import LLMResponse, LLMUsage
from auto_engineering.runtime.context import TaskContext
from auto_engineering.runtime.task import Task
from tests.conftest import run_async


class TestMapLLMException:
    """直接测试 _map_llm_exception 映射逻辑."""

    def _agent(self) -> BaseAgent:
        llm = MagicMock()
        llm.create_message.return_value = LLMResponse(
            content="{}",
            model="m",
            usage=LLMUsage(0, 0),
            stop_reason="end_turn",
        )
        return BaseAgent(llm=llm, system_prompt="test")

    def test_apitimeouterror_maps_to_llm_timeout(self):
        """APITimeoutError → LLM_TIMEOUT."""
        import anthropic
        exc = anthropic.APITimeoutError(request=object())
        ae = self._agent()._map_llm_exception(exc)
        assert ae.code == ErrorCode.LLM_TIMEOUT

    def test_apiconnectionerror_maps_to_llm_network_error(self):
        """APIConnectionError → LLM_NETWORK_ERROR."""
        import anthropic
        exc = anthropic.APIConnectionError(request=object())
        ae = self._agent()._map_llm_exception(exc)
        assert ae.code == ErrorCode.LLM_NETWORK_ERROR

    def test_apistatuserror_maps_to_llm_invalid_response(self):
        """APIStatusError → LLM_INVALID_RESPONSE."""
        import anthropic
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.request = object()
        exc = anthropic.APIStatusError(message="bad", response=mock_resp, body={})
        ae = self._agent()._map_llm_exception(exc)
        assert ae.code == ErrorCode.LLM_INVALID_RESPONSE

    def test_authenticationerror_maps_to_llm_auth_error(self):
        """AuthenticationError → LLM_AUTH_ERROR."""
        import anthropic
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.request = object()
        exc = anthropic.AuthenticationError(message="auth", response=mock_resp, body={})
        ae = self._agent()._map_llm_exception(exc)
        assert ae.code == ErrorCode.LLM_AUTH_ERROR

    def test_ratelimiterror_maps_to_llm_rate_limit(self):
        """RateLimitError → LLM_RATE_LIMIT."""
        import anthropic
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.request = object()
        exc = anthropic.RateLimitError(message="rate", response=mock_resp, body={})
        ae = self._agent()._map_llm_exception(exc)
        assert ae.code == ErrorCode.LLM_RATE_LIMIT

    def test_unknown_error_maps_to_llm_unknown_error(self):
        """RuntimeError → LLM_UNKNOWN_ERROR."""
        exc = RuntimeError("unexpected")
        ae = self._agent()._map_llm_exception(exc)
        assert ae.code == ErrorCode.LLM_UNKNOWN_ERROR


class TestExecuteWithLLMErrors:
    """execute 调用中 LLM 异常 → AEError 传播."""

    async def _execute(self, agent: BaseAgent):
        task = Task(id="t", description="x", expected_output="y", output_channels=["x"])
        ctx = TaskContext(state=LoopState(), requirement="r")
        return await agent.execute(task, ctx)

    def test_llm_timeout_propagates_aeerror(self):
        """APITimeoutError → AEError(LLM_TIMEOUT)."""
        import anthropic
        llm = MagicMock()
        llm.create_message = AsyncMock(
            side_effect=anthropic.APITimeoutError(request=object())
        )
        agent = BaseAgent(llm=llm, system_prompt="test")
        with pytest.raises(AEError) as ctx:
            run_async(self._execute(agent))
        assert ctx.value.code == ErrorCode.LLM_TIMEOUT

    def test_normal_response_no_error(self):
        """正常 LLM 返回 → TaskResult 无异常."""
        llm = MagicMock()
        llm.create_message = AsyncMock(
            return_value=LLMResponse(
                content='{"x": 1}',
                model="m",
                usage=LLMUsage(input_tokens=10, output_tokens=5),
                stop_reason="end_turn",
            )
        )
        agent = BaseAgent(llm=llm, system_prompt="test")
        result = run_async(self._execute(agent))
        assert result.values.get("x") == 1
