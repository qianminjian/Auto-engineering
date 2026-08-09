"""旧事件 payload 到严格领域事件的只读兼容边界。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.events import LoopEvent


class LegacyEventError(ValueError):
    """旧事件无法安全转换为当前 Projection 语义。"""


@dataclass(frozen=True, slots=True)
class AdaptedLegacyEvent:
    state: EngineState
    event: LoopEvent


class LegacyEventAdapter:
    """应用旧 `state_patch`，并移除后交给严格 Reducer。"""

    def adapt(
        self,
        state: EngineState,
        event: LoopEvent,
    ) -> AdaptedLegacyEvent | None:
        raw = event.to_dict()
        payload = raw["payload"]
        patch = payload.get("state_patch")
        if patch is None:
            return None
        if not isinstance(patch, Mapping):
            raise LegacyEventError("legacy state_patch 必须为 object")

        state_data = state.to_dict()
        unknown = sorted(set(patch) - set(state_data))
        if unknown:
            raise LegacyEventError(
                f"legacy state_patch 含未知字段: {', '.join(unknown)}"
            )
        state_data.update(dict(patch))
        patched_state = EngineState.from_dict(state_data)

        canonical_payload = dict(payload)
        canonical_payload.pop("state_patch")
        canonical_payload.pop("legacy_import", None)
        canonical_event = LoopEvent.create(
            thread_id=event.thread_id,
            sequence=event.sequence,
            event_type=event.event_type,
            payload=canonical_payload,
            causation_id=event.causation_id,
            correlation_id=event.correlation_id,
            event_id=event.event_id,
            created_at=event.created_at,
        )
        return AdaptedLegacyEvent(state=patched_state, event=canonical_event)


__all__ = ["AdaptedLegacyEvent", "LegacyEventAdapter", "LegacyEventError"]
