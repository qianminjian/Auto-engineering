"""Core-to-Host 的严格 Worker 调用合同。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


class SpawnContractError(ValueError):
    """SpawnPlan 或 WorkerOutcome 不满足最小权限合同。"""


_COORDINATOR_FIELDS = frozenset({
    "spawned", "spawn_proof_token", "spawn_error", "spawn_error_code",
})


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

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> WorkerInvocationSpec:
        try:
            item = cls(
                worker_id=str(value["worker_id"]),
                role=str(value["role"]),
                prompt_ref=str(value["prompt_ref"]),
                prompt_sha256=str(value["prompt_sha256"]),
                requested_effort=str(value["requested_effort"]),
                isolation=str(value["isolation"]),
                capabilities=dict(value["capabilities"]),
                receipt_path=str(value["receipt_path"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SpawnContractError("WORKER_INVOCATION_INVALID") from exc
        if (
            not item.worker_id
            or not item.role
            or not item.prompt_ref
            or len(item.prompt_sha256) != 64
            or not item.requested_effort
            or item.isolation != "fresh_context"
            or item.capabilities != {
                "may_drive_loop": False,
                "may_spawn_workers": False,
            }
            or not item.receipt_path
            or PurePosixPath(item.receipt_path).is_absolute()
            or ".." in PurePosixPath(item.receipt_path).parts
            or not item.receipt_path.startswith(".ae-state/spawn-proofs/")
            or PurePosixPath(item.prompt_ref).is_absolute()
            or ".." in PurePosixPath(item.prompt_ref).parts
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
        }


@dataclass(frozen=True, slots=True)
class SpawnPlan:
    contract_version: str
    invocations: tuple[WorkerInvocationSpec, ...]

    @classmethod
    def from_action(cls, action: Mapping[str, Any]) -> SpawnPlan:
        spawn = action.get("spawn")
        if not isinstance(spawn, Mapping):
            raise SpawnContractError("SPAWN_PLAN_MISSING")
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

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> WorkerOutcome:
        forbidden = _COORDINATOR_FIELDS.intersection(value)
        if forbidden:
            raise SpawnContractError(
                "WORKER_OUTCOME_PRIVILEGE_ESCALATION: " + ",".join(sorted(forbidden))
            )
        return cls(dict(value))


__all__ = [
    "SpawnContractError", "SpawnPlan", "WorkerInvocationSpec", "WorkerOutcome",
]
