"""显式领域事件 Reducer 与只读 legacy state patch 兼容。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.events import LoopEvent, LoopEventType


class EventChannelViolation(ValueError):
    """事件尝试修改不属于自身的 Projection channel。"""


Reducer = Callable[[EngineState, LoopEvent], EngineState]


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
    if set(payload) != {"from", "to"} or not isinstance(payload.get("to"), str):
        raise EventChannelViolation("StageAdvanced 只能包含 from/to 字符串")
    return _copy(state, current_stage=payload["to"])


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
        if event.event_type is LoopEventType.RESULT_ACCEPTED:
            patch = _payload(event).get("state_patch")
            if patch is not None:
                return self._reduce_legacy_patch(state, patch)
        reducer = self._reducers.get(event.event_type)
        if reducer is None:
            raise EventChannelViolation(f"未注册事件 Reducer: {event.event_type.value}")
        return reducer(state, event)

    def _reduce_legacy_patch(
        self,
        state: EngineState,
        patch: object,
    ) -> EngineState:
        if not isinstance(patch, Mapping):
            raise EventChannelViolation("legacy state_patch 必须为 object")
        self.legacy_patch_count += 1
        return _copy(state, **dict(patch))


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
    }
    for event_type in LoopEventType:
        registry.register(event_type, special.get(event_type, _no_projection_change))
    return registry


__all__ = [
    "EventChannelViolation",
    "Reducer",
    "ReducerRegistry",
    "default_reducer_registry",
]
