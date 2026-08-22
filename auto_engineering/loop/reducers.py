"""显式领域事件 Reducer 与只读 legacy state patch 兼容。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.progress_tree import ProgressTree
from auto_engineering.engine.state import EngineState
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.legacy_event_adapter import (
    LegacyEventAdapter,
    LegacyEventError,
)
from auto_engineering.loop.task_factory import ROLE_FIELD_DEFAULTS, ROLE_FIELD_MAP


class EventChannelViolation(ValueError):
    """事件尝试修改不属于自身的 Projection channel。"""


Reducer = Callable[[EngineState, LoopEvent], EngineState]


EVENT_CHANNELS: dict[LoopEventType, frozenset[str]] = {
    LoopEventType.STAGE_ADVANCED: frozenset({"current_stage"}),
    LoopEventType.ARCHITECTURE_BASELINE_ACCEPTED: frozenset({
        "architecture_baseline"
    }),
    LoopEventType.RUNTIME_REVISION_DETECTED: frozenset({
        "pending_runtime_revision"
    }),
    LoopEventType.RUNTIME_REVISION_ACTIVATED: frozenset({
        "active_runtime_revision",
        "pending_runtime_revision",
    }),
    LoopEventType.GAP_STATE_UPDATED: frozenset({
        "gap_report_json",
        "pending_research_ids",
        "research_archive",
    }),
    LoopEventType.CRITIC_STATE_UPDATED: frozenset({
        "majors_in_a_row",
        "total_majors",
        "critic_verdict",
        "findings",
        "critic_feedback",
        "suggested_fix",
        "strengths",
        "assessment",
        "open_findings",
        "repair_cycle_count",
        "unchanged_finding_streak",
        "last_finding_fingerprint",
        "batch_changed_files",
    }),
    LoopEventType.VERIFICATION_STATE_UPDATED: frozenset({
        "audit_findings",
        "open_findings",
        "coverage_map",
        "critic_feedback",
    }),
    LoopEventType.LIFECYCLE_STATE_UPDATED: frozenset({
        "round",
        "tick",
        "expected_stage",
        "guardrail_retry_counters",
        "batch_state_json",
        "progress_tree_json",
    }),
    LoopEventType.RESULT_EVIDENCE_RECORDED: frozenset({
        "plan",
        "file_list",
        "batch_plan",
        "contracts",
        "files_changed",
        "commit_hash",
        "test_results",
        "red_evidence",
        "developer_snapshot",
        "batch_changed_files",
    }),
    LoopEventType.SESSION_STATE_UPDATED: frozenset({
        "execution_session_id",
        "session_start_tick",
        "session_started_at",
        "session_input_units",
        "session_summary",
    }),
    LoopEventType.PLAN_STATE_UPDATED: frozenset({
        "plan_refine_count",
        "refine_request_json",
        "plan_refine_by_source",
    }),
    LoopEventType.PROJECT_STATE_UPDATED: frozenset({
        "project_profile",
        "project_profile_id",
        "missing_project_capabilities",
    }),
    LoopEventType.PROJECT_ANCHORS_WITNESSED: frozenset({
        "project_anchor_baseline",
    }),
    LoopEventType.TELEMETRY_RECORDED: frozenset({
        "action_history",
        "gate_results",
        "action_timestamp",
        "tick_token_usage",
        "audit_revision_fingerprints",
        "task_verification_evidence",
    }),
    LoopEventType.SUPPLEMENT_STATE_UPDATED: frozenset({
        "design_supplements_json",
        "pending_gap_decisions",
        "gap_decision_policy",
    }),
    LoopEventType.STATE_CONFLICT_DETECTED: frozenset({"state_reconciliation"}),
    LoopEventType.STATE_RECONCILIATION_SELECTED: frozenset({"state_reconciliation"}),
    LoopEventType.THREAD_SUPERSEDED: frozenset({"thread_status"}),
    LoopEventType.PLAN_RECONCILED: frozenset({
        "plan_reconciliation",
        "state_reconciliation",
    }),
    LoopEventType.TASK_SUPERSEDED: frozenset({"superseded_tasks"}),
    LoopEventType.BATCH_COMPLETED: frozenset({
        "batch_state_json",
        "progress_tree_json",
    }),
    LoopEventType.COMPONENT_COMPLETED: frozenset({"batch_state_json"}),
    LoopEventType.PLATE_COMPLETED: frozenset({"batch_state_json"}),
}


def _copy(state: EngineState, **changes: Any) -> EngineState:
    value = state.to_dict()
    unknown = sorted(set(changes) - set(value))
    if unknown:
        raise EventChannelViolation(f"事件含未知 State channel: {', '.join(unknown)}")
    value.update(changes)
    return EngineState.from_dict(value)


def _payload(event: LoopEvent) -> dict[str, Any]:
    return event.to_dict()["payload"]


def _no_projection_change(state: EngineState, event: LoopEvent) -> EngineState:
    return _copy(state)


def _stage_advanced(state: EngineState, event: LoopEvent) -> EngineState:
    payload = _payload(event)
    if (
        set(payload) != {"from", "to"}
        or not isinstance(payload.get("from"), str)
        or not isinstance(payload.get("to"), str)
    ):
        raise EventChannelViolation("StageAdvanced 只能包含 from/to 字符串")
    changes: dict[str, Any] = {"current_stage": payload["to"]}
    for field_name in ROLE_FIELD_MAP.get(payload["from"], []):
        if field_name in ROLE_FIELD_DEFAULTS:
            changes[field_name] = ROLE_FIELD_DEFAULTS[field_name]
    return _copy(state, **changes)


def _architecture_baseline(state: EngineState, event: LoopEvent) -> EngineState:
    payload = _payload(event)
    if set(payload) != {"baseline"} or not isinstance(payload["baseline"], Mapping):
        raise EventChannelViolation("ArchitectureBaselineAccepted payload 无效")
    return _copy(state, architecture_baseline=dict(payload["baseline"]))


def _runtime_detected(state: EngineState, event: LoopEvent) -> EngineState:
    payload = _payload(event)
    pending = payload.get("pending")
    if not isinstance(pending, Mapping):
        raise EventChannelViolation("RuntimeRevisionDetected 缺少 pending revision")
    return _copy(state, pending_runtime_revision=dict(pending))


def _runtime_activated(state: EngineState, event: LoopEvent) -> EngineState:
    payload = _payload(event)
    revision = payload.get("runtime_revision")
    if set(payload) != {"runtime_revision"} or not isinstance(revision, Mapping):
        raise EventChannelViolation("RuntimeRevisionActivated payload 无效")
    return _copy(
        state,
        active_runtime_revision=dict(revision),
        pending_runtime_revision=None,
    )


def _state_channels_changed(state: EngineState, event: LoopEvent) -> EngineState:
    """迁移期 façade 的有界 delta；禁止携带完整 EngineState。"""

    payload = _payload(event)
    changes = payload.get("changes")
    if set(payload) != {"changes", "writer"} or not isinstance(changes, Mapping):
        raise EventChannelViolation("StateChannelsChanged payload 无效")
    if len(changes) >= len(state.to_dict()):
        raise EventChannelViolation("StateChannelsChanged 禁止携带完整 EngineState")
    return _copy(state, **dict(changes))


def _owned_channels(
    state: EngineState,
    event: LoopEvent,
    *,
    allowed: frozenset[str],
) -> EngineState:
    payload = _payload(event)
    changes = payload.get("changes")
    if set(payload) != {"changes"} or not isinstance(changes, Mapping):
        raise EventChannelViolation(f"{event.event_type.value} payload 无效")
    unexpected = sorted(set(changes) - allowed)
    if unexpected:
        raise EventChannelViolation(
            f"{event.event_type.value} 越权修改: {', '.join(unexpected)}"
        )
    return _copy(state, **dict(changes))


def _gap_state_updated(state: EngineState, event: LoopEvent) -> EngineState:
    return _owned_channels(
        state,
        event,
        allowed=frozenset({
            "gap_report_json",
            "pending_research_ids",
            "research_archive",
        }),
    )


def _critic_state_updated(state: EngineState, event: LoopEvent) -> EngineState:
    return _owned_channels(
        state,
        event,
        allowed=frozenset({
            "majors_in_a_row",
            "total_majors",
            "critic_verdict",
            "open_findings",
            "repair_cycle_count",
            "unchanged_finding_streak",
            "last_finding_fingerprint",
            "batch_changed_files",
        }),
    )


def _verification_state_updated(state: EngineState, event: LoopEvent) -> EngineState:
    return _owned_channels(
        state,
        event,
        allowed=frozenset({
            "audit_findings",
            "open_findings",
            "coverage_map",
            "critic_feedback",
        }),
    )


def _batch_completed(state: EngineState, event: LoopEvent) -> EngineState:
    """按稳定 batch/task 身份推进机器游标与人视角进度。"""

    payload = _payload(event)
    required = {
        "batch_id",
        "task_ids",
        "completed_task_count",
        "design_section",
        "progress_node_id",
        "next_task",
    }
    if set(payload) != required:
        raise EventChannelViolation("BATCH_COMPLETED_PAYLOAD_INVALID")
    batch_id = payload.get("batch_id")
    task_ids = payload.get("task_ids")
    count = payload.get("completed_task_count")
    section = payload.get("design_section")
    progress_node_id = payload.get("progress_node_id")
    next_task = payload.get("next_task")
    if (
        not isinstance(batch_id, str)
        or not batch_id
        or not isinstance(task_ids, list)
        or any(not isinstance(item, str) or not item for item in task_ids)
        or len(set(task_ids)) != len(task_ids)
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 0
        or count != len(task_ids)
        or not isinstance(section, str)
        or not isinstance(progress_node_id, str)
        or not progress_node_id
        or (next_task is not None and not isinstance(next_task, str))
        or not isinstance(state.batch_state_json, str)
        or not isinstance(state.progress_tree_json, str)
    ):
        raise EventChannelViolation("BATCH_COMPLETED_PAYLOAD_INVALID")
    try:
        batch_state = BatchState.from_json(state.batch_state_json, None)
        progress_tree = ProgressTree.from_dict(
            json.loads(state.progress_tree_json)
        )
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise EventChannelViolation("BATCH_PROJECTION_INVALID") from exc
    if batch_state.is_component_complete() or batch_state.current_batch_id() != batch_id:
        raise EventChannelViolation("BATCH_IDENTITY_MISMATCH")
    active_batch = batch_state.current_batch()
    expected_task_ids = [
        str(item.get("id"))
        for item in active_batch.get("tasks", [])
        if isinstance(item, Mapping) and item.get("id")
    ]
    if task_ids != expected_task_ids:
        raise EventChannelViolation("TASK_IDENTITY_MISMATCH")
    node = progress_tree.nodes.get(progress_node_id)
    component = batch_state.current_component()
    if (
        node is None
        or node.level != "component"
        or node.name != component.name
        or node.design_section_ref != section
    ):
        raise EventChannelViolation("PROGRESS_COMPONENT_MISSING")
    if node.done_tasks + count > node.total_tasks:
        raise EventChannelViolation("STATE_INVARIANT_VIOLATION")
    node.done_tasks += count
    node.current_task = next_task
    progress_tree.recalculate_parents(node.id)
    batch_state.advance_batch()
    return _copy(
        state,
        batch_state_json=batch_state.to_json(),
        progress_tree_json=json.dumps(
            progress_tree.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def _component_completed(state: EngineState, event: LoopEvent) -> EngineState:
    payload = _payload(event)
    if set(payload) != {"component"} or not isinstance(
        payload.get("component"), str
    ):
        raise EventChannelViolation("COMPONENT_COMPLETED_PAYLOAD_INVALID")
    try:
        batch_state = BatchState.from_json(state.batch_state_json or "", None)
        component = batch_state.current_component()
        if component.name != payload["component"] or not batch_state.is_component_complete():
            raise EventChannelViolation("COMPONENT_IDENTITY_MISMATCH")
        batch_state.advance_component()
    except EventChannelViolation:
        raise
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise EventChannelViolation("BATCH_PROJECTION_INVALID") from exc
    return _copy(state, batch_state_json=batch_state.to_json())


def _plate_completed(state: EngineState, event: LoopEvent) -> EngineState:
    payload = _payload(event)
    if set(payload) != {"plate"} or not isinstance(payload.get("plate"), str):
        raise EventChannelViolation("PLATE_COMPLETED_PAYLOAD_INVALID")
    try:
        batch_state = BatchState.from_json(state.batch_state_json or "", None)
        plate = batch_state.current_plate()
        if plate.name != payload["plate"] or not batch_state.is_plate_complete():
            raise EventChannelViolation("PLATE_IDENTITY_MISMATCH")
        batch_state.advance_plate()
    except EventChannelViolation:
        raise
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise EventChannelViolation("BATCH_PROJECTION_INVALID") from exc
    return _copy(state, batch_state_json=batch_state.to_json())


def _registered_channels(state: EngineState, event: LoopEvent) -> EngineState:
    allowed = EVENT_CHANNELS.get(event.event_type)
    if allowed is None:
        raise EventChannelViolation(f"{event.event_type.value} 缺少 Channel 注册")
    return _owned_channels(state, event, allowed=allowed)


class ReducerRegistry:
    """Event Type 到纯 Reducer 的唯一注册表。"""

    def __init__(self) -> None:
        self._reducers: dict[LoopEventType, Reducer] = {}
        self.legacy_patch_count = 0

    def register(self, event_type: LoopEventType, reducer: Reducer) -> None:
        if event_type in self._reducers:
            raise ValueError(f"Reducer 重复注册: {event_type.value}")
        self._reducers[event_type] = reducer

    def reduce(self, state: EngineState, event: LoopEvent) -> EngineState:
        try:
            adapted = LegacyEventAdapter().adapt(state, event)
        except LegacyEventError as exc:
            raise EventChannelViolation(str(exc)) from exc
        if adapted is not None:
            self.legacy_patch_count += 1
            state = adapted.state
            event = adapted.event
        reducer = self._reducers.get(event.event_type)
        if reducer is None:
            raise EventChannelViolation(f"未注册事件 Reducer: {event.event_type.value}")
        return reducer(state, event)

def default_reducer_registry() -> ReducerRegistry:
    registry = ReducerRegistry()
    special: dict[LoopEventType, Reducer] = {
        LoopEventType.STAGE_ADVANCED: _stage_advanced,
        LoopEventType.ARCHITECTURE_BASELINE_ACCEPTED: _architecture_baseline,
        LoopEventType.RUNTIME_REVISION_DETECTED: _runtime_detected,
        LoopEventType.RUNTIME_REVISION_ACTIVATED: _runtime_activated,
        LoopEventType.STATE_CHANNELS_CHANGED: _state_channels_changed,
        LoopEventType.GAP_STATE_UPDATED: _gap_state_updated,
        LoopEventType.CRITIC_STATE_UPDATED: _critic_state_updated,
        LoopEventType.VERIFICATION_STATE_UPDATED: _verification_state_updated,
        LoopEventType.LIFECYCLE_STATE_UPDATED: _registered_channels,
        LoopEventType.RESULT_EVIDENCE_RECORDED: _registered_channels,
        LoopEventType.SESSION_STATE_UPDATED: _registered_channels,
        LoopEventType.PLAN_STATE_UPDATED: _registered_channels,
        LoopEventType.PROJECT_STATE_UPDATED: _registered_channels,
        LoopEventType.PROJECT_ANCHORS_WITNESSED: _registered_channels,
        LoopEventType.TELEMETRY_RECORDED: _registered_channels,
        LoopEventType.SUPPLEMENT_STATE_UPDATED: _registered_channels,
        LoopEventType.STATE_CONFLICT_DETECTED: _registered_channels,
        LoopEventType.STATE_RECONCILIATION_SELECTED: _registered_channels,
        LoopEventType.COMPONENT_COMPLETED: _component_completed,
        LoopEventType.PLATE_COMPLETED: _plate_completed,
        LoopEventType.THREAD_SUPERSEDED: _registered_channels,
        LoopEventType.PLAN_RECONCILED: _registered_channels,
        LoopEventType.TASK_SUPERSEDED: _registered_channels,
        LoopEventType.BATCH_COMPLETED: _batch_completed,
    }
    for event_type in LoopEventType:
        registry.register(event_type, special.get(event_type, _no_projection_change))
    return registry


__all__ = [
    "EVENT_CHANNELS",
    "EventChannelViolation",
    "Reducer",
    "ReducerRegistry",
    "default_reducer_registry",
]
