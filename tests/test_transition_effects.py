"""Phase 80 T409：领域事实的生命周期 Effect 执行边界。"""

from __future__ import annotations

from unittest.mock import Mock

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.transition_effects import TransitionEffectExecutor


def _event(event_type: LoopEventType, payload: dict | None = None) -> LoopEvent:
    return LoopEvent.create(
        thread_id="thread-1",
        sequence=1,
        event_type=event_type,
        payload=payload or {},
        correlation_id="thread-1",
    )


def _batch_state() -> BatchState:
    return BatchState.from_batch_plan([
        {"batch_id": "B1", "component": "Core", "tasks": []},
        {"batch_id": "B2", "component": "Core", "tasks": []},
    ])


def test_pre_progress_effects_do_not_advance_cursor() -> None:
    batch_state = _batch_state()
    activate = Mock()
    critic = Mock()
    executor = TransitionEffectExecutor(batch_state, activate, critic)

    executor.apply_pre_progress((
        _event(LoopEventType.ARCHITECTURE_PLAN_ACTIVATED),
        _event(LoopEventType.CRITIC_PROGRESS_RECORDED, {"verdict": "MAJOR"}),
        _event(LoopEventType.BATCH_COMPLETED),
    ))

    activate.assert_called_once_with()
    critic.assert_called_once_with("MAJOR")
    assert batch_state.current_batch_idx == 0


def test_post_progress_effects_apply_semantic_cursor_facts() -> None:
    batch_state = _batch_state()
    executor = TransitionEffectExecutor(batch_state, Mock(), Mock())

    executor.apply_post_progress((_event(LoopEventType.BATCH_COMPLETED),))
    assert batch_state.current_batch_idx == 1

    executor.apply_post_progress((_event(LoopEventType.WORK_REOPENED),))
    assert batch_state.current_batch_idx == 0


def test_developer_progress_is_applied_outside_orchestrator() -> None:
    batch_state = _batch_state()
    node = Mock(done_tasks=2, current_task=None, id="node-1")
    progress_tree = Mock()
    progress_tree.find_by_design_section.return_value = node
    executor = TransitionEffectExecutor(
        batch_state,
        Mock(),
        Mock(),
        progress_tree,
    )

    executor.apply_developer_progress({
        "design_section": "§1",
        "completed_task_count": 3,
        "next_task": "T2",
    })

    assert node.done_tasks == 5
    assert node.current_task == "T2"
    progress_tree.recalculate_parents.assert_called_once_with("node-1")


def test_component_verification_progress_is_applied_outside_orchestrator() -> None:
    component = Mock(design_section="§1")
    batch_state = Mock()
    batch_state.current_component.return_value = component
    node = Mock(
        verifier_status="pending",
        verifier_missing=0,
        verifier_diverged=0,
        id="node-1",
    )
    progress_tree = Mock()
    progress_tree.find_by_design_section.return_value = node
    executor = TransitionEffectExecutor(
        batch_state,
        Mock(),
        Mock(),
        progress_tree,
    )

    executor.apply_verification_progress({
        "kind": "component_verifier",
        "missing": 1,
        "diverged": 2,
    })

    assert node.verifier_status == "failed"
    assert node.verifier_missing == 1
    assert node.verifier_diverged == 2
    progress_tree.recalculate_parents.assert_called_once_with("node-1")
