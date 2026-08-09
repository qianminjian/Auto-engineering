"""Phase 80 T407：显式领域事件 Reducer 与 legacy replay。"""

from __future__ import annotations

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.reducers import (
    EventChannelViolation,
    ReducerRegistry,
    default_reducer_registry,
)


def _event(event_type: LoopEventType, payload: dict[str, object]) -> LoopEvent:
    return LoopEvent.create(
        thread_id="thread-1",
        sequence=1,
        event_type=event_type,
        payload=payload,
        correlation_id="thread-1",
    )


def test_stage_advanced_reducer_changes_only_stage() -> None:
    state = EngineState(thread_id="thread-1", current_stage="architect", tick=3)
    registry = default_reducer_registry()

    reduced = registry.reduce(
        state,
        _event(LoopEventType.STAGE_ADVANCED, {"from": "architect", "to": "developer"}),
    )

    assert reduced.current_stage == "developer"
    assert reduced.tick == 3
    assert state.current_stage == "architect"


def test_stage_event_rejects_cross_channel_state_patch() -> None:
    registry = default_reducer_registry()

    with pytest.raises(EventChannelViolation, match="StageAdvanced"):
        registry.reduce(
            EngineState(thread_id="thread-1"),
            _event(
                LoopEventType.STAGE_ADVANCED,
                {"from": "architect", "to": "developer", "state_patch": {"tick": 9}},
            ),
        )


def test_runtime_revision_activation_is_explicit() -> None:
    pending = {
        "protocol_version": "1.1",
        "event_schema_version": "1.0",
        "projection_schema_version": "1.0",
        "action_contract_version": "1.0",
        "prompt_revision": "new",
        "policy_revision": "policy",
        "engine_build_id": "rc.6",
    }
    state = EngineState(
        thread_id="thread-1",
        active_runtime_revision={**pending, "prompt_revision": "old"},
        pending_runtime_revision=pending,
    )

    reduced = default_reducer_registry().reduce(
        state,
        _event(
            LoopEventType.RUNTIME_REVISION_ACTIVATED,
            {"runtime_revision": pending},
        ),
    )

    assert reduced.active_runtime_revision == pending
    assert reduced.pending_runtime_revision is None


def test_legacy_result_patch_is_counted_and_replayed() -> None:
    registry = default_reducer_registry()
    state = EngineState(thread_id="thread-1", tick=1)

    reduced = registry.reduce(
        state,
        _event(LoopEventType.RESULT_ACCEPTED, {"state_patch": {"tick": 2}}),
    )

    assert reduced.tick == 2
    assert registry.legacy_patch_count == 1


def test_registry_rejects_duplicate_reducer_registration() -> None:
    registry = ReducerRegistry()
    registry.register(LoopEventType.STAGE_ADVANCED, lambda state, event: state)

    with pytest.raises(ValueError, match="重复"):
        registry.register(LoopEventType.STAGE_ADVANCED, lambda state, event: state)


def test_gap_event_cannot_modify_critic_channel() -> None:
    with pytest.raises(EventChannelViolation, match="越权修改"):
        default_reducer_registry().reduce(
            EngineState(thread_id="thread-1"),
            _event(
                LoopEventType.GAP_STATE_UPDATED,
                {"changes": {"open_findings": []}},
            ),
        )


def test_event_store_rejects_new_complete_state_patch() -> None:
    event = LoopEvent.create(
        thread_id="thread-1",
        sequence=0,
        event_type=LoopEventType.RESULT_ACCEPTED,
        payload={"state_patch": EngineState(thread_id="thread-1").to_dict()},
        causation_id="action-1",
        correlation_id="thread-1",
    )
    store = SQLiteEventStore(":memory:")

    with pytest.raises(ValueError, match="FULL_STATE_PATCH_FORBIDDEN"):
        store.append([event])
