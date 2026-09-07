"""状态协调 Gate 的确定性选择与旧 thread 生命周期处理。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.actions import build_terminal_acceptance_summary
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.protocol import (
    ProtocolEnvelope,
    ResultEnvelope,
    action_envelope,
    payload_digest,
    validate_result_envelope,
)
from auto_engineering.loop.reducers import default_reducer_registry


class StateReconciliationError(ValueError):
    """状态协调选择不符合当前 active Gate。"""


@dataclass(frozen=True, slots=True)
class StateReconciliationOutcome:
    choice: str
    intent: Mapping[str, Any]
    response: Mapping[str, Any]


class StateReconciliationService:
    def __init__(self, events: SQLiteEventStore) -> None:
        self._events = events

    def validate(self, result: Mapping[str, Any]) -> None:
        """只读校验协调 Result，不提交事件、不替换 active thread。"""

        envelope, _, replay = self._validate_protocol_identity(result)
        if replay is not None:
            self._outcome_from_response(replay)
            return
        self._validate_active_selection(result, envelope)

    def select(self, result: Mapping[str, Any]) -> StateReconciliationOutcome:
        envelope, result_hash, replay = self._validate_protocol_identity(result)
        if replay is not None:
            return self._outcome_from_response(replay)

        state, intent, choice = self._validate_active_selection(
            result, envelope
        )
        causation_id = envelope.causation_id
        assert causation_id is not None
        reconciliation = state.state_reconciliation
        assert isinstance(reconciliation, Mapping)

        selected = dict(reconciliation)
        selected.update({"status": "selected", "choice": choice})
        sequence = self._events.next_sequence(state.thread_id)
        selected_event = LoopEvent.create(
            thread_id=state.thread_id,
            sequence=sequence,
            event_type=LoopEventType.STATE_RECONCILIATION_SELECTED,
            payload={"changes": {"state_reconciliation": selected}},
            correlation_id=state.thread_id,
            causation_id=causation_id,
        )
        superseded_event = LoopEvent.create(
            thread_id=state.thread_id,
            sequence=sequence + 1,
            event_type=LoopEventType.THREAD_SUPERSEDED,
            payload={"changes": {"thread_status": "superseded"}},
            correlation_id=state.thread_id,
            causation_id=causation_id,
        )
        registry = default_reducer_registry()
        projected = registry.reduce(state, selected_event)
        projected = registry.reduce(projected, superseded_event)
        response = action_envelope(
            {
                "action": "done",
                "verdict": "SUPERSEDED",
                "message": "旧 thread 已由用户选择重新初始化而逻辑关闭",
                "extensions": {
                    "ae": {
                        "reconciliation": {
                            "choice": choice,
                            "intent": dict(intent),
                        }
                    }
                },
                "acceptance_summary": build_terminal_acceptance_summary(
                    state, verdict="SUPERSEDED",
                ),
            },
            thread_id=state.thread_id,
            tick=state.tick + 1,
            stage=state.current_stage,
            causation_id=envelope.message_id,
        )
        self._events.commit_tick(
            events=[selected_event, superseded_event],
            state=projected,
            action=response,
            result_causation_id=causation_id,
            result_hash=result_hash,
        )
        return StateReconciliationOutcome(
            choice=choice,
            intent=dict(intent),
            response=response,
        )

    def _validate_protocol_identity(
        self, result: Mapping[str, Any]
    ) -> tuple[ResultEnvelope, str, Mapping[str, Any] | None]:
        envelope = validate_result_envelope(result)
        if envelope.causation_id is None:
            raise StateReconciliationError("result causation 缺失")
        result_hash = payload_digest(result)
        replay = self._events.load_protocol_result(
            envelope.thread_id,
            envelope.causation_id,
        )
        if replay is not None and replay[0] != result_hash:
            raise StateReconciliationError("result causation 已绑定不同选择")
        return envelope, result_hash, replay[1] if replay is not None else None

    def _validate_active_selection(
        self,
        result: Mapping[str, Any],
        envelope: ProtocolEnvelope,
    ) -> tuple[EngineState, Mapping[str, Any], str]:
        state = self._events.load_projection(envelope.thread_id)
        active_action = self._events.load_action_snapshot(envelope.thread_id)
        if state is None or active_action is None:
            raise StateReconciliationError("state reconciliation active gate 不存在")
        gate = active_action.get("gate")
        if (
            active_action.get("action") != "gate"
            or not isinstance(gate, Mapping)
            or gate.get("id") != "state_reconciliation"
        ):
            raise StateReconciliationError("causation 未绑定 state reconciliation gate")
        if envelope.causation_id != active_action.get("message_id"):
            raise StateReconciliationError("causation 未绑定 active gate message")

        resolution = result.get("gate_resolution")
        if not isinstance(resolution, Mapping):
            raise StateReconciliationError("gate resolution 缺失")
        if resolution.get("gate_id") != "state_reconciliation":
            raise StateReconciliationError("gate resolution id 无效")
        choice = resolution.get("resolution")
        if choice not in {"reinitialize", "reconcile"}:
            raise StateReconciliationError("gate resolution 不受支持")
        if choice != "reinitialize":
            raise StateReconciliationError("PLAN_RECONCILE 尚未激活")

        reconciliation = state.state_reconciliation
        if not isinstance(reconciliation, Mapping):
            raise StateReconciliationError("state reconciliation 投影缺失")
        intent = reconciliation.get("intent")
        if not isinstance(intent, Mapping):
            raise StateReconciliationError("state reconciliation intent 缺失")
        return state, intent, choice

    @staticmethod
    def _outcome_from_response(response: Mapping[str, Any]) -> StateReconciliationOutcome:
        extensions = response.get("extensions")
        ae = extensions.get("ae") if isinstance(extensions, Mapping) else None
        reconciliation = ae.get("reconciliation") if isinstance(ae, Mapping) else None
        if not isinstance(reconciliation, Mapping):
            raise StateReconciliationError("replayed response 缺少 reconciliation")
        choice = reconciliation.get("choice")
        intent = reconciliation.get("intent")
        if not isinstance(choice, str) or not isinstance(intent, Mapping):
            raise StateReconciliationError("replayed reconciliation 无效")
        return StateReconciliationOutcome(
            choice=choice,
            intent=dict(intent),
            response=dict(response),
        )


__all__ = [
    "StateReconciliationError",
    "StateReconciliationOutcome",
    "StateReconciliationService",
]
