"""v2.3 Phase J 测试 — ClaudeSemanticEvaluator (P1.6 FINAL).

设计来源:
    - Phase 1 审计 P1.6: Phase B 实现 Orchestrator 接受
      semantic_evaluator: Callable[[RoundResult], Awaitable[bool]],
      但生产环境无内置 LLM evaluator, 用户需自己写. 第 4 级语义
      收敛永远不触发.
    - v2.3 Phase J: 内置 ClaudeSemanticEvaluator, 接 Claude API
      真判"本轮产出满足需求". OrchestratorConfig 默认配置
      (有 API key 时).
    - 借鉴 LangGraph ConditionalEdge: LLM 评估下一步路由.

测试覆盖 (TDD 强制 RED→GREEN→REFACTOR):
    A. 无 API key → True (不阻止)  (≥1 用例)
    B. mock Claude API 返回 {"satisfied": True} → 评估器返回 True  (≥1 用例)
    C. mock Claude API 返回 invalid JSON → 评估器返回 False (保守)  (≥1 用例)
    D. OrchestratorConfig 默认启用 ClaudeSemanticEvaluator (有 API key 时)  (≥1 用例)
    合计: ≥4 用例

测试约束 (遵循 pytest-memory-management.md):
    - 单文件 pytest --no-cov --timeout=60
    - mock Claude API (不真调), 验证真逻辑
    - 跑完清理 .pytest_cache
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

# ============================================================
# Fixtures + helpers
# ============================================================


class _FakeTextBlock:
    """模拟 Anthropic SDK 返回的 text block."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.type = "text"


class _FakeContentList:
    """模拟 response.content 列表 (可索引)."""

    def __init__(self, text: str) -> None:
        self._text = text

    def __getitem__(self, idx: int) -> _FakeTextBlock:
        return _FakeTextBlock(self._text)

    def __bool__(self) -> bool:
        return bool(self._text)


def _make_mock_response(text: str) -> MagicMock:
    """构造 mock 的 AnthropicProvider.create_message 返回值.

    Args:
        text: 模拟 LLM 返回的文本内容 (JSON 字符串或 invalid)
    """
    response = MagicMock()
    response.content = _FakeContentList(text)
    return response


def _make_round_result_with_history(
    gate_results: dict | None = None,
    outcomes: list | None = None,
) -> RoundResult:
    """构造一个带 history 的 RoundResult (供 evaluator 调用)."""
    from auto_engineering.loop.convergence import RoundHistory
    from auto_engineering.loop.round import RoundResult, TaskOutcome

    history = RoundHistory(
        round_id=1,
        files_changed=1,
        lines_added=10,
        lines_removed=2,
        gate_results=gate_results or {},
        semantic_satisfied=None,
        tasks_run=["t1"],
        task_outcomes={"t1": "completed"},
    )
    return RoundResult(
        round_id=1,
        outcomes=outcomes or [TaskOutcome(task_id="t1", status="completed")],
        history=[history],
    )


