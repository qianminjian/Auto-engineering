"""Phase 54 T257：Architect 与 Critic Handler 决策矩阵。"""

from __future__ import annotations

from auto_engineering.loop.stages.base import TransitionContext
from auto_engineering.loop.stages.design import ArchitectHandler, CriticHandler
from auto_engineering.loop.tick_orchestrator import TickOrchestrator


def _context(**extensions: object) -> TransitionContext:
    return TransitionContext(
        thread_id="thread-1",
        tick=5,
        event_sequence=10,
        extensions=extensions,
    )


def test_architect_rejects_empty_batch_plan() -> None:
    decision = ArchitectHandler().apply(
        {"batch_plan": []},
        {},
        _context(),
    )

    assert decision.next_stage is None
    assert decision.action_context["error"]["error_code"] == "EMPTY_BATCH_PLAN"


def test_architect_initializes_plan_before_advancing() -> None:
    decision = ArchitectHandler().apply(
        {"batch_plan": [{"batch_id": "B1", "tasks": []}]},
        {},
        _context(),
    )

    assert decision.next_stage == "developer"
    assert decision.action_context["initialize_architecture"] is True
    assert decision.action_context["offload_stage"] == "architect"


def test_critic_rejects_unknown_verdict() -> None:
    decision = CriticHandler().apply({}, {"verdict": "MINOR"}, _context())

    assert decision.next_stage is None
    assert decision.action_context["error"]["error_code"] == "INVALID_VERDICT"


def test_critic_major_stops_at_projected_hard_limit() -> None:
    decision = CriticHandler().apply(
        {"majors_in_a_row": 2, "total_majors": 2},
        {"verdict": "MAJOR"},
        _context(max_majors_in_a_row=3, max_total_majors=4),
    )

    assert decision.terminal is True
    assert decision.action_context["terminal_action"]["verdict"] == "HARD_LIMIT"
    assert decision.action_context["state_patch"]["majors_in_a_row"] == 3


def test_critic_major_rolls_back_batch_and_returns_findings() -> None:
    findings = [{"severity": "P1", "description": "fix"}]
    decision = CriticHandler().apply(
        {"majors_in_a_row": 0, "total_majors": 0},
        {"verdict": "MAJOR", "findings": findings},
        _context(max_majors_in_a_row=3, max_total_majors=4),
    )

    assert decision.next_stage == "developer"
    assert decision.action_context["cursor_operation"] == "rollback_batch"
    assert decision.action_context["feedback"] == findings


def test_critic_approve_routes_by_remaining_batches() -> None:
    more = CriticHandler().apply(
        {"majors_in_a_row": 1, "total_majors": 2},
        {"verdict": "APPROVE"},
        _context(has_more_batches=True),
    )
    complete = CriticHandler().apply(
        {"majors_in_a_row": 1, "total_majors": 2},
        {"verdict": "APPROVE"},
        _context(has_more_batches=False),
    )

    assert more.next_stage == "developer"
    assert complete.next_stage == "component_verifier"
    assert more.action_context["state_patch"]["majors_in_a_row"] == 0
    assert more.action_context["state_patch"]["total_majors"] == 2


def test_orchestrator_dispatches_design_stages_via_registry(tmp_path) -> None:
    orchestrator = TickOrchestrator(tmp_path)

    assert orchestrator._stage_handlers.get("architect").stage == "architect"
    assert orchestrator._stage_handlers.get("critic").stage == "critic"
    assert not hasattr(orchestrator, "_after_architect")
    assert not hasattr(orchestrator, "_after_critic")
