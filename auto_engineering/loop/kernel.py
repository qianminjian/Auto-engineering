"""固定的单 Tick 事件提交编译流水线。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.events import LoopEvent, LoopEventType


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
            if changes:
                append(
                    LoopEventType.STATE_CHANNELS_CHANGED,
                    {
                        "changes": changes,
                        "writer": "tick_orchestrator_compat_facade",
                    },
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

        ownership = {
            LoopEventType.STAGE_ADVANCED: frozenset({"current_stage"}),
            LoopEventType.ARCHITECTURE_BASELINE_ACCEPTED: frozenset(
                {"architecture_baseline"}
            ),
            LoopEventType.RUNTIME_REVISION_DETECTED: frozenset(
                {"pending_runtime_revision"}
            ),
            LoopEventType.RUNTIME_REVISION_ACTIVATED: frozenset(
                {"active_runtime_revision", "pending_runtime_revision"}
            ),
            LoopEventType.GAP_STATE_UPDATED: frozenset({
                "gap_report_json",
                "pending_research_ids",
                "research_archive",
            }),
            LoopEventType.CRITIC_STATE_UPDATED: frozenset({
                "majors_in_a_row",
                "total_majors",
                "critic_verdict",
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
        }
        return frozenset().union(
            *(ownership.get(event.event_type, frozenset()) for event in pending_events)
        )


__all__ = ["TickCommitCandidate", "TickKernel"]