if TYPE_CHECKING:
    from auto_engineering.loop.round import RoundResult


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch):
    """测试前清空 ANTHROPIC_API_KEY, 保证从干净状态开始."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return monkeypatch


# ============================================================
# A. 无 API key 行为
# ============================================================


class TestClaudeSemanticEvaluatorNoApiKey:
    """无 ANTHROPIC_API_KEY 时, evaluator 必须返回 True (不阻止).

    设计理由: 无 API key → 不调 Claude → 默认 True, 让其他 Gate
    决定是否停止. 这是 graceful degradation 行为.
    """

    def test_no_api_key_returns_true(self, clean_env: pytest.MonkeyPatch) -> None:
        """RED: 无 ANTHROPIC_API_KEY 时, evaluator(RoundResult) → True."""
        from auto_engineering.loop.semantic_evaluator import ClaudeSemanticEvaluator

        evaluator = ClaudeSemanticEvaluator()
        # 即使构造时不传 api_key, 也未设置环境变量 → 应默认 True
        rr = _make_round_result_with_history()

        result = asyncio_run(evaluator(rr))
        assert result is True, (
            f"无 API key 应返回 True (不阻止), 实际: {result}"
        )

    def test_empty_api_key_string_falls_back_to_env(
        self, clean_env: pytest.MonkeyPatch
    ) -> None:
        """RED: 显式传 api_key="" 时, 应回退到环境变量 (无 → True)."""
        from auto_engineering.loop.semantic_evaluator import ClaudeSemanticEvaluator

        evaluator = ClaudeSemanticEvaluator(api_key="")
        rr = _make_round_result_with_history()

        result = asyncio_run(evaluator(rr))
        assert result is True, f"空 api_key 应回退到环境变量, 实际: {result}"


# ============================================================
# B. mock Claude API 返回 satisfied=True
# ============================================================


class TestClaudeSemanticEvaluatorParsesSatisfiedJson:
    """mock Claude API 返回有效 JSON, 验证解析逻辑."""

    def test_satisfied_true_returns_true(self) -> None:
        """RED: mock Claude 返回 {"satisfied": true, "reason": "ok"} → True."""
        from auto_engineering.loop.semantic_evaluator import ClaudeSemanticEvaluator

        mock_response = _make_mock_response(
            '{"satisfied": true, "reason": "all gates passed"}'
        )

        with patch(
            "auto_engineering.loop.semantic_evaluator.AnthropicProvider"
        ) as MockProvider:
            mock_provider_instance = MagicMock()
            # 同步 mock: create_message 实际是 sync 方法, 包在 to_thread 里调用
            mock_provider_instance.create_message = MagicMock(
                return_value=mock_response
            )
            MockProvider.return_value = mock_provider_instance

            evaluator = ClaudeSemanticEvaluator(api_key="fake-key-for-test")
            rr = _make_round_result_with_history()

            result = asyncio_run(evaluator(rr))
            assert result is True, f"满意 JSON 应返回 True, 实际: {result}"

    def test_satisfied_false_returns_false(self) -> None:
        """RED: mock Claude 返回 {"satisfied": false} → False."""
        from auto_engineering.loop.semantic_evaluator import ClaudeSemanticEvaluator

        mock_response = _make_mock_response(
            '{"satisfied": false, "reason": "task not done"}'
        )

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

            result = asyncio_run(evaluator(rr))
            assert result is False, f"不满意 JSON 应返回 False, 实际: {result}"


# ============================================================
# C. mock Claude API 返回 invalid JSON
# ============================================================


class TestClaudeSemanticEvaluatorInvalidJson:
    """mock Claude API 返回 invalid JSON, 应保守返回 False."""

    def test_invalid_json_returns_false(self) -> None:
        """RED: mock Claude 返回非 JSON 文本 → False (保守, 不阻止评估)."""
        from auto_engineering.loop.semantic_evaluator import ClaudeSemanticEvaluator

        mock_response = _make_mock_response(
            "Sorry, I cannot evaluate this."
        )

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

            result = asyncio_run(evaluator(rr))
            assert result is False, f"invalid JSON 应返回 False (保守), 实际: {result}"

    def test_partial_json_returns_false(self) -> None:
        """RED: mock Claude 返回缺字段的 JSON → False."""
        from auto_engineering.loop.semantic_evaluator import ClaudeSemanticEvaluator

        mock_response = _make_mock_response('{"reason": "ok"}')  # 缺 satisfied

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

            result = asyncio_run(evaluator(rr))
            assert result is False, f"缺字段 JSON 应返回 False, 实际: {result}"


# ============================================================
# D. OrchestratorConfig 默认启用 ClaudeSemanticEvaluator
# ============================================================


class TestOrchestratorConfigDefaultEvaluator:
    """OrchestratorConfig 默认行为: 有 ANTHROPIC_API_KEY → 自动用 ClaudeSemanticEvaluator."""

    def test_default_with_api_key_enables_claude_evaluator(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RED: 设 ANTHROPIC_API_KEY → 启用 ClaudeSemanticEvaluator."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-from-env")

        from auto_engineering.loop.orchestrator import OrchestratorConfig
        from auto_engineering.loop.semantic_evaluator import (
            ClaudeSemanticEvaluator,
        )

        config = OrchestratorConfig()
        assert config.semantic_evaluator is not None, (
            "有 API key 时 semantic_evaluator 应自动启用"
        )
        assert isinstance(config.semantic_evaluator, ClaudeSemanticEvaluator), (
            f"应是 ClaudeSemanticEvaluator 实例, 实际: "
            f"{type(config.semantic_evaluator).__name__}"
        )

    def test_default_without_api_key_keeps_none(
        self, clean_env: pytest.MonkeyPatch
    ) -> None:
        """RED: 无 ANTHROPIC_API_KEY → semantic_evaluator 仍为 None."""
        from auto_engineering.loop.orchestrator import OrchestratorConfig

        config = OrchestratorConfig()
        assert config.semantic_evaluator is None, (
            "无 API key 时 semantic_evaluator 应保持 None"
        )

    def test_explicit_evaluator_not_overridden(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RED: 用户显式传 semantic_evaluator → 不被默认覆盖."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-from-env")

        from auto_engineering.loop.orchestrator import OrchestratorConfig

        async def custom_evaluator(round_result):
            return True

        config = OrchestratorConfig(semantic_evaluator=custom_evaluator)
        assert config.semantic_evaluator is custom_evaluator, (
            "用户显式传值不应被默认覆盖"
        )


class TestOrchestratorConfigLLMAgentSkip:
    """OrchestratorConfig 在 LLM agent 上下文 (CLAUDE_CODE=1) 中跳过自动启用.

    借鉴 settings.py:49-50 + environment.py:211 同模式 (commit 7f12a70/fae3255).
    目的: 避免 Claude Code 自身运行 dev-loop 时调用 Claude API 自评估
    (浪费 budget + 产生自循环噪声).
    """

    def test_claude_code_set_with_api_key_keeps_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLAUDE_CODE=1 + ANTHROPIC_API_KEY → 不自动启用 (避免自调)."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-from-env")
        monkeypatch.setenv("CLAUDE_CODE", "1")

        from auto_engineering.loop.orchestrator import OrchestratorConfig

        config = OrchestratorConfig()
        assert config.semantic_evaluator is None, (
            "CLAUDE_CODE=1 时不应自动启用 ClaudeSemanticEvaluator "
            "(避免 Claude Code 自调 Claude 评估, 镜像 settings.py:49-50)"
        )

    def test_claude_code_unset_with_api_key_enables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLAUDE_CODE 未设 + ANTHROPIC_API_KEY → 自动启用 (非 LLM agent)."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-from-env")
        monkeypatch.delenv("CLAUDE_CODE", raising=False)

        from auto_engineering.loop.orchestrator import OrchestratorConfig
        from auto_engineering.loop.semantic_evaluator import (
            ClaudeSemanticEvaluator,
        )

        config = OrchestratorConfig()
        assert isinstance(config.semantic_evaluator, ClaudeSemanticEvaluator), (
            "CLAUDE_CODE 未设时仍应自动启用 (镜像 settings.py 默认行为)"
        )

    def test_claude_code_set_without_api_key_keeps_none(
        self, clean_env: pytest.MonkeyPatch
    ) -> None:
        """CLAUDE_CODE=1 + 无 ANTHROPIC_API_KEY → 仍为 None (graceful)."""
        monkeypatch = clean_env
        monkeypatch.setenv("CLAUDE_CODE", "1")

        from auto_engineering.loop.orchestrator import OrchestratorConfig

        config = OrchestratorConfig()
        assert config.semantic_evaluator is None, (
            "无 API key + LLM agent → 保持 None (graceful degradation)"
        )

    def test_explicit_evaluator_in_llm_agent_not_overridden(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLAUDE_CODE=1 + 用户显式传 semantic_evaluator → 用户值保留."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-from-env")
        monkeypatch.setenv("CLAUDE_CODE", "1")

        from auto_engineering.loop.orchestrator import OrchestratorConfig

        async def custom_evaluator(round_result):
            return True

        config = OrchestratorConfig(semantic_evaluator=custom_evaluator)
        assert config.semantic_evaluator is custom_evaluator, (
            "用户显式传值在 LLM agent 中也不应被覆盖"
        )


# ============================================================
# 辅助: 同步跑 async 函数 (pytest-asyncio 风格)
# ============================================================


def asyncio_run(coro):
    """同步运行 coroutine — 避免引入 pytest-asyncio 标记污染."""
    import asyncio

    return asyncio.run(coro)
