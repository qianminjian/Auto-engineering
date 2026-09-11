"""状态协调 Gate Result 的只读 CLI 投影。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.actions import ActionError
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.protocol import action_envelope
from auto_engineering.loop.reducers import default_reducer_registry

if TYPE_CHECKING:
    from auto_engineering.loop.event_store import SQLiteEventStore


def build_recovery_gate(
    action: Mapping[str, Any],
    root: Path,
    *,
    expected_format: Mapping[str, Any],
    result_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """将无法安全继续的活动 Action 投影为唯一的状态协调 Gate。"""
    thread_id = action.get("thread_id")
    tick = action.get("tick")
    if not isinstance(thread_id, str) or not isinstance(tick, int):
        raise ValueError("ACTION_IDENTITY_MISSING")
    source_message_id = action.get("message_id", "")
    message_id = str(uuid5(
        NAMESPACE_URL,
        f"action-recovery:{thread_id}:{source_message_id}",
    ))
    return action_envelope(
        {
            "action": "gate",
            "project_root": str(root.resolve()),
            "gate": {
                "id": "state_reconciliation",
                "type": "decision",
                "prompt": "当前活动 Action 不能安全复用，请选择重新初始化。",
                "options": [{"id": "reinitialize", "label": "重新初始化"}],
                "reason_codes": ["active_action_requires_reinitialize"],
                "missing_anchors": [],
            },
            "instruction": (
                "这是状态协调 Gate。必须原样展示 gate.options，等待用户选择；"
                "只允许提交 gate_resolution，禁止复用旧执行内容。"
            ),
            "expected_format": dict(expected_format),
            "result_contract": dict(result_contract),
            "extensions": {
                "ae": {
                    "action_recovery": {
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


def persist_recovery_gate(
    action: Mapping[str, Any],
    state: EngineState,
    events: SQLiteEventStore,
    root: Path,
    *,
    expected_format: Mapping[str, Any],
    result_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """原子持久化状态协调 Gate，并保持幂等。"""
    gate_source = dict(action)
    gate_source["thread_id"] = state.thread_id
    gate_source["tick"] = state.tick + 1
    gate = build_recovery_gate(
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
        "mode": "action_recovery",
        "design_doc_path": state.design_doc_path,
        "design_doc_digest": state.design_doc_digest,
        "scope": None,
        "source_action_message_id": action.get("message_id"),
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
                    "reason_codes": ["active_action_requires_reinitialize"],
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
    """在设计源漂移时读取已持久化的状态协调 Gate。"""
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
    """将宿主映射错误投影为严格错误 Action。"""
    error_code = str(error) or "ACTION_INVALID"
    payload = ActionError(
        error_code=error_code,
        message="当前 Action 不符合严格宿主合同，已停止复用旧执行路径",
        suggestion="请重新执行 dev-loop --init，或提交状态协调 Gate 的合法选择",
    ).to_dict()
    thread_id = action.get("thread_id")
    tick = action.get("tick")
    if not isinstance(thread_id, str) or not isinstance(tick, int):
        return payload
    return action_envelope(
        payload,
        thread_id=thread_id,
        tick=tick,
        stage=action.get("stage") if isinstance(action.get("stage"), str) else None,
        message_id=action.get("message_id") if isinstance(action.get("message_id"), str) else None,
    )


def validate_state_reconciliation_result_file(
    *,
    result_file: Path,
    active_thread: str,
    events: SQLiteEventStore,
) -> dict[str, Any] | None:
    """只读校验状态协调 Result；非协调 Result 返回 None。"""

    try:
        result = json.loads(result_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(result, Mapping):
        return None
    resolution = result.get("gate_resolution")
    if not isinstance(resolution, Mapping):
        return None
    if resolution.get("gate_id") != "state_reconciliation":
        return None

    from auto_engineering.loop.action_responses import ErrorResponse
    from auto_engineering.loop.protocol import ProtocolValidationError
    from auto_engineering.loop.state_reconciliation import (
        StateReconciliationError,
        StateReconciliationService,
    )

    if result.get("thread_id") != active_thread:
        return ErrorResponse(
            "ACTION_NOT_ACTIVE",
            "Result 指向的 thread 不是当前 active thread",
        ).to_dict()
    try:
        StateReconciliationService(events).validate(result)
    except ProtocolValidationError as exc:
        return ErrorResponse(exc.code.value, str(exc)).to_dict()
    except StateReconciliationError as exc:
        return ErrorResponse(
            "STATE_RECONCILIATION_RESULT_INVALID",
            str(exc),
            suggestion="只提交当前 state_reconciliation Gate 的合法 reinitialize 选择。",
        ).to_dict()

    state = events.load_projection(active_thread)
    if state is None:
        return ErrorResponse(
            "STATE_RECONCILIATION_RESULT_INVALID",
            "协调 Result 对应的 active thread 状态不存在",
        ).to_dict()
    return {
        "action": "validation_passed",
        "stage": state.current_stage,
        "thread_id": state.thread_id,
        "causation_id": result.get("causation_id"),
    }


__all__ = [
    "build_recovery_gate",
    "host_mapping_error_action",
    "persist_recovery_gate",
    "persisted_reconciliation_gate_status",
    "validate_state_reconciliation_result_file",
]
