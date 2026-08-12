"""Coordinator 与 Worker 的机器化运行身份。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class RuntimeIdentityError(ValueError):
    """运行身份字段或权限组合无效。"""


class RuntimeRole(StrEnum):
    COORDINATOR = "coordinator"
    WORKER = "worker"


@dataclass(frozen=True, slots=True)
class ExecutionIdentity:
    role: RuntimeRole
    stage: str
    may_drive_loop: bool
    may_spawn_workers: bool
    inherit_parent_context: bool

    @classmethod
    def coordinator(cls, *, stage: str) -> ExecutionIdentity:
        return cls(RuntimeRole.COORDINATOR, stage, True, True, True)

    @classmethod
    def worker(cls, *, stage: str) -> ExecutionIdentity:
        return cls(RuntimeRole.WORKER, stage, False, False, False)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ExecutionIdentity:
        try:
            identity = cls(
                role=RuntimeRole(value["role"]),
                stage=str(value["stage"]),
                may_drive_loop=value["may_drive_loop"],
                may_spawn_workers=value["may_spawn_workers"],
                inherit_parent_context=value["inherit_parent_context"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeIdentityError("RUNTIME_IDENTITY_INVALID") from exc
        if not identity.stage or not all(isinstance(item, bool) for item in (
            identity.may_drive_loop,
            identity.may_spawn_workers,
            identity.inherit_parent_context,
        )):
            raise RuntimeIdentityError("RUNTIME_IDENTITY_INVALID")
        if identity.role is RuntimeRole.WORKER and any((
            identity.may_drive_loop,
            identity.may_spawn_workers,
            identity.inherit_parent_context,
        )):
            raise RuntimeIdentityError("WORKER_IDENTITY_ESCALATION")
        return identity

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "stage": self.stage,
            "may_drive_loop": self.may_drive_loop,
            "may_spawn_workers": self.may_spawn_workers,
            "inherit_parent_context": self.inherit_parent_context,
        }


__all__ = [
    "ExecutionIdentity",
    "RuntimeIdentityError",
    "RuntimeRole",
]
