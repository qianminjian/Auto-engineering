"""Phase 80 T407：显式领域事件 Reducer 与 legacy replay。"""

from __future__ import annotations

import json

import pytest

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.progress_tree import ProgressTree
from auto_engineering.engine.state import EngineState
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.kernel import FALLBACK_CHANNEL_EVENTS
from auto_engineering.loop.reducers import (
    EVENT_CHANNELS,
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


def test_stage_advanced_reducer_clears_source_stage_transient_fields() -> None:
    state = EngineState(
        thread_id="thread-1",
        current_stage="critic",
        tick=3,
        critic_verdict="MAJOR",
        findings=[{"severity": "P1"}],
        strengths=[{"description": "清晰"}],
        assessment="Needs rework",
    )
    registry = default_reducer_registry()

    reduced = registry.reduce(
        state,
        _event(LoopEventType.STAGE_ADVANCED, {"from": "critic", "to": "developer"}),
    )

    assert reduced.current_stage == "developer"
    assert reduced.tick == 3
    assert reduced.critic_verdict == ""
    assert reduced.findings == []
    assert reduced.strengths is None
    assert reduced.assessment is None
    assert state.current_stage == "critic"
    assert state.critic_verdict == "MAJOR"


def test_lifecycle_event_replays_architect_repair_counter() -> None:
    state = EngineState(thread_id="thread-1", current_stage="architect")

    reduced = default_reducer_registry().reduce(
        state,
        _event(
            LoopEventType.LIFECYCLE_STATE_UPDATED,
            {"changes": {
                "guardrail_retry_counters": {
                    "architect_result_validation": 1,
                },
            }},
        ),
    )

    assert reduced.guardrail_retry_counters == {
        "architect_result_validation": 1,
    }


def test_legacy_adapter_does_not_hide_other_stage_event_cross_channel_fields() -> None:
    registry = default_reducer_registry()

    with pytest.raises(EventChannelViolation, match="StageAdvanced"):
        registry.reduce(
            EngineState(thread_id="thread-1"),
            _event(
                LoopEventType.STAGE_ADVANCED,
                {
                    "from": "architect",
                    "to": "developer",
                    "state_patch": {"tick": 9},
                    "unexpected_channel": True,
                },
            ),
        )


def test_legacy_stage_event_applies_patch_before_advancing_stage() -> None:
    registry = default_reducer_registry()
    state = EngineState(
        thread_id="thread-1",
        current_stage="gap_review",
        pending_research_ids=["gap-1"],
    )

    reduced = registry.reduce(
        state,
        _event(
            LoopEventType.STAGE_ADVANCED,
            {
                "from": "gap_review",
                "to": "research",
                "state_patch": {
                    "pending_research_ids": [],
                    "research_archive": {"gap-1": {"status": "complete"}},
                },
            },
        ),
    )

    assert reduced.current_stage == "research"
    assert reduced.pending_research_ids == []
    assert reduced.research_archive == {"gap-1": {"status": "complete"}}
    assert registry.legacy_patch_count == 1


def test_event_store_rejects_new_stage_event_state_patch() -> None:
    store = SQLiteEventStore(":memory:")
    event = LoopEvent.create(
        thread_id="thread-1",
        sequence=0,
        event_type=LoopEventType.STAGE_ADVANCED,
        payload={
            "from": "architect",
            "to": "developer",
            "state_patch": {"tick": 9},
        },
        correlation_id="thread-1",
    )

    with pytest.raises(ValueError, match="NEW_STATE_PATCH_FORBIDDEN"):
        store.append([event])


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

    with pytest.raises(ValueError, match="NEW_STATE_PATCH_FORBIDDEN"):
        store.append([event])


def test_every_mutable_projection_channel_has_explicit_event_owner() -> None:
    initial_only = {
        "requirement",
        "thread_id",
            "design_doc_path",
            "design_doc_digest",
        "prompt_registry_hash",
        "debug_enabled",
        "debug_dir",
    }
    explicitly_owned = set().union(*EVENT_CHANNELS.values())
    serialized = set(EngineState(thread_id="thread-1").to_dict())

    assert serialized - initial_only <= explicitly_owned
    assert set(FALLBACK_CHANNEL_EVENTS) <= explicitly_owned


def test_batch_completed_reducer_updates_cursor_and_progress_by_stable_ids() -> None:
    batches = [
        {
            "batch_id": "B1",
            "component": "Core",
            "design_section": "§1",
            "tasks": [{"id": "B1-T1"}, {"id": "B1-T2"}],
        },
        {
            "batch_id": "B2",
            "component": "Core",
            "design_section": "§1",
            "tasks": [{"id": "B2-T1"}],
        },
    ]
    batch_state = BatchState.from_batch_plan(batches)
    progress = ProgressTree.from_batch_plan(batches, "Core")
    state = EngineState(
        thread_id="thread-1",
        batch_state_json=batch_state.to_json(),
        progress_tree_json=json.dumps(progress.to_dict()),
    )

    reduced = default_reducer_registry().reduce(
        state,
        _event(
            LoopEventType.BATCH_COMPLETED,
            {
                "batch_id": "B1",
                "task_ids": ["B1-T1", "B1-T2"],
                "completed_task_count": 2,
                "design_section": "§1",
                "progress_node_id": "§1",
                "next_task": "B2",
            },
        ),
    )

    restored_batch = BatchState.from_json(reduced.batch_state_json, None)
    restored_progress = ProgressTree.from_dict(
        json.loads(reduced.progress_tree_json)
    )
    assert restored_batch.current_batch_id() == "B2"
    assert restored_batch.completed_batch_ids() == {"B1"}
    assert restored_progress.nodes["§1"].done_tasks == 2
    assert restored_progress.nodes["§1"].current_task == "B2"


def test_batch_completed_reducer_rejects_task_identity_mismatch() -> None:
    batches = [{
        "batch_id": "B1",
        "component": "Core",
        "design_section": "§1",
        "tasks": [{"id": "B1-T1"}],
    }]
    state = EngineState(
        thread_id="thread-1",
        batch_state_json=BatchState.from_batch_plan(batches).to_json(),
        progress_tree_json=json.dumps(
            ProgressTree.from_batch_plan(batches, "Core").to_dict()
        ),
    )

    with pytest.raises(EventChannelViolation, match="TASK_IDENTITY_MISMATCH"):
        default_reducer_registry().reduce(
            state,
            _event(
                LoopEventType.BATCH_COMPLETED,
                {
                    "batch_id": "B1",
                    "task_ids": ["wrong"],
                    "completed_task_count": 1,
                    "design_section": "§1",
                    "progress_node_id": "§1",
                    "next_task": None,
                },
            ),
        )


def test_work_repair_completed_heals_cursor_without_recounting_progress() -> None:
    batches = [
        {"batch_id": "B1", "component": "Core", "design_section": "§1",
         "tasks": [{"id": "B1-T1"}]},
        {"batch_id": "B2", "component": "Core", "design_section": "§1",
         "tasks": [{"id": "B2-T1"}]},
    ]
    batch_state = BatchState.from_batch_plan(batches)
    batch_state.advance_batch()
    batch_state.advance_batch()
    batch_state.current_batch_idx = 0  # 模拟旧版连续返修把游标错误回退到 B1
    progress = ProgressTree.from_batch_plan(batches, "Core")
    progress.nodes["§1"].done_tasks = 2
    state = EngineState(
        thread_id="thread-1",
        batch_state_json=batch_state.to_json(),
        progress_tree_json=json.dumps(progress.to_dict()),
    )

    reduced = default_reducer_registry().reduce(
        state,
        _event(LoopEventType.WORK_REPAIR_COMPLETED, {"batch_id": "B1"}),
    )

    restored = BatchState.from_json(reduced.batch_state_json, None)
    restored_progress = ProgressTree.from_dict(json.loads(reduced.progress_tree_json))
    assert restored.is_component_complete()
    assert restored.completed_batch_ids() == {"B1", "B2"}
    assert restored_progress.nodes["§1"].done_tasks == 2
