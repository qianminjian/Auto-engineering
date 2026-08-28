"""Core-to-Host 的机器化执行处置契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ExecutionControlError(ValueError):
    """ExecutionControl 字段或组合不合法。"""


class ExecutionDisposition(StrEnum):
    CONTINUE = "CONTINUE"
    WAIT_RESOURCE = "WAIT_RESOURCE"
    WAIT_USER = "WAIT_USER"
    TERMINAL = "TERMINAL"
    ERROR = "ERROR"
    HANDOFF_REQUIRED = "HANDOFF_REQUIRED"


# Gate type 表示用户交互语义，不是宿主执行阶段。所有生产方（设计权威、状态协调、
# escalation、阶段检查点）统一经过下方唯一的 Action → ExecutionControl 策略，
# 确保得到相同的 WAIT_USER 处置。
_USER_INTERACTIVE_GATE_TYPES = frozenset({
    "decision",
    "agent_escalation",
    "stage_checkpoint",
    "manual",
    "user",
})


@dataclass(frozen=True, slots=True)
class ExecutionControl:
    schema_version: str
    disposition: ExecutionDisposition
    continuation_required: bool
    yield_allowed: bool
    allowed_stop_reasons: tuple[str, ...]
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ExecutionControlError("ExecutionControl schema_version 不受支持")
        if self.disposition is ExecutionDisposition.CONTINUE and (
            not self.continuation_required or self.yield_allowed
        ):
            raise ExecutionControlError(
                "CONTINUE 必须 continuation_required=true 且 yield_allowed=false"
            )
        if self.disposition in {
            ExecutionDisposition.WAIT_RESOURCE,
            ExecutionDisposition.WAIT_USER,
        } and not self.reason_code:
            raise ExecutionControlError("等待处置必须包含 reason_code")
        if self.disposition is not ExecutionDisposition.CONTINUE and self.continuation_required:
            raise ExecutionControlError("非 CONTINUE 不得要求自动续接")

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": self.schema_version,
            "disposition": self.disposition.value,
            "continuation_required": self.continuation_required,
            "yield_allowed": self.yield_allowed,
            "allowed_stop_reasons": list(self.allowed_stop_reasons),
        }
        if self.reason_code is not None:
            value["reason_code"] = self.reason_code
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ExecutionControl:
        allowed = {
            "schema_version",
            "disposition",
            "continuation_required",
            "yield_allowed",
            "allowed_stop_reasons",
            "reason_code",
        }
        if set(value) - allowed:
            raise ExecutionControlError("ExecutionControl 含未知字段")
        raw_disposition = value.get("disposition")
        if not isinstance(raw_disposition, str):
            raise ExecutionControlError("ExecutionControl disposition 不受支持")
        try:
            disposition = ExecutionDisposition(raw_disposition)
        except (TypeError, ValueError) as exc:
            raise ExecutionControlError("ExecutionControl disposition 不受支持") from exc
        reasons = value.get("allowed_stop_reasons", [])
        if not isinstance(reasons, list) or not all(
            isinstance(item, str) and item for item in reasons
        ):
            raise ExecutionControlError("allowed_stop_reasons 必须为字符串数组")
        continuation = value.get("continuation_required")
        yield_allowed = value.get("yield_allowed")
        if not isinstance(continuation, bool) or not isinstance(yield_allowed, bool):
            raise ExecutionControlError("ExecutionControl 布尔字段无效")
        reason_code = value.get("reason_code")
        if reason_code is not None and (
            not isinstance(reason_code, str) or not reason_code
        ):
            raise ExecutionControlError("reason_code 必须为非空字符串或 null")
        return cls(
            schema_version=str(value.get("schema_version", "")),
            disposition=disposition,
            continuation_required=continuation,
            yield_allowed=yield_allowed,
            allowed_stop_reasons=tuple(reasons),
            reason_code=reason_code,
        )


def control_for_action(action: Mapping[str, Any]) -> ExecutionControl:
    """根据 Core Action discriminator 计算唯一合法处置。"""

    name = action.get("action")
    if name == "done":
        disposition = ExecutionDisposition.TERMINAL
        reason = None
    elif name == "error":
        disposition = ExecutionDisposition.ERROR
        reason = str(action.get("error_code") or "core_error")
    elif name == "session_rollover":
        disposition = ExecutionDisposition.HANDOFF_REQUIRED
        reason = str(action.get("reason") or "recovery_required")
    elif name == "gap_review" and action.get("auto_decision") is None:
        disposition = ExecutionDisposition.WAIT_USER
        reason = "gap_decisions_required"
    elif name == "resource_wait":
        disposition = ExecutionDisposition.WAIT_RESOURCE
        reason = str(action.get("reason_code") or "resource_unavailable")
    elif (
        name == "developer"
        and isinstance(action.get("gate_summary"), Mapping)
        and isinstance(action["gate_summary"].get("task_evidence"), Mapping)
        and action["gate_summary"]["task_evidence"].get("status")
        == "environment_failure"
    ):
        disposition = ExecutionDisposition.WAIT_USER
        reason = "environment_failure"
    elif name == "gate":
        gate = action.get("gate")
        if not isinstance(gate, Mapping):
            disposition = ExecutionDisposition.ERROR
            reason = "GATE_PAYLOAD_INVALID"
        elif (
            gate.get("id") == "state_reconciliation"
            or gate.get("type") in _USER_INTERACTIVE_GATE_TYPES
        ):
            disposition = ExecutionDisposition.WAIT_USER
            raw_reason = gate.get("reason_code")
            if isinstance(raw_reason, str) and raw_reason:
                reason = raw_reason
            elif gate.get("id") == "state_reconciliation":
                reason = "STATE_RECONCILIATION_REQUIRED"
            else:
                reason = "manual_gate_required"
        else:
            # 未登记的 Gate 不能猜测为自动流程；新增类型必须先注册语义。
            disposition = ExecutionDisposition.ERROR
            reason = "UNKNOWN_GATE_TYPE"
    else:
        disposition = ExecutionDisposition.CONTINUE
        reason = None
    return ExecutionControl(
        schema_version="1.0",
        disposition=disposition,
        continuation_required=disposition is ExecutionDisposition.CONTINUE,
        yield_allowed=disposition is not ExecutionDisposition.CONTINUE,
        allowed_stop_reasons=(),
        reason_code=reason,
    )


def project_execution_control(action: Mapping[str, Any]) -> dict[str, Any]:
    """为宿主投影修复旧 Action 中过期的处置字段。

    事件流中的 Canonical Action 不可变；仅在宿主边界生成安全投影，确保历史版本
    把人工 Gate 错写成 ``CONTINUE`` 时不会再次触发错误执行。
    """

    projected = dict(action)
    extensions = dict(projected.get("extensions") or {})
    ae = dict(extensions.get("ae") or {})
    ae["execution_control"] = control_for_action(projected).to_dict()
    extensions["ae"] = ae
    projected["extensions"] = extensions
    return projected


__all__ = [
    "ExecutionControl",
    "ExecutionControlError",
    "ExecutionDisposition",
    "control_for_action",
    "project_execution_control",
]
