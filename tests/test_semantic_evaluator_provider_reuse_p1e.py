"""P1-E: ClaudeSemanticEvaluator 复用 AnthropicProvider (避免每轮 new instance).

设计动机: _call_claude 每次 new AnthropicProvider → SDK client 每次重连.
  fix: __post_init__ 中预创建 self._provider, 多次 __call__ 复用.

TDD: RED → GREEN.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

# 复用现有 helpers
from .test_loop_semantic_evaluator import _make_mock_response, _make_round_result_with_history


def asyncio_run(coro):
    """同步运行 coroutine."""
    return asyncio.run(coro)


class TestClaudeSemanticEvaluatorProviderReuse:
    """P1-E: 同一 evaluator 多次 __call__ 复用同一 provider 实例."""

    def test_provider_instance_reused_across_calls(self) -> None:
        """连续 3 次 __call__, AnthropicProvider 构造次数应 = 1 (不是 3)."""
        from auto_engineering.loop.semantic_evaluator import ClaudeSemanticEvaluator

        mock_response = _make_mock_response('{"satisfied": true, "reason": "ok"}')

        with patch(
            "auto_engineering.loop.semantic_evaluator.AnthropicProvider"
        ) as MockProvider:
            mock_provider_instance = MagicMock()
            mock_provider_instance.create_message = MagicMock(
                return_value=mock_response
            )
            MockProvider.return_value = mock_provider_instance

            evaluator = ClaudeSemanticEvaluator(api_key="fake-key")
            rr = _make_round_result_with_history()

            for _ in range(3):
                asyncio_run(evaluator(rr))

            # AnthropicProvider 应只在 __post_init__ 中实例化 1 次
            # 不是每次 _call_claude 都 new 一个
            assert MockProvider.call_count == 1, (
                f"AnthropicProvider 应复用, call_count 应 = 1, 实际: {MockProvider.call_count}"
            )

    def test_provider_created_in_post_init(self) -> None:
        """__post_init__ 中应预创建 provider (不依赖每次 _call_claude 创建)."""
        from auto_engineering.loop.semantic_evaluator import ClaudeSemanticEvaluator

        with patch(
            "auto_engineering.loop.semantic_evaluator.AnthropicProvider"
        ) as MockProvider:
            mock_provider_instance = MagicMock()
            MockProvider.return_value = mock_provider_instance

            # 构造时 (无 __call__) 应已创建 provider
            _ = ClaudeSemanticEvaluator(api_key="test-key")

            # AnthropicProvider 应在 __post_init__ 中被调用 (实例化)
            assert MockProvider.called, (
                "AnthropicProvider 应在 __post_init__ 中实例化, 而不是 lazy 创建"
            )
