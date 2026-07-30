"""v5.8 ResumeCapsule：跨宿主会话的最小确定性恢复包。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

CAPSULE_SCHEMA_VERSION = "1.0"
_FORBIDDEN_HISTORY_KEYS = frozenset({
    "messages", "transcript", "conversation_history", "action_history",
})


class ResumeCapsuleError(ValueError):
    """Capsule 字段、证据或完整性校验失败。"""


def _canonical(value: object) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ResumeCapsuleError(f"Capsule 必须可序列化: {exc}") from exc


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _thaw(v) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_thaw(item) for item in value]
    return value


def _hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _contains_history(value: object) -> bool:
    if isinstance(value, Mapping):
        return bool(_FORBIDDEN_HISTORY_KEYS.intersection(value)) or any(
            _contains_history(item) for item in value.values()
        )
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return any(_contains_history(item) for item in value)
    return False


@dataclass(frozen=True, slots=True)
class ResumeCapsule:
    schema_version: str
    thread_id: str
    source_session_id: str
    projection_sequence: int
    active_action: Mapping[str, Any]
    state_digest: Mapping[str, Any]
    required_artifacts: tuple[Mapping[str, Any], ...]
    policy_snapshot: Mapping[str, Any]
    budget: Mapping[str, Any]
    issued_at: str
    payload_sha256: str

    @classmethod
    def create(
        cls,
        *,
        thread_id: str,
        source_session_id: str,
        projection_sequence: int,
        active_action: Mapping[str, Any],
        state_digest: Mapping[str, Any],
        required_artifacts: Sequence[Mapping[str, Any]] = (),
        policy_snapshot: Mapping[str, Any] | None = None,
        budget: Mapping[str, Any] | None = None,
        issued_at: str | None = None,
    ) -> ResumeCapsule:
        raw = {
            "schema_version": CAPSULE_SCHEMA_VERSION,
            "thread_id": thread_id,
            "source_session_id": source_session_id,
            "projection_sequence": projection_sequence,
            "active_action": dict(active_action),
            "state_digest": dict(state_digest),
            "required_artifacts": [dict(item) for item in required_artifacts],
            "policy_snapshot": dict(policy_snapshot or {}),
            "budget": dict(budget or {}),
            "issued_at": issued_at or datetime.now(UTC).isoformat(),
        }
        raw["payload_sha256"] = _hash(raw)
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ResumeCapsule:
        raw = _thaw(value)
        required = {
            "schema_version", "thread_id", "source_session_id",
            "projection_sequence", "active_action", "state_digest",
            "required_artifacts", "policy_snapshot", "budget", "issued_at",
            "payload_sha256",
        }
        if set(raw) != required:
            raise ResumeCapsuleError("Capsule 字段集合不符合契约")
        if raw["schema_version"] != CAPSULE_SCHEMA_VERSION:
            raise ResumeCapsuleError("Capsule schema_version 不受支持")
        for field in ("thread_id", "source_session_id", "issued_at"):
            if not isinstance(raw[field], str) or not raw[field]:
                raise ResumeCapsuleError(f"{field} 必须为非空字符串")
        sequence = raw["projection_sequence"]
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise ResumeCapsuleError("projection_sequence 必须为非负整数")
        for field in ("active_action", "state_digest", "policy_snapshot", "budget"):
            if not isinstance(raw[field], Mapping):
                raise ResumeCapsuleError(f"{field} 必须为 object")
        if _contains_history(raw):
            raise ResumeCapsuleError("Capsule 禁止包含完整会话历史")
        action_id = raw["active_action"].get("message_id")
        if not isinstance(action_id, str) or not action_id:
            raise ResumeCapsuleError("active_action.message_id 必须存在")
        artifacts = raw["required_artifacts"]
        if not isinstance(artifacts, list):
            raise ResumeCapsuleError("required_artifacts 必须为 array")
        for artifact in artifacts:
            if (
                not isinstance(artifact, Mapping)
                or not isinstance(artifact.get("artifact_id"), str)
                or not isinstance(artifact.get("kind"), str)
                or not isinstance(artifact.get("sha256"), str)
                or len(artifact["sha256"]) != 64
            ):
                raise ResumeCapsuleError("artifact 引用无效")
        supplied_hash = raw.pop("payload_sha256")
        if supplied_hash != _hash(raw):
            raise ResumeCapsuleError("payload_sha256 校验失败")
        return cls(
            schema_version=CAPSULE_SCHEMA_VERSION,
            thread_id=raw["thread_id"],
            source_session_id=raw["source_session_id"],
            projection_sequence=sequence,
            active_action=_freeze(raw["active_action"]),
            state_digest=_freeze(raw["state_digest"]),
            required_artifacts=tuple(_freeze(item) for item in artifacts),
            policy_snapshot=_freeze(raw["policy_snapshot"]),
            budget=_freeze(raw["budget"]),
            issued_at=raw["issued_at"],
            payload_sha256=supplied_hash,
        )

    def verify_payload_hash(self) -> bool:
        raw = self.to_dict()
        supplied = raw.pop("payload_sha256")
        return supplied == _hash(raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "thread_id": self.thread_id,
            "source_session_id": self.source_session_id,
            "projection_sequence": self.projection_sequence,
            "active_action": _thaw(self.active_action),
            "state_digest": _thaw(self.state_digest),
            "required_artifacts": _thaw(self.required_artifacts),
            "policy_snapshot": _thaw(self.policy_snapshot),
            "budget": _thaw(self.budget),
            "issued_at": self.issued_at,
            "payload_sha256": self.payload_sha256,
        }


__all__ = [
    "CAPSULE_SCHEMA_VERSION",
    "ResumeCapsule",
    "ResumeCapsuleError",
]
