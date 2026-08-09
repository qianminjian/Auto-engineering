"""Phase 54 T258：Developer Handler 决策矩阵。"""

from __future__ import annotations

from auto_engineering.loop.events import LoopEventType
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
    assert decision.events[0].event_type is LoopEventType.BATCH_COMPLETED
    assert decision.lifecycle_effects.save_checkpoint is True
    assert not {
        "collect_token_usage",
        "completed_batch_id",
        "snapshot_developer_output",
        "save_checkpoint",
        "offload_stage",
    } & decision.action_context.keys()
    assert decision.action_context["pre_gate"] == gate
    assert decision.lifecycle_effects.developer_progress["next_task"] == "实现 B2"
    assert "developer_progress" not in decision.action_context


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
    assert decision.lifecycle_effects.snapshot_developer_output is True
    assert decision.lifecycle_effects.save_checkpoint is False


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
    assert decision.advance_stage is False
    assert "stay_in_stage" not in decision.action_context
    assert all(
        event.event_type is not LoopEventType.BATCH_COMPLETED
        for event in decision.events
    )
    assert decision.action_context["feedback"] == {
        "reason": "required_gate_failed",
        "gates": [failure],
    }


def test_orchestrator_dispatches_developer_via_registry(tmp_path) -> None:
    orchestrator = TickOrchestrator(tmp_path)

    assert orchestrator._stage_handlers.get("developer").stage == "developer"
    assert not hasattr(orchestrator, "_after_developer")
