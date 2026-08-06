"""Phase 53 T249：由事件重放 EngineState 投影。"""

from __future__ import annotations

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.projector import EngineStateProjector, ProjectionError


def _event(
    sequence: int,
    event_type: LoopEventType,
    payload: dict[str, object],
) -> LoopEvent:
    return LoopEvent.create(
        thread_id="thread-1",
        sequence=sequence,
        event_type=event_type,
        payload=payload,
        correlation_id="thread-1",
        causation_id="action-1" if event_type is LoopEventType.RESULT_ACCEPTED else None,
    )


def test_replay_rebuilds_semantically_equivalent_engine_state() -> None:
    initial = EngineState(
        thread_id="thread-1",
        requirement="构建确定性内核",
        current_stage="gap_scan",
    )
    events = [
        _event(
            0,
            LoopEventType.LOOP_INITIALIZED,
            {"state": initial.to_dict()},
        ),
        _event(
            1,
            LoopEventType.RESULT_ACCEPTED,
            {
                "result_message_id": "result-1",
                "state_patch": {
                    "tick": 1,
                    "round": 1,
                    "current_stage": "architect",
                    "files_changed": ["auto_engineering/loop/events.py"],
                },
            },
        ),
        _event(
            2,
            LoopEventType.STAGE_ADVANCED,
            {"from": "architect", "to": "developer"},
        ),
    ]

    state = EngineStateProjector().replay(events)

    assert state.to_dict() == {
        **initial.to_dict(),
        "tick": 1,
        "round": 1,
        "current_stage": "developer",
        "files_changed": ["auto_engineering/loop/events.py"],
    }


def test_projector_is_pure_and_does_not_mutate_event_payload() -> None:
    event = _event(
        0,
        LoopEventType.LOOP_INITIALIZED,
        {"state": EngineState(thread_id="thread-1").to_dict()},
    )
    before = event.to_dict()
    projector = EngineStateProjector()

    first = projector.replay([event])
    first.requirement = "本地修改"
    second = projector.replay([event])

    assert second.requirement == ""
    assert event.to_dict() == before


def test_replay_requires_initial_state_event() -> None:
    with pytest.raises(ProjectionError, match="初始化"):
        EngineStateProjector().replay(
            [_event(0, LoopEventType.ACTION_ISSUED, {"action": {"message_id": "a1"}})]
        )


def test_replay_rejects_non_contiguous_or_mixed_stream() -> None:
    initial = EngineState(thread_id="thread-1")
    first = _event(0, LoopEventType.LOOP_INITIALIZED, {"state": initial.to_dict()})
    gap = _event(2, LoopEventType.LOOP_COMPLETED, {"verdict": "APPROVE"})

    with pytest.raises(ProjectionError, match="连续"):
        EngineStateProjector().replay([first, gap])

    other_thread = LoopEvent.create(
        thread_id="thread-2",
        sequence=1,
        event_type=LoopEventType.LOOP_COMPLETED,
        payload={},
        correlation_id="thread-2",
    )
    with pytest.raises(ProjectionError, match="同一 thread"):
        EngineStateProjector().replay([first, other_thread])


def test_checkpoint_import_can_seed_projection() -> None:
    state = EngineState(thread_id="thread-1", current_stage="critic", tick=9)
    event = _event(
        0,
        LoopEventType.CHECKPOINT_IMPORTED,
        {"checkpoint_id": "cp-1", "state": state.to_dict()},
    )

    assert EngineStateProjector().replay([event]).to_dict() == state.to_dict()


def test_architecture_baseline_event_rebuilds_persistent_projection() -> None:
    initial = EngineState(thread_id="thread-1", current_stage="architect")
    baseline = {
        "schema_version": "1.0",
        "baseline_id": "a" * 64,
        "revision": 1,
        "batch_plan": [],
        "contracts": {},
        "obligations": [],
    }

    state = EngineStateProjector().replay([
        _event(0, LoopEventType.LOOP_INITIALIZED, {"state": initial.to_dict()}),
        _event(
            1,
            LoopEventType.ARCHITECTURE_BASELINE_ACCEPTED,
            {"baseline": baseline},
        ),
    ])

    assert state.architecture_baseline == baseline
