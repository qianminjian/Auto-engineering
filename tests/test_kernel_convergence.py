"""Phase 80 T409：TickKernel 固定提交流水线。"""

from __future__ import annotations

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.kernel import TickKernel


def _action(message_id: str, stage: str) -> dict[str, object]:
    return {
        "message_id": message_id,
        "thread_id": "thread-1",
        "stage": stage,
        "action": stage,
    }


def test_initial_commit_contains_seed_then_action() -> None:
    state = EngineState(thread_id="thread-1", current_stage="architect")

    candidate = TickKernel().compile_commit(
        next_sequence=0,
        previous_state=None,
        current_state=state,
        action=_action("action-1", "architect"),
        pending_events=(),
        result_message_id=None,
        result_causation_id=None,
    )

    assert [event.event_type for event in candidate.events] == [
        LoopEventType.LOOP_INITIALIZED,
        LoopEventType.ACTION_ISSUED,
    ]
    assert [event.sequence for event in candidate.events] == [0, 1]


def test_result_commit_uses_bounded_delta_and_preserves_domain_event_order() -> None:
    previous = EngineState(
        thread_id="thread-1",
        current_stage="architect",
        tick=1,
    )
    current = EngineState.from_dict({
        **previous.to_dict(),
        "current_stage": "developer",
        "tick": 2,
    })
    stage_event = LoopEvent.create(
        thread_id="thread-1",
        sequence=0,
        event_type=LoopEventType.STAGE_ADVANCED,
        payload={"from": "architect", "to": "developer"},
        correlation_id="thread-1",
    )

    candidate = TickKernel().compile_commit(
        next_sequence=2,
        previous_state=previous,
        current_state=current,
        action=_action("action-2", "developer"),
        pending_events=(stage_event,),
        result_message_id="result-1",
        result_causation_id="action-1",
    )

    assert [event.event_type for event in candidate.events] == [
        LoopEventType.RESULT_ACCEPTED,
        LoopEventType.LIFECYCLE_STATE_UPDATED,
        LoopEventType.STAGE_ADVANCED,
        LoopEventType.ACTION_ISSUED,
    ]
    delta = candidate.events[1].to_dict()["payload"]["changes"]
    assert delta == {"tick": 2}
    assert len(delta) < len(current.to_dict())


def test_new_tick_never_emits_compatibility_state_delta() -> None:
    previous = EngineState(thread_id="thread-1", tick=1)
    current = EngineState.from_dict({
        **previous.to_dict(),
        "tick": 2,
        "action_timestamp": 3.0,
        "files_changed": ["src/app.py"],
    })

    candidate = TickKernel().compile_commit(
        next_sequence=2,
        previous_state=previous,
        current_state=current,
        action=_action("action-2", "developer"),
        pending_events=(),
        result_message_id="result-1",
        result_causation_id="action-1",
    )

    assert LoopEventType.STATE_CHANNELS_CHANGED not in {
        event.event_type for event in candidate.events
    }
    assert {
        event.event_type for event in candidate.events
    } >= {
        LoopEventType.LIFECYCLE_STATE_UPDATED,
        LoopEventType.RESULT_EVIDENCE_RECORDED,
        LoopEventType.TELEMETRY_RECORDED,
    }
    assert [event.sequence for event in candidate.events] == [2, 3, 4, 5, 6]
