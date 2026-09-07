"""Core-to-Host 的严格 Worker 调用合同。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


class SpawnContractError(ValueError):
    """SpawnPlan 或 WorkerOutcome 不满足最小权限合同。"""


_COORDINATOR_FIELDS = frozenset({
    "spawned", "spawn_proof_token", "spawn_error", "spawn_error_code",
})
_LEGACY_FIELDS = frozenset({"agents", "subagent", "subagent_prompt"})
_HOST_FACT_FIELDS = frozenset({
    "native_worker_handle", "actual_model", "isolation_evidence",
    "attestation", "worker_attestations", "receipt", "outcomes",
})
_WORKER_ARTIFACT_FIELDS = frozenset({
    "worker_id", "status", "payload", "summary",
})
_INVOCATION_FIELDS = frozenset({
    "worker_id", "role", "prompt_ref", "prompt_sha256", "requested_effort",
    "isolation", "capabilities", "receipt_path", "outcome_path",
})


def _is_safe_relative_path(value: str, *, prefix: tuple[str, ...] = ()) -> bool:
    if not value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and path.parts[:len(prefix)] == prefix
    )


@dataclass(frozen=True, slots=True)
class WorkerInvocationSpec:
    worker_id: str
    role: str
    prompt_ref: str
    prompt_sha256: str
    requested_effort: str
    isolation: str
    capabilities: dict[str, bool]
    receipt_path: str
    outcome_path: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> WorkerInvocationSpec:
        if not isinstance(value, Mapping):
            raise SpawnContractError("WORKER_INVOCATION_INVALID")
        unexpected = set(value) - _INVOCATION_FIELDS
        if unexpected.intersection(_LEGACY_FIELDS):
            raise SpawnContractError("SPAWN_LEGACY_FIELD_REJECTED")
        if unexpected.intersection(_HOST_FACT_FIELDS):
            raise SpawnContractError("SPAWN_HOST_FIELD_REJECTED")
        if unexpected:
            raise SpawnContractError("WORKER_INVOCATION_INVALID")
        try:
            capabilities = value["capabilities"]
            if not isinstance(capabilities, Mapping):
                raise TypeError("capabilities must be an object")
            item = cls(
                worker_id=value["worker_id"],
                role=value["role"],
                prompt_ref=value["prompt_ref"],
                prompt_sha256=value["prompt_sha256"],
                requested_effort=value["requested_effort"],
                isolation=value["isolation"],
                capabilities=dict(capabilities),
                receipt_path=value["receipt_path"],
                outcome_path=value["outcome_path"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SpawnContractError("WORKER_INVOCATION_INVALID") from exc
        if (
            not all(isinstance(item, str) for item in (
                item.worker_id, item.role, item.prompt_ref, item.prompt_sha256,
                item.requested_effort, item.isolation, item.receipt_path,
                item.outcome_path,
            ))
            or not item.worker_id
            or not item.role
            or not item.prompt_ref
            or not re.fullmatch(r"[0-9a-f]{64}", item.prompt_sha256)
            or not item.requested_effort
            or item.isolation != "fresh_context"
            or item.capabilities != {
                "may_drive_loop": False,
                "may_spawn_workers": False,
            }
            or not _is_safe_relative_path(
                item.receipt_path, prefix=(".ae-state", "spawn-proofs")
            )
            or not _is_safe_relative_path(item.prompt_ref)
            or not _is_safe_relative_path(
                item.outcome_path,
                prefix=(".ae-state", "host-runtime", "worker-outcomes"),
            )
        ):
            raise SpawnContractError("WORKER_INVOCATION_INVALID")
        return item

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "role": self.role,
            "prompt_ref": self.prompt_ref,
            "prompt_sha256": self.prompt_sha256,
            "requested_effort": self.requested_effort,
            "isolation": self.isolation,
            "capabilities": dict(self.capabilities),
            "receipt_path": self.receipt_path,
            "outcome_path": self.outcome_path,
        }


@dataclass(frozen=True, slots=True)
class SpawnPlan:
    contract_version: str
    invocations: tuple[WorkerInvocationSpec, ...]

    @classmethod
    def from_action(cls, action: Mapping[str, Any]) -> SpawnPlan:
        if not isinstance(action, Mapping):
            raise SpawnContractError("SPAWN_PLAN_INVALID")
        if set(action).intersection(_LEGACY_FIELDS):
            raise SpawnContractError("SPAWN_LEGACY_FIELD_REJECTED")
        spawn = action.get("spawn")
        if not isinstance(spawn, Mapping):
            raise SpawnContractError("SPAWN_PLAN_MISSING")
        if set(spawn).intersection(_LEGACY_FIELDS):
            raise SpawnContractError("SPAWN_LEGACY_FIELD_REJECTED")
        if set(spawn).intersection(_HOST_FACT_FIELDS):
            raise SpawnContractError("SPAWN_HOST_FIELD_REJECTED")
        raw = spawn.get("invocations")
        if not isinstance(raw, list) or not raw:
            raise SpawnContractError("SPAWN_INVOCATIONS_MISSING")
        invocations = tuple(WorkerInvocationSpec.from_dict(item) for item in raw)
        contract_version = spawn.get("contract_version")
        count = spawn.get("count")
        effort = spawn.get("effort")
        if (
            contract_version != "1.0"
            or count != len(invocations)
            or not isinstance(effort, str)
            or any(item.requested_effort != effort for item in invocations)
        ):
            raise SpawnContractError("SPAWN_PLAN_INVALID")
        if len({item.worker_id for item in invocations}) != len(invocations):
            raise SpawnContractError("WORKER_ID_DUPLICATE")
        return cls(contract_version, invocations)


@dataclass(frozen=True, slots=True)
class WorkerOutcome:
    payload: dict[str, Any]
    worker_id: str | None = None
    status: str | None = None
    summary: str | None = None

    @classmethod
    def from_artifact(
        cls,
        value: Mapping[str, Any],
        *,
        expected_worker_id: str | None = None,
    ) -> WorkerOutcome:
        if not isinstance(value, Mapping):
            raise SpawnContractError("WORKER_OUTCOME_INVALID")
        if set(value) != _WORKER_ARTIFACT_FIELDS:
            forbidden = set(value).intersection(
                _LEGACY_FIELDS | _HOST_FACT_FIELDS | _COORDINATOR_FIELDS
            )
            code = (
                "WORKER_OUTCOME_PRIVILEGE_ESCALATION"
                if forbidden else "WORKER_OUTCOME_INVALID"
            )
            raise SpawnContractError(code)
        worker_id = value.get("worker_id")
        status = value.get("status")
        payload = value.get("payload")
        summary = value.get("summary")
        if (
            not isinstance(worker_id, str) or not worker_id
            or not isinstance(status, str) or not status
            or not isinstance(payload, dict)
            or not isinstance(summary, str)
            or (expected_worker_id is not None and worker_id != expected_worker_id)
        ):
            raise SpawnContractError("WORKER_OUTCOME_INVALID")
        return cls(
            payload=dict(payload), worker_id=worker_id,
            status=status, summary=summary,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> WorkerOutcome:
        return cls.from_artifact(value)

    @classmethod
    def from_business_payload(cls, value: Mapping[str, Any]) -> WorkerOutcome:
        """构造测试/宿主内部的业务载荷，不解析 Worker 私有 artifact。"""

        if not isinstance(value, Mapping):
            raise SpawnContractError("WORKER_OUTCOME_INVALID")
        forbidden = (
            _COORDINATOR_FIELDS | _LEGACY_FIELDS | _HOST_FACT_FIELDS
        ).intersection(value)
        if forbidden:
            raise SpawnContractError(
                "WORKER_OUTCOME_PRIVILEGE_ESCALATION: "
                + ",".join(sorted(forbidden))
            )
        return cls(dict(value))

    def to_artifact(self) -> dict[str, Any]:
        if self.worker_id is None or self.status is None or self.summary is None:
            raise SpawnContractError("WORKER_OUTCOME_INVALID")
        return {
            "worker_id": self.worker_id,
            "status": self.status,
            "payload": dict(self.payload),
            "summary": self.summary,
        }


__all__ = [
    "SpawnContractError", "SpawnPlan", "WorkerInvocationSpec", "WorkerOutcome",
]
