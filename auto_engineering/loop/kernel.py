"""固定的单 Tick 事件提交编译流水线。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.reducers import EVENT_CHANNELS

# 兼容性 delta 的显式白名单。不要从 EVENT_CHANNELS 动态派生：新增 State
# channel 必须同时增加领域事件或明确登记，否则在新写入路径上 fail-closed。
FALLBACK_CHANNEL_EVENTS: dict[str, LoopEventType] = {
    "batch_state_json": LoopEventType.LIFECYCLE_STATE_UPDATED,
    "expected_stage": LoopEventType.LIFECYCLE_STATE_UPDATED,
    "guardrail_retry_counters": LoopEventType.LIFECYCLE_STATE_UPDATED,
    "progress_tree_json": LoopEventType.LIFECYCLE_STATE_UPDATED,
    "round": LoopEventType.LIFECYCLE_STATE_UPDATED,
    "tick": LoopEventType.LIFECYCLE_STATE_UPDATED,
    "batch_changed_files": LoopEventType.RESULT_EVIDENCE_RECORDED,
    "batch_plan": LoopEventType.RESULT_EVIDENCE_RECORDED,
    "commit_hash": LoopEventType.RESULT_EVIDENCE_RECORDED,
    "contracts": LoopEventType.RESULT_EVIDENCE_RECORDED,
    "developer_snapshot": LoopEventType.RESULT_EVIDENCE_RECORDED,
    "file_list": LoopEventType.RESULT_EVIDENCE_RECORDED,
    "files_changed": LoopEventType.RESULT_EVIDENCE_RECORDED,
    "plan": LoopEventType.RESULT_EVIDENCE_RECORDED,
    "red_evidence": LoopEventType.RESULT_EVIDENCE_RECORDED,
    "test_results": LoopEventType.RESULT_EVIDENCE_RECORDED,
    "execution_session_id": LoopEventType.SESSION_STATE_UPDATED,
    "session_input_units": LoopEventType.SESSION_STATE_UPDATED,
    "session_start_tick": LoopEventType.SESSION_STATE_UPDATED,
    "session_started_at": LoopEventType.SESSION_STATE_UPDATED,
    "session_summary": LoopEventType.SESSION_STATE_UPDATED,
    "plan_refine_by_source": LoopEventType.PLAN_STATE_UPDATED,
    "plan_refine_count": LoopEventType.PLAN_STATE_UPDATED,
    "refine_request_json": LoopEventType.PLAN_STATE_UPDATED,
    "missing_project_capabilities": LoopEventType.PROJECT_STATE_UPDATED,
    "project_profile": LoopEventType.PROJECT_STATE_UPDATED,
    "project_profile_id": LoopEventType.PROJECT_STATE_UPDATED,
    "project_anchor_baseline": LoopEventType.PROJECT_ANCHORS_WITNESSED,
    "action_history": LoopEventType.TELEMETRY_RECORDED,
    "action_timestamp": LoopEventType.TELEMETRY_RECORDED,
    "audit_revision_fingerprints": LoopEventType.TELEMETRY_RECORDED,
    "gate_results": LoopEventType.TELEMETRY_RECORDED,
    "task_verification_evidence": LoopEventType.TELEMETRY_RECORDED,
    "tick_token_usage": LoopEventType.TELEMETRY_RECORDED,
    "design_supplements_json": LoopEventType.SUPPLEMENT_STATE_UPDATED,
    "gap_decision_policy": LoopEventType.SUPPLEMENT_STATE_UPDATED,
    "pending_gap_decisions": LoopEventType.SUPPLEMENT_STATE_UPDATED,
    "gap_report_json": LoopEventType.GAP_STATE_UPDATED,
    "pending_research_ids": LoopEventType.GAP_STATE_UPDATED,
    "research_archive": LoopEventType.GAP_STATE_UPDATED,
    "majors_in_a_row": LoopEventType.CRITIC_STATE_UPDATED,
    "total_majors": LoopEventType.CRITIC_STATE_UPDATED,
    "critic_verdict": LoopEventType.CRITIC_STATE_UPDATED,
    "findings": LoopEventType.CRITIC_STATE_UPDATED,
    "critic_feedback": LoopEventType.CRITIC_STATE_UPDATED,
    "suggested_fix": LoopEventType.CRITIC_STATE_UPDATED,
    "strengths": LoopEventType.CRITIC_STATE_UPDATED,
    "assessment": LoopEventType.CRITIC_STATE_UPDATED,
    "open_findings": LoopEventType.CRITIC_STATE_UPDATED,
    "repair_cycle_count": LoopEventType.CRITIC_STATE_UPDATED,
    "unchanged_finding_streak": LoopEventType.CRITIC_STATE_UPDATED,
    "last_finding_fingerprint": LoopEventType.CRITIC_STATE_UPDATED,
    "audit_findings": LoopEventType.VERIFICATION_STATE_UPDATED,
    "coverage_map": LoopEventType.VERIFICATION_STATE_UPDATED,
    "active_runtime_revision": LoopEventType.RUNTIME_REVISION_ACTIVATED,
}


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
                    if event_type is LoopEventType.RUNTIME_REVISION_ACTIVATED:
                        revision = event_changes.get("active_runtime_revision")
                        if not isinstance(revision, Mapping):
                            raise ValueError(
                                "RUNTIME_REVISION_ACTIVATION_INVALID"
                            )
                        append(
                            event_type,
                            {"runtime_revision": dict(revision)},
                            causation_id=result_message_id,
                        )
                        continue
                    append(
                        event_type,
                        {"changes": event_changes},
                        causation_id=result_message_id,
                    )

        for pending in pending_events:
            append(
                pending.event_type,
                pending.to_dict()["payload"],
                causation_id=pending.causation_id or result_message_id,
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
