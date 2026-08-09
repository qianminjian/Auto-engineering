from __future__ import annotations

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.reducers import default_reducer_registry


def _event(event_type: LoopEventType, changes: dict[str, object]) -> LoopEvent:
    return LoopEvent.create(
        thread_id="thread-old",
        sequence=1,
        event_type=event_type,
        payload={"changes": changes},
        correlation_id="thread-old",
        causation_id="gate-message",
    )


def test_conflict_and_user_selection_are_replayable() -> None:
    registry = default_reducer_registry()
    state = EngineState(thread_id="thread-old")
    conflict = {
        "status": "waiting_user",
        "gate_message_id": "gate-message",
        "reason_codes": ["project_anchors_missing"],
        "intent": {"design_doc_path": "design/current.md", "design_doc_digest": "abc"},
    }

    detected = registry.reduce(
        state,
        _event(
            LoopEventType.STATE_CONFLICT_DETECTED,
            {"state_reconciliation": conflict},
        ),
    )
    selected = registry.reduce(
        detected,
        _event(
            LoopEventType.STATE_RECONCILIATION_SELECTED,
            {"state_reconciliation": {**conflict, "status": "selected", "choice": "reinitialize"}},
        ),
    )

    assert state.state_reconciliation is None
    assert detected.state_reconciliation == conflict
    assert selected.state_reconciliation is not None
    assert selected.state_reconciliation["choice"] == "reinitialize"


def test_supersede_events_preserve_history_in_projection() -> None:
    registry = default_reducer_registry()
    state = EngineState(thread_id="thread-old")

    thread_closed = registry.reduce(
        state,
        _event(
            LoopEventType.THREAD_SUPERSEDED,
            {"thread_status": "superseded"},
        ),
    )
    task_closed = registry.reduce(
        thread_closed,
        _event(
            LoopEventType.TASK_SUPERSEDED,
            {"superseded_tasks": [{"task_id": "B2-T1", "reason": "project_changed"}]},
        ),
    )

    assert thread_closed.thread_status == "superseded"
    assert task_closed.superseded_tasks == [
        {"task_id": "B2-T1", "reason": "project_changed"}
    ]


def test_plan_reconciled_records_revision_mapping() -> None:
    state = default_reducer_registry().reduce(
        EngineState(thread_id="thread-old"),
        _event(
            LoopEventType.PLAN_RECONCILED,
            {
                "plan_reconciliation": {
                    "source_revision": 2,
                    "current_revision": 3,
                    "verified_completed": 5,
                    "superseded": 4,
                    "unverifiable": 2,
                }
            },
        ),
    )

    assert state.plan_reconciliation == {
        "source_revision": 2,
        "current_revision": 3,
        "verified_completed": 5,
        "superseded": 4,
        "unverifiable": 2,
    }
