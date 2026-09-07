"""旧 Action 的安全恢复投影。

该边界只负责把已退役的 Action 变成一次可审计的状态协调 Gate；它不读取、
改写或重新执行旧的 prompt/Worker 合同。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.actions import ActionError
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.protocol import action_envelope
from auto_engineering.loop.reducers import default_reducer_registry


def build_legacy_action_recovery_gate(
    action: Mapping[str, Any],
    root: Path,
    *,
    expected_format: Mapping[str, Any],
    result_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """生成不携带旧执行内容的 reinitialize Gate。"""
    thread_id = action.get("thread_id")
    tick = action.get("tick")
    if not isinstance(thread_id, str) or not isinstance(tick, int):
        raise ValueError("LEGACY_ACTION_IDENTITY_MISSING")
    source_message_id = action.get("message_id", "")
    message_id = str(uuid5(
        NAMESPACE_URL,
        f"legacy-action-recovery:{thread_id}:{source_message_id}",
    ))
    return action_envelope(
        {
            "action": "gate",
            "project_root": str(root.resolve()),
            "gate": {
                "id": "state_reconciliation",
                "type": "decision",
                "prompt": "当前活动 Action 使用已退役协议字段，不能复用；请选择重新初始化。",
                "options": [{"id": "reinitialize", "label": "重新初始化"}],
                "reason_codes": [
                    "legacy_active_action_requires_reinitialize"
                ],
                "missing_anchors": [],
            },
            "instruction": (
                "这是旧 Action 迁移 Gate。必须原样展示 gate.options，等待用户选择；"
                "只允许提交 gate_resolution，禁止复用旧 Action 或旧 subagent_prompt。"
            ),
            "expected_format": dict(expected_format),
            "result_contract": dict(result_contract),
            "extensions": {
                "ae": {
                    "legacy_action_recovery": {
                        "source_action_message_id": source_message_id,
                        "required_resolution": "reinitialize",
                    }
                }
            },
        },
        thread_id=thread_id,
        tick=tick,
        stage=action.get("stage") if isinstance(action.get("stage"), str) else None,
        message_id=message_id,
    )


def persist_legacy_action_recovery_gate(
    action: Mapping[str, Any],
    state: EngineState,
    events: SQLiteEventStore,
    root: Path,
    *,
    expected_format: Mapping[str, Any],
    result_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """原子持久化旧 Action 的恢复 Gate，并保持幂等。"""
    gate_source = dict(action)
    gate_source["thread_id"] = state.thread_id
    gate_source["tick"] = state.tick + 1
    gate = build_legacy_action_recovery_gate(
        gate_source,
        root,
        expected_format=expected_format,
        result_contract=result_contract,
    )
    reconciliation = state.state_reconciliation
    if (
        isinstance(reconciliation, Mapping)
        and reconciliation.get("gate_message_id") == gate["message_id"]
    ):
        return gate

    intent = {
        "mode": "legacy_action_recovery",
        "design_doc_path": state.design_doc_path,
        "design_doc_digest": state.design_doc_digest,
        "scope": None,
        "legacy_action_message_id": action.get("message_id"),
    }
    event = LoopEvent.create(
        thread_id=state.thread_id,
        sequence=events.next_sequence(state.thread_id),
        event_type=LoopEventType.STATE_CONFLICT_DETECTED,
        payload={
            "changes": {
                "state_reconciliation": {
                    "status": "waiting_user",
                    "gate_message_id": gate["message_id"],
                    "reason_codes": [
                        "legacy_active_action_requires_reinitialize"
                    ],
                    "missing_anchors": [],
                    "intent": intent,
                }
            }
        },
        correlation_id=state.thread_id,
        causation_id=gate["message_id"],
    )
    projected = default_reducer_registry().reduce(state, event)
    events.commit_tick(events=[event], state=projected, action=gate)
    return gate


def persisted_reconciliation_gate_status(
    action: Mapping[str, Any],
    state: EngineState | None,
    *,
    status_action: Mapping[str, Any],
    next_operation: Mapping[str, Any],
) -> dict[str, Any] | None:
    """在设计源漂移时读取已持久化的恢复 Gate。"""
    gate = action.get("gate")
    if (
        state is None
        or action.get("action") != "gate"
        or not isinstance(gate, Mapping)
        or gate.get("id") != "state_reconciliation"
    ):
        return None
    return {
        "thread_id": state.thread_id,
        "current_stage": state.current_stage,
        "expected_stage": state.expected_stage,
        "tick": state.tick,
        "round": state.round,
        "verdict": state.critic_verdict,
        "total_majors": state.total_majors,
        "plan_refine_count": state.plan_refine_count,
        "active_action": dict(status_action),
        "next_operation": dict(next_operation),
    }


def host_mapping_error_action(
    action: Mapping[str, Any],
    error: ValueError,
    *,
    expected_format: Mapping[str, Any],
    result_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """将宿主映射错误投影为严格错误或 legacy 恢复 Gate。"""
    error_code = str(error) or "ACTION_INVALID"
    if error_code == "SPAWN_LEGACY_FIELD_REJECTED":
        try:
            return build_legacy_action_recovery_gate(
                action,
                Path(str(action.get("project_root") or ".")),
                expected_format=expected_format,
                result_contract=result_contract,
            )
        except ValueError:
            pass
    payload = ActionError(
        error_code=error_code,
        message="当前 Action 不符合严格宿主合同，已停止复用旧执行路径",
        suggestion="请通过显式迁移边界导入历史状态，或重新执行 dev-loop --init",
    ).to_dict()
    thread_id = action.get("thread_id")
    tick = action.get("tick")
    if not isinstance(thread_id, str) or not isinstance(tick, int):
        return payload
    from auto_engineering.loop.protocol import action_envelope

    return action_envelope(
        payload,
        thread_id=thread_id,
        tick=tick,
        stage=action.get("stage") if isinstance(action.get("stage"), str) else None,
        message_id=action.get("message_id") if isinstance(action.get("message_id"), str) else None,
    )


__all__ = [
    "build_legacy_action_recovery_gate",
    "host_mapping_error_action",
    "persist_legacy_action_recovery_gate",
    "persisted_reconciliation_gate_status",
]
