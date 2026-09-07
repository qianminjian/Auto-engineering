"""原生 Worker 等待、心跳和所有权观察的宿主合同。"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class WorkerObservationContractError(ValueError):
    """Worker 观察合同被修改或不完整。"""


_FIELDS = frozenset({
    "schema_version",
    "mode",
    "wait_timeout_ms",
    "max_waits",
    "heartbeat_intervals_ms",
    "after_waits",
    "unknown_owner_disposition",
    "terminal_statuses",
})
_TERMINAL_STATUSES = (
    "completed",
    "failed",
    "cancelled",
    "timed_out",
)
_UNKNOWN_OWNER_DISPOSITION = "WAIT_RESOURCE/WORKER_OWNERSHIP_UNCERTAIN"


@dataclass(frozen=True, slots=True)
class WorkerObservationContract:
    """由 Core/Adapter 固化、由宿主执行的有界观察策略。"""

    schema_version: str
    mode: str
    wait_timeout_ms: int
    max_waits: int
    heartbeat_intervals_ms: tuple[int, ...]
    after_waits: str
    unknown_owner_disposition: str
    terminal_statuses: tuple[str, ...]

    @classmethod
    def for_platform(cls, platform: object) -> WorkerObservationContract:
        platform_value = getattr(platform, "value", platform)
        if platform_value == "codex":
            return cls(
                schema_version="1.0",
                mode="native_wait",
                wait_timeout_ms=300_000,
                max_waits=3,
                heartbeat_intervals_ms=(300_000, 600_000, 900_000),
                after_waits="probe_owner_then_interrupt",
                unknown_owner_disposition=_UNKNOWN_OWNER_DISPOSITION,
                terminal_statuses=_TERMINAL_STATUSES,
            )
        if platform_value == "claude-code":
            return cls(
                schema_version="1.0",
                mode="synchronous_return",
                wait_timeout_ms=0,
                max_waits=0,
                heartbeat_intervals_ms=(),
                after_waits="native_return",
                unknown_owner_disposition=_UNKNOWN_OWNER_DISPOSITION,
                terminal_statuses=_TERMINAL_STATUSES,
            )
        raise WorkerObservationContractError(
            "WORKER_OBSERVATION_PLATFORM_UNSUPPORTED"
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> WorkerObservationContract:
        if not isinstance(value, Mapping) or set(value) != _FIELDS:
            raise WorkerObservationContractError("WORKER_OBSERVATION_CONTRACT_INVALID")
        raw_heartbeat = value.get("heartbeat_intervals_ms")
        raw_terminal = value.get("terminal_statuses")
        raw_schema_version = value.get("schema_version")
        raw_mode = value.get("mode")
        raw_wait_timeout = value.get("wait_timeout_ms")
        raw_max_waits = value.get("max_waits")
        raw_after_waits = value.get("after_waits")
        raw_unknown_owner = value.get("unknown_owner_disposition")
        if (
            not isinstance(raw_schema_version, str)
            or not isinstance(raw_mode, str)
            or not isinstance(raw_wait_timeout, int)
            or not isinstance(raw_max_waits, int)
            or not isinstance(raw_after_waits, str)
            or not isinstance(raw_unknown_owner, str)
            or not isinstance(raw_heartbeat, list)
            or not isinstance(raw_terminal, list)
        ):
            raise WorkerObservationContractError("WORKER_OBSERVATION_CONTRACT_INVALID")
        item = cls(
            schema_version=raw_schema_version,
            mode=raw_mode,
            wait_timeout_ms=raw_wait_timeout,
            max_waits=raw_max_waits,
            heartbeat_intervals_ms=tuple(raw_heartbeat),
            after_waits=raw_after_waits,
            unknown_owner_disposition=raw_unknown_owner,
            terminal_statuses=tuple(raw_terminal),
        )
        if (
            item.schema_version != "1.0"
            or item.mode not in {"native_wait", "synchronous_return"}
            or not isinstance(item.wait_timeout_ms, int)
            or isinstance(item.wait_timeout_ms, bool)
            or item.wait_timeout_ms < 0
            or not isinstance(item.max_waits, int)
            or isinstance(item.max_waits, bool)
            or item.max_waits < 0
            or any(
                not isinstance(interval, int)
                or isinstance(interval, bool)
                or interval <= 0
                for interval in item.heartbeat_intervals_ms
            )
            or item.after_waits not in {
                "probe_owner_then_interrupt",
                "native_return",
            }
            or item.unknown_owner_disposition != _UNKNOWN_OWNER_DISPOSITION
            or item.terminal_statuses != _TERMINAL_STATUSES
        ):
            raise WorkerObservationContractError("WORKER_OBSERVATION_CONTRACT_INVALID")
        expected = cls.for_platform(
            "codex" if item.mode == "native_wait" else "claude-code"
        )
        if item != expected:
            raise WorkerObservationContractError("WORKER_OBSERVATION_CONTRACT_INVALID")
        return item
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "wait_timeout_ms": self.wait_timeout_ms,
            "max_waits": self.max_waits,
            "heartbeat_intervals_ms": list(self.heartbeat_intervals_ms),
            "after_waits": self.after_waits,
            "unknown_owner_disposition": self.unknown_owner_disposition,
            "terminal_statuses": list(self.terminal_statuses),
        }


_RECORD_FIELDS = frozenset({
    "schema_version",
    "action_message_id",
    "worker_id",
    "execution_generation",
    "fencing_token",
    "observed_at",
    "native_status",
    "wait_attempt",
    "owner_known",
    "native_worker_handle",
})
_NATIVE_STATUSES = frozenset({
    "running",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "unknown",
})
_SAFE_PATH_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True, slots=True)
class WorkerObservationRecord:
    """当前 Action/Worker 的最新原生观察事实。"""

    schema_version: str
    action_message_id: str
    worker_id: str
    execution_generation: int
    fencing_token: str
    observed_at: str
    native_status: str
    wait_attempt: int
    owner_known: bool
    native_worker_handle: str | None

    def validate(self) -> None:
        if (
            self.schema_version != "1.0"
            or not isinstance(self.action_message_id, str)
            or not self.action_message_id
            or not isinstance(self.worker_id, str)
            or not self.worker_id
            or not isinstance(self.execution_generation, int)
            or isinstance(self.execution_generation, bool)
            or self.execution_generation < 1
            or not isinstance(self.fencing_token, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.fencing_token)
            or not isinstance(self.observed_at, str)
            or not self.observed_at
            or self.native_status not in _NATIVE_STATUSES
            or not isinstance(self.wait_attempt, int)
            or isinstance(self.wait_attempt, bool)
            or not 0 <= self.wait_attempt <= 3
            or not isinstance(self.owner_known, bool)
            or (
                self.native_worker_handle is not None
                and (
                    not isinstance(self.native_worker_handle, str)
                    or not self.native_worker_handle
                )
            )
            or (
                self.native_status == "completed"
                and (
                    not self.owner_known
                    or not self.native_worker_handle
                )
            )
        ):
            raise WorkerObservationContractError("WORKER_OBSERVATION_RECORD_INVALID")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> WorkerObservationRecord:
        if not isinstance(value, Mapping) or set(value) != _RECORD_FIELDS:
            raise WorkerObservationContractError("WORKER_OBSERVATION_RECORD_INVALID")
        item = cls(**dict(value))
        item.validate()
        return item

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "action_message_id": self.action_message_id,
            "worker_id": self.worker_id,
            "execution_generation": self.execution_generation,
            "fencing_token": self.fencing_token,
            "observed_at": self.observed_at,
            "native_status": self.native_status,
            "wait_attempt": self.wait_attempt,
            "owner_known": self.owner_known,
            "native_worker_handle": self.native_worker_handle,
        }


def observation_path_for(root: Path, record: WorkerObservationRecord) -> Path:
    """返回 Action-scoped 观察文件路径，不允许用户字段逃出状态目录。"""
    record.validate()
    return root.resolve() / observation_relative_path(
        record.action_message_id,
        record.worker_id,
        record.execution_generation,
    )


def observation_relative_path(
    action_message_id: str,
    worker_id: str,
    execution_generation: int,
) -> Path:
    """生成不依赖项目根的 Action-scoped 观察相对路径。"""
    if not isinstance(action_message_id, str) or not action_message_id:
        raise WorkerObservationContractError("WORKER_OBSERVATION_RECORD_INVALID")
    if not isinstance(worker_id, str) or not worker_id:
        raise WorkerObservationContractError("WORKER_OBSERVATION_RECORD_INVALID")
    if (
        not isinstance(execution_generation, int)
        or isinstance(execution_generation, bool)
        or execution_generation < 1
    ):
        raise WorkerObservationContractError("WORKER_OBSERVATION_RECORD_INVALID")
    def component(value: str, *, digest_size: int) -> str:
        if _SAFE_PATH_COMPONENT.fullmatch(value):
            return value
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:digest_size]
    return (
        Path(".ae-state")
        / "host-runtime"
        / "worker-observations"
        / (
            f"{component(action_message_id, digest_size=24)}-"
            f"{component(worker_id, digest_size=16)}-"
            f"g{execution_generation}.json"
        )
    )


__all__ = [
    "WorkerObservationContract",
    "WorkerObservationContractError",
    "WorkerObservationRecord",
    "observation_path_for",
    "observation_relative_path",
]
