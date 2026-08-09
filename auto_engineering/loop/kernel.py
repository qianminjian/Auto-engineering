"""固定的单 Tick 事件提交编译流水线。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.reducers import EVENT_CHANNELS

FALLBACK_CHANNEL_EVENTS: dict[str, LoopEventType] = {}
for _event_type in (
    LoopEventType.LIFECYCLE_STATE_UPDATED,
    LoopEventType.RESULT_EVIDENCE_RECORDED,
    LoopEventType.SESSION_STATE_UPDATED,
    LoopEventType.PLAN_STATE_UPDATED,
    LoopEventType.PROJECT_STATE_UPDATED,
    LoopEventType.TELEMETRY_RECORDED,
    LoopEventType.SUPPLEMENT_STATE_UPDATED,
    LoopEventType.GAP_STATE_UPDATED,
    LoopEventType.CRITIC_STATE_UPDATED,
):
    FALLBACK_CHANNEL_EVENTS.update(
        dict.fromkeys(EVENT_CHANNELS[_event_type], _event_type)
    )
FALLBACK_CHANNEL_EVENTS.update({
    channel: LoopEventType.VERIFICATION_STATE_UPDATED
    for channel in EVENT_CHANNELS[LoopEventType.VERIFICATION_STATE_UPDATED]
    if channel not in {"critic_feedback", "open_findings"}
})


@dataclass(frozen=True, slots=True)
class TickCommitCandidate:
    events: tuple[LoopEvent, ...]
    state: EngineState
    action: Mapping[str, Any]


class TickKernel:
    """把已验证转换编译为有序事件；不执行 SQLite 或文件副作用。"""

    def compile_commit(
        self,
        *,
        next_sequence: int,
        previous_state: EngineState | None,
        current_state: EngineState,
        action: Mapping[str, Any],
        pending_events: Sequence[LoopEvent],
        result_message_id: str | None,
        result_causation_id: str | None,
        round_history: Sequence[Mapping[str, Any]] = (),
    ) -> TickCommitCandidate:
        thread_id = current_state.thread_id
        sequence = next_sequence
        events: list[LoopEvent] = []

        def append(
            event_type: LoopEventType,
            payload: Mapping[str, Any],
            *,
            causation_id: str | None = None,
        ) -> None:
            nonlocal sequence
            events.append(LoopEvent.create(
                thread_id=thread_id,
                sequence=sequence,
                event_type=event_type,
                payload=payload,
                causation_id=causation_id,
                correlation_id=thread_id,
            ))
            sequence += 1

        if next_sequence == 0:
            append(
                LoopEventType.LOOP_INITIALIZED,
                {"state": current_state.to_dict(), "round_history": list(round_history)},
            )
        elif result_message_id is not None:
            if previous_state is None or result_causation_id is None:
                raise ValueError("Result commit 缺少 previous_state 或 causation")
            append(
                LoopEventType.RESULT_ACCEPTED,
                {
                    "result_message_id": result_message_id,
                    "round_history": list(round_history),
                },
                causation_id=result_causation_id,
            )
            previous = previous_state.to_dict()
            owned_channels = self._owned_channels(pending_events)
            changes = {
                key: value
                for key, value in current_state.to_dict().items()
                if previous.get(key) != value and key not in owned_channels
            }
            grouped: dict[LoopEventType, dict[str, Any]] = {}
            for channel, value in changes.items():
                event_type = FALLBACK_CHANNEL_EVENTS.get(channel)
                if event_type is None:
                    raise ValueError(
                        f"UNMAPPED_PROJECTION_CHANNEL: {channel}"
                    )
                grouped.setdefault(event_type, {})[channel] = value
            for event_type in LoopEventType:
                event_changes = grouped.get(event_type)
                if event_changes:
                    append(
                        event_type,
                        {"changes": event_changes},
                        causation_id=result_message_id,
                    )

        for pending in pending_events:
            append(
                pending.event_type,
                pending.to_dict()["payload"],
                causation_id=pending.causation_id,
            )
        append(
            LoopEventType.ACTION_ISSUED,
            {"action": dict(action)},
            causation_id=result_message_id,
        )
        return TickCommitCandidate(
            events=tuple(events),
            state=current_state,
            action=dict(action),
        )

    @staticmethod
    def _owned_channels(pending_events: Sequence[LoopEvent]) -> frozenset[str]:
        """返回已由显式领域事件负责重放的 Projection channels。"""

        return frozenset().union(
            *(EVENT_CHANNELS.get(event.event_type, frozenset()) for event in pending_events)
        )


__all__ = ["FALLBACK_CHANNEL_EVENTS", "TickCommitCandidate", "TickKernel"]
