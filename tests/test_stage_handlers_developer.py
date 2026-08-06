"""Phase 54 T258：Developer Handler 决策矩阵。"""

from __future__ import annotations

from auto_engineering.loop.stages.base import TransitionContext
from auto_engineering.loop.stages.developer import DeveloperHandler
from auto_engineering.loop.tick_orchestrator import TickOrchestrator


def _context(**extensions: object) -> TransitionContext:
    return TransitionContext(
        thread_id="thread-1",
        tick=6,
        event_sequence=11,
        extensions=extensions,
    )


def test_developer_advances_to_next_batch_with_checkpoint() -> None:
    gate = {"name": "unit-tests"}
    decision = DeveloperHandler().apply(
        {},
        {},
        _context(
            has_more_batches_after_advance=True,
            completed_batch_id="B1",
            completed_task_count=2,
            design_section="§1",
            next_task="实现 B2",
            next_pre_gate=gate,
        ),
    )

    assert decision.next_stage == "developer"
    assert decision.action_context["cursor_operation"] == "advance_batch"
    assert decision.action_context["save_checkpoint"] is True
    assert decision.action_context["pre_gate"] == gate
    assert decision.action_context["developer_progress"]["next_task"] == "实现 B2"


def test_developer_component_completion_routes_to_critic() -> None:
    decision = DeveloperHandler().apply(
        {},
        {},
        _context(
            has_more_batches_after_advance=False,
            completed_batch_id="B1",
            completed_task_count=1,
            design_section="§1",
        ),
    )

    assert decision.next_stage == "critic"
    assert decision.action_context["snapshot_developer_output"] is True
    assert decision.action_context["save_checkpoint"] is False


def test_developer_required_gate_failure_stays_before_critic() -> None:
    """required Gate hard-fail 必须阻止 batch 完成和 Developer→Critic。"""
    failure = {
        "gate_name": "type_check",
        "status": "hard_fail",
        "passed": False,
        "message": "pnpm exec tsc 无法执行",
    }

    decision = DeveloperHandler().apply(
        {},
        {},
        _context(
            has_more_batches_after_advance=False,
            completed_batch_id="B1",
            completed_task_count=1,
            design_section="§1",
            blocking_gate_results=[failure],
        ),
    )

    assert decision.next_stage == "developer"
    assert decision.events == ()
    assert decision.action_context["stay_in_stage"] is True
    assert "cursor_operation" not in decision.action_context
    assert decision.action_context["feedback"] == {
        "reason": "required_gate_failed",
        "gates": [failure],
    }


def test_orchestrator_dispatches_developer_via_registry(tmp_path) -> None:
    orchestrator = TickOrchestrator(tmp_path)

    assert orchestrator._stage_handlers.get("developer").stage == "developer"
    assert not hasattr(orchestrator, "_after_developer")
