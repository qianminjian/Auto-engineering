"""Event Store 使用的不可变 LoopEvent 契约。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import uuid4

EVENT_SCHEMA_VERSION = "1.0"


class LoopEventType(StrEnum):
    """协议内核当前定义的事实类型。"""

    LOOP_INITIALIZED = "LoopInitialized"
    ACTION_ISSUED = "ActionIssued"
    RESULT_ACCEPTED = "ResultAccepted"
    GATE_RESOLVED = "GateResolved"
    GUARDRAIL_EVALUATED = "GuardrailEvaluated"
    GATES_COMPLETED = "GatesCompleted"
    STAGE_ADVANCED = "StageAdvanced"
    CHECKPOINT_IMPORTED = "CheckpointImported"
    LOOP_COMPLETED = "LoopCompleted"
    LOOP_FAILED = "LoopFailed"
    EXECUTION_SESSION_STARTED = "ExecutionSessionStarted"
    SESSION_BUDGET_OBSERVED = "SessionBudgetObserved"
    SESSION_ROLLOVER_REQUESTED = "SessionRolloverRequested"
    RESUME_CAPSULE_CREATED = "ResumeCapsuleCreated"
    EXECUTION_SESSION_CLAIMED = "ExecutionSessionClaimed"
    EXECUTION_SESSION_CLOSED = "ExecutionSessionClosed"
    EXECUTION_SESSION_ABANDONED = "ExecutionSessionAbandoned"
    USAGE_RECORDED = "UsageRecorded"
    ARTIFACT_REGISTERED = "ArtifactRegistered"
    PLAN_PATCHED = "PlanPatched"
    STATE_INVARIANT_REJECTED = "StateInvariantRejected"
    VERIFICATION_EVIDENCE_BOUND = "VerificationEvidenceBound"
    PROJECT_PROFILE_RESOLVED = "ProjectProfileResolved"
    PROJECT_PROFILE_CHANGED = "ProjectProfileChanged"
    PROJECT_PROFILE_CONFLICT = "ProjectProfileConflict"
    PROJECT_SETUP_REQUIRED = "ProjectSetupRequired"
    PROJECT_SETUP_COMPLETED = "ProjectSetupCompleted"


class LoopEventValidationError(ValueError):
    """LoopEvent 结构或完整性校验失败。"""


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise LoopEventValidationError(f"payload 必须是有效 JSON: {exc}") from exc


def _payload_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class LoopEvent:
    """Append-only 事件日志中的单条不可变事实。"""

    schema_version: str
    event_id: str
    thread_id: str
    sequence: int
    event_type: LoopEventType
    causation_id: str | None
    correlation_id: str
    payload: Mapping[str, Any]
    payload_sha256: str
    created_at: str

    @classmethod
    def create(
        cls,
        *,
        thread_id: str,
        sequence: int,
        event_type: LoopEventType | str,
        payload: Mapping[str, Any],
        correlation_id: str,
        causation_id: str | None = None,
        event_id: str | None = None,
        created_at: str | None = None,
    ) -> LoopEvent:
        """校验输入并创建事件；调用方负责分配流内 sequence。"""

        normalized_payload = _thaw(payload)
        raw = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_id": event_id or str(uuid4()),
            "thread_id": thread_id,
            "sequence": sequence,
            "event_type": str(event_type),
            "causation_id": causation_id,
            "correlation_id": correlation_id,
            "payload": normalized_payload,
            "payload_sha256": _payload_hash(normalized_payload),
            "created_at": created_at or datetime.now(UTC).isoformat(),
        }
        return cls._from_validated(raw)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LoopEvent:
        """从持久化表示恢复，并验证 payload 完整性。"""

        return cls._from_validated(dict(value))

    @classmethod
    def _from_validated(cls, raw: Mapping[str, Any]) -> LoopEvent:
        required = {
            "schema_version",
            "event_id",
            "thread_id",
            "sequence",
            "event_type",
            "causation_id",
            "correlation_id",
            "payload",
            "payload_sha256",
            "created_at",
        }
        if set(raw) != required:
            raise LoopEventValidationError("LoopEvent 字段集合不符合契约")
        if raw["schema_version"] != EVENT_SCHEMA_VERSION:
            raise LoopEventValidationError("schema_version 不受支持")
        for field in ("event_id", "thread_id", "correlation_id", "created_at"):
            if not isinstance(raw[field], str) or not raw[field]:
                raise LoopEventValidationError(f"{field} 必须为非空字符串")
        if (
            not isinstance(raw["sequence"], int)
            or isinstance(raw["sequence"], bool)
            or raw["sequence"] < 0
        ):
            raise LoopEventValidationError("sequence 必须为非负整数")
        causation_id = raw["causation_id"]
        if causation_id is not None and (
            not isinstance(causation_id, str) or not causation_id
        ):
            raise LoopEventValidationError("causation_id 必须为非空字符串或 null")
        if not isinstance(raw["payload"], Mapping):
            raise LoopEventValidationError("payload 必须为 object")
        payload = _thaw(raw["payload"])
        expected_hash = _payload_hash(payload)
        if raw["payload_sha256"] != expected_hash:
            raise LoopEventValidationError("payload_sha256 校验失败")
        try:
            event_type = LoopEventType(raw["event_type"])
        except (TypeError, ValueError) as exc:
            raise LoopEventValidationError("event_type 不受支持") from exc
        return cls(
            schema_version=EVENT_SCHEMA_VERSION,
            event_id=raw["event_id"],
            thread_id=raw["thread_id"],
            sequence=raw["sequence"],
            event_type=event_type,
            causation_id=causation_id,
            correlation_id=raw["correlation_id"],
            payload=_freeze(payload),
            payload_sha256=expected_hash,
            created_at=raw["created_at"],
        )

    def verify_payload_hash(self) -> bool:
        """验证内存中的 payload 与创建时摘要一致。"""

        return _payload_hash(_thaw(self.payload)) == self.payload_sha256

    def to_dict(self) -> dict[str, Any]:
        """输出可直接进行 JSON/schema 校验的持久化表示。"""

        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "thread_id": self.thread_id,
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "causation_id": self.causation_id,
            "correlation_id": self.correlation_id,
            "payload": _thaw(self.payload),
            "payload_sha256": self.payload_sha256,
            "created_at": self.created_at,
        }


__all__ = [
    "EVENT_SCHEMA_VERSION",
    "LoopEvent",
    "LoopEventType",
    "LoopEventValidationError",
]
