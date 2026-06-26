"""P1.1 — cli.py TokenTracker 真接 dev_loop.

验收:
- ae dev-loop --max-tokens 100 "x" 超 100 token 后抛 BUDGET_EXCEEDED
- _run_v1_engine 接受 token_tracker 参数
- _execute_with_progress 收到非 None 的 token_tracker
- cli.py dev_loop 把 TokenTracker 传给 _run_v1_engine
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from auto_engineering.cli import (
    ProgressLogger,
    TokenTracker,
    _execute_with_progress,
    _run_v1_engine,
)
from auto_engineering.errors import AEError, ErrorCode
from auto_engineering.llm.anthropic_provider import LLMUsage


class TestTokenTrackerCLIWiring:
    """TokenTracker 在 CLI 调用链中的真接验证."""

    def test_run_v1_engine_accepts_token_tracker_param(self):
        """_run_v1_engine 接受 token_tracker 参数(签名验证)."""
        import inspect
        sig = inspect.signature(_run_v1_engine)
        assert "token_tracker" in sig.parameters

    def test_execute_with_progress_receives_token_tracker(self):
        """_execute_with_progress 收到非 None token_tracker 时传给 engine.run()."""
        mock_engine = MagicMock()
        # engine.run 是 async，所以 mock 也要是 async
        async def mock_run(*args, **kwargs):
            return MagicMock(status="done", total_steps=1, checkpoint_id="x")
        mock_engine.run = MagicMock(return_value=mock_run())

        tracker = TokenTracker(max_tokens=0)

        _execute_with_progress(
            engine=mock_engine,
            requirement="test",
            max_steps=1,
            cancellation=MagicMock(),
            progress=ProgressLogger(log_format="text"),
            max_tokens=0,
            token_tracker=tracker,
        )

        mock_engine.run.assert_called_once()
        call_kwargs = mock_engine.run.call_args.kwargs
        assert call_kwargs.get("token_tracker") is tracker

    def test_token_tracker_cli_accumulates_from_llm_response(self):
        """TokenTracker.add 累加 LLMResponse token,超阈值抛 AEError."""
        tracker = TokenTracker(max_tokens=100)

        response = MagicMock()
        response.usage = LLMUsage(input_tokens=80, output_tokens=30)  # total=110 > 100

        with pytest.raises(AEError) as exc_info:
            tracker.add(response)
        assert exc_info.value.code == ErrorCode.BUDGET_EXCEEDED

    def test_token_tracker_under_budget_no_raise(self):
        """TokenTracker 未超限额不抛异常."""
        tracker = TokenTracker(max_tokens=200)

        response = MagicMock()
        response.usage = LLMUsage(input_tokens=80, output_tokens=30)  # total=110 < 200

        tracker.add(response)  # 不抛
        assert tracker.total_tokens == 110

    def test_execute_with_progress_none_token_tracker_does_not_crash(self):
        """token_tracker=None 时 _execute_with_progress 正常返回."""
        mock_engine = MagicMock()

        async def mock_run(*args, **kwargs):
            return MagicMock(status="done", total_steps=1, checkpoint_id="x")
        mock_engine.run = MagicMock(return_value=mock_run())

        _execute_with_progress(
            engine=mock_engine,
            requirement="test",
            max_steps=1,
            cancellation=MagicMock(),
            progress=ProgressLogger(log_format="text"),
            max_tokens=0,
            token_tracker=None,
        )

        mock_engine.run.assert_called_once()
        # None 也传进去
        call_kwargs = mock_engine.run.call_args.kwargs
        assert call_kwargs.get("token_tracker") is None
