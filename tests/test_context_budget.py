"""v5.8 T310：ContextBudget 确定性决策。"""

from unittest.mock import MagicMock

from auto_engineering.config.runtime_config import RuntimeConfig
from auto_engineering.loop.context_budget import (
    BudgetDecision,
    ContextBudgetPolicy,
    ContextUsage,
    evaluate_budget,
)
from auto_engineering.loop.guardrail import GuardrailChain
from auto_engineering.loop.tick_orchestrator import TickOrchestrator

POLICY = ContextBudgetPolicy(
    policy_id="test-v1",
    soft_input_units=600,
    hard_input_units=700,
    max_prompt_bytes=1000,
)


def test_below_budget_continues() -> None:
    assert evaluate_budget(
        POLICY,
        ContextUsage(ticks=10, wall_seconds=100, input_units=500, prompt_bytes=500),
    ).decision is BudgetDecision.CONTINUE


def test_host_usage_thresholds_do_not_trigger_rollover() -> None:
    soft = evaluate_budget(
        POLICY,
        ContextUsage(ticks=10, wall_seconds=100, input_units=600, prompt_bytes=500),
    )
    hard = evaluate_budget(
        POLICY,
        ContextUsage(ticks=10, wall_seconds=100, input_units=700, prompt_bytes=500),
    )

    assert soft.decision is BudgetDecision.CONTINUE
    assert hard.decision is BudgetDecision.CONTINUE


def test_single_prompt_over_limit_fails_instead_of_truncating() -> None:
    outcome = evaluate_budget(
        POLICY,
        ContextUsage(ticks=1, wall_seconds=1, input_units=1, prompt_bytes=1001),
    )

    assert outcome.decision is BudgetDecision.REJECT
    assert outcome.error_code == "ACTION_CONTEXT_TOO_LARGE"


def test_unknown_input_and_tick_count_do_not_trigger_rollover() -> None:
    outcome = evaluate_budget(
        POLICY,
        ContextUsage(
            ticks=30,
            wall_seconds=100,
            input_units=None,
            prompt_bytes=500,
            estimated=True,
        ),
    )

    assert outcome.decision is BudgetDecision.CONTINUE


def test_runtime_config_builds_policy_from_manifest_defaults() -> None:
    policy = RuntimeConfig(environ={}).context_budget_policy

    assert policy.policy_id == "context-budget-v2"
    assert policy.soft_input_units == 600_000
    assert policy.hard_input_units == 700_000
    assert policy.max_prompt_bytes == 200_000


def test_host_session_thresholds_are_not_runtime_configuration() -> None:
    policy = RuntimeConfig(environ={
        "AE_CONTEXT_SOFT_INPUT": "1000",
        "AE_CONTEXT_HARD_INPUT": "1200",
        "AE_MAX_PROMPT_BYTES": "4096",
    }).context_budget_policy

    assert policy.soft_input_units == 600_000
    assert policy.hard_input_units == 700_000
    assert policy.max_prompt_bytes == 4096


def _orchestrator(config: RuntimeConfig) -> TickOrchestrator:
    guardrail = MagicMock(spec=GuardrailChain)
    guardrail.check.return_value = MagicMock(action="pass")
    return TickOrchestrator(
        gate_runner=lambda names, root: {
            name: MagicMock(passed=True, message="ok") for name in names
        },
        guardrail=guardrail,
        runtime_config=config,
    )


def test_tick_kernel_does_not_rollover_at_fixed_tick_count() -> None:
    config = RuntimeConfig(environ={
        "AE_CONTEXT_SOFT_INPUT": "600000",
        "AE_CONTEXT_HARD_INPUT": "700000",
        "AE_MAX_PROMPT_BYTES": "200000",
    })
    orchestrator = _orchestrator(config)
    orchestrator.init("实现功能")
    orchestrator._state.tick = 1

    action = orchestrator.build_action()

    assert action["action"] == "architect"


def test_tick_orchestrator_production_default_has_no_round_cap() -> None:
    """固定 Round 上限只能是显式兼容配置，不能成为当前生产默认。"""

    orchestrator = _orchestrator(RuntimeConfig(environ={}))
    orchestrator.init("实现长流程功能")

    assert orchestrator._judge is not None
    assert orchestrator._judge.config.max_iterations is None


def test_tick_kernel_rejects_oversized_candidate_without_truncation() -> None:
    config = RuntimeConfig(environ={
        "AE_CONTEXT_SOFT_INPUT": "600000",
        "AE_CONTEXT_HARD_INPUT": "700000",
        "AE_MAX_PROMPT_BYTES": "10",
    })

    action = _orchestrator(config).init("实现功能")

    assert action["action"] == "error"
    assert action["error_code"] == "ACTION_CONTEXT_TOO_LARGE"


def test_build_action_converts_prompt_overflow_to_structured_error(tmp_path) -> None:
    """Prompt 编译超限必须返回协议错误，不能让 CLI 裸抛异常。"""
    orchestrator = TickOrchestrator(project_root=tmp_path)
    orchestrator.init("实现功能")
    assert orchestrator._state is not None
    orchestrator._state.current_stage = "developer"
    orchestrator._state.expected_stage = "developer"
    orchestrator._state.requirement = "x" * 70_000

    action = orchestrator.build_action()

    assert action["action"] == "error"
    assert action["error_code"] == "ACTION_CONTEXT_TOO_LARGE"


def test_cache_usage_does_not_change_context_decision() -> None:
    low = evaluate_budget(
        POLICY,
        ContextUsage(ticks=1, wall_seconds=1, input_units=1, prompt_bytes=100),
    )
    high = evaluate_budget(
        POLICY,
        ContextUsage(ticks=999, wall_seconds=99999, input_units=999999, prompt_bytes=100),
    )
    assert low == high
