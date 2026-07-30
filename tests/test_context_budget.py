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
    max_session_ticks=30,
    max_session_wall_seconds=3600,
    soft_input_units=600,
    hard_input_units=700,
    max_prompt_bytes=1000,
)


def test_below_budget_continues() -> None:
    assert evaluate_budget(
        POLICY,
        ContextUsage(ticks=10, wall_seconds=100, input_units=500, prompt_bytes=500),
    ).decision is BudgetDecision.CONTINUE


def test_soft_and_hard_limits_rollover() -> None:
    soft = evaluate_budget(
        POLICY,
        ContextUsage(ticks=10, wall_seconds=100, input_units=600, prompt_bytes=500),
    )
    hard = evaluate_budget(
        POLICY,
        ContextUsage(ticks=10, wall_seconds=100, input_units=700, prompt_bytes=500),
    )

    assert soft.decision is BudgetDecision.ROLLOVER
    assert soft.reason == "context_soft_limit"
    assert hard.decision is BudgetDecision.ROLLOVER
    assert hard.reason == "context_hard_limit"


def test_single_prompt_over_limit_fails_instead_of_truncating() -> None:
    outcome = evaluate_budget(
        POLICY,
        ContextUsage(ticks=1, wall_seconds=1, input_units=1, prompt_bytes=1001),
    )

    assert outcome.decision is BudgetDecision.REJECT
    assert outcome.error_code == "ACTION_CONTEXT_TOO_LARGE"


def test_unknown_input_uses_tick_and_byte_limits() -> None:
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

    assert outcome.decision is BudgetDecision.ROLLOVER
    assert outcome.reason == "tick_limit"


def test_runtime_config_builds_policy_from_manifest_defaults() -> None:
    policy = RuntimeConfig(environ={}).context_budget_policy

    assert policy.policy_id == "context-budget-v1"
    assert policy.max_session_ticks == 50
    assert policy.max_session_wall_seconds == 3600
    assert policy.soft_input_units == 600_000
    assert policy.hard_input_units == 700_000
    assert policy.max_prompt_bytes == 200_000


def test_runtime_config_allows_host_profile_overrides() -> None:
    policy = RuntimeConfig(environ={
        "AE_SESSION_MAX_TICKS": "12",
        "AE_SESSION_MAX_SECONDS": "900",
        "AE_CONTEXT_SOFT_INPUT": "1000",
        "AE_CONTEXT_HARD_INPUT": "1200",
        "AE_MAX_PROMPT_BYTES": "4096",
    }).context_budget_policy

    assert policy.max_session_ticks == 12
    assert policy.max_session_wall_seconds == 900
    assert policy.soft_input_units == 1000
    assert policy.hard_input_units == 1200
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


def test_tick_kernel_emits_rollover_instead_of_next_work_action() -> None:
    config = RuntimeConfig(environ={
        "AE_SESSION_MAX_TICKS": "1",
        "AE_SESSION_MAX_SECONDS": "3600",
        "AE_CONTEXT_SOFT_INPUT": "600000",
        "AE_CONTEXT_HARD_INPUT": "700000",
        "AE_MAX_PROMPT_BYTES": "200000",
    })
    orchestrator = _orchestrator(config)
    orchestrator.init("实现功能")
    orchestrator._state.tick = 1

    action = orchestrator.build_action()

    assert action["action"] == "session_rollover"
    assert action["reason"] == "tick_limit"
    assert action["capsule"]["schema_version"] == "1.0"


def test_tick_kernel_rejects_oversized_candidate_without_truncation() -> None:
    config = RuntimeConfig(environ={
        "AE_SESSION_MAX_TICKS": "50",
        "AE_SESSION_MAX_SECONDS": "3600",
        "AE_CONTEXT_SOFT_INPUT": "600000",
        "AE_CONTEXT_HARD_INPUT": "700000",
        "AE_MAX_PROMPT_BYTES": "10",
    })

    action = _orchestrator(config).init("实现功能")

    assert action["action"] == "error"
    assert action["error_code"] == "ACTION_CONTEXT_TOO_LARGE"


def test_claim_result_restores_original_active_action() -> None:
    config = RuntimeConfig(environ={
        "AE_SESSION_MAX_TICKS": "1",
        "AE_SESSION_MAX_SECONDS": "3600",
        "AE_CONTEXT_SOFT_INPUT": "600000",
        "AE_CONTEXT_HARD_INPUT": "700000",
        "AE_MAX_PROMPT_BYTES": "200000",
    })
    orchestrator = _orchestrator(config)
    orchestrator.init("实现功能")
    orchestrator._state.tick = 1
    rollover = orchestrator.build_action()

    restored = orchestrator.tick_dict({
        "schema_version": "1.1",
        "message_type": "result",
        "message_id": "claim-result-1",
        "thread_id": rollover["thread_id"],
        "tick": rollover["tick"],
        "stage": "session_claimed",
        "causation_id": rollover["message_id"],
        "correlation_id": rollover["thread_id"],
        "extensions": {},
        "claim_token": rollover["claim_token"],
        "session_id": "session-2",
        "host": "codex",
    })

    assert restored["action"] == "architect"
    assert orchestrator._state.execution_session_id == "session-2"
