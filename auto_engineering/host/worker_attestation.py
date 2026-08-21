"""宿主对一次原生 Worker 调用的有界事实证明。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from auto_engineering.host import HostPlatform
from auto_engineering.host.spawn_contract import WorkerInvocationSpec


class WorkerAttestationError(ValueError):
    """Attestation 与 active Action 的 Invocation 不一致。"""


def _capabilities_digest(capabilities: tuple[str, ...]) -> str:
    encoded = json.dumps(
        sorted(set(capabilities)), separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class WorkerAttestation:
    platform: HostPlatform
    action_message_id: str
    worker_id: str
    prompt_sha256: str
    requested_effort: str
    effective_effort: str
    isolation_evidence: str
    visible_capabilities_sha256: str
    actual_model: str
    status: str
    sandbox_guaranteed: bool = False

    @classmethod
    def completed(
        cls,
        *,
        platform: HostPlatform,
        action_message_id: str,
        invocation: WorkerInvocationSpec,
        effective_effort: str,
        isolation_evidence: str,
        visible_capabilities: tuple[str, ...],
        actual_model: str,
    ) -> WorkerAttestation:
        return cls(
            platform=platform,
            action_message_id=action_message_id,
            worker_id=invocation.worker_id,
            prompt_sha256=invocation.prompt_sha256,
            requested_effort=invocation.requested_effort,
            effective_effort=effective_effort,
            isolation_evidence=isolation_evidence,
            visible_capabilities_sha256=_capabilities_digest(visible_capabilities),
            actual_model=actual_model,
            status="completed",
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> WorkerAttestation:
        try:
            return cls(
                platform=HostPlatform(value["platform"]),
                action_message_id=str(value["action_message_id"]),
                worker_id=str(value["worker_id"]),
                prompt_sha256=str(value["prompt_sha256"]),
                requested_effort=str(value["requested_effort"]),
                effective_effort=str(value["effective_effort"]),
                isolation_evidence=str(value["isolation_evidence"]),
                visible_capabilities_sha256=str(
                    value["visible_capabilities_sha256"]
                ),
                actual_model=str(value["actual_model"]),
                status=str(value["status"]),
                sandbox_guaranteed=value.get("sandbox_guaranteed", False),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkerAttestationError("ATTESTATION_INVALID") from exc

    def validate(
        self,
        *,
        action_message_id: str,
        invocation: WorkerInvocationSpec,
    ) -> None:
        if self.action_message_id != action_message_id:
            raise WorkerAttestationError("ATTESTATION_ACTION_MISMATCH")
        if self.worker_id != invocation.worker_id:
            raise WorkerAttestationError("ATTESTATION_WORKER_MISMATCH")
        if self.prompt_sha256 != invocation.prompt_sha256:
            raise WorkerAttestationError("ATTESTATION_PROMPT_MISMATCH")
        if (
            self.requested_effort != invocation.requested_effort
            or self.effective_effort != invocation.requested_effort
        ):
            raise WorkerAttestationError("ATTESTATION_EFFORT_MISMATCH")
        if self.status != "completed" or not self.isolation_evidence:
            raise WorkerAttestationError("ATTESTATION_INCOMPLETE")
        allowed_isolation = {
            HostPlatform.CODEX: {"fork_turns=none", "fork_context=false"},
            HostPlatform.CLAUDE_CODE: {"fresh_context"},
        }.get(self.platform)
        if allowed_isolation is None:
            raise WorkerAttestationError("ATTESTATION_PLATFORM_UNSUPPORTED")
        if self.isolation_evidence not in allowed_isolation:
            raise WorkerAttestationError("ATTESTATION_ISOLATION_MISMATCH")
        expected_capabilities = tuple(sorted(invocation.capabilities))
        if (
            self.visible_capabilities_sha256
            != _capabilities_digest(expected_capabilities)
        ):
            raise WorkerAttestationError("ATTESTATION_CAPABILITIES_MISMATCH")

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform.value,
            "action_message_id": self.action_message_id,
            "worker_id": self.worker_id,
            "prompt_sha256": self.prompt_sha256,
            "requested_effort": self.requested_effort,
            "effective_effort": self.effective_effort,
            "isolation_evidence": self.isolation_evidence,
            "visible_capabilities_sha256": self.visible_capabilities_sha256,
            "actual_model": self.actual_model,
            "status": self.status,
            "sandbox_guaranteed": self.sandbox_guaranteed,
        }


def validate_attestations(
    *,
    action_message_id: str,
    invocations: tuple[WorkerInvocationSpec, ...],
    attestations: list[dict[str, Any]],
) -> tuple[WorkerAttestation, ...]:
    if len(attestations) != len(invocations):
        raise WorkerAttestationError("ATTESTATION_COUNT_MISMATCH")
    parsed = tuple(WorkerAttestation.from_dict(item) for item in attestations)
    by_worker = {item.worker_id: item for item in parsed}
    if len(by_worker) != len(parsed):
        raise WorkerAttestationError("ATTESTATION_WORKER_DUPLICATE")
    for invocation in invocations:
        item = by_worker.get(invocation.worker_id)
        if item is None:
            raise WorkerAttestationError("ATTESTATION_WORKER_MISMATCH")
        item.validate(
            action_message_id=action_message_id,
            invocation=invocation,
        )
    return parsed


def attestation_template(
    *,
    platform: HostPlatform,
    action_message_id: str,
    invocation: WorkerInvocationSpec,
) -> dict[str, Any]:
    """由宿主适配层物化证明固定字段，避免 Coordinator 手工推导。"""

    isolation = {
        HostPlatform.CODEX: "fork_turns=none",
        HostPlatform.CLAUDE_CODE: "fresh_context",
    }.get(platform)
    if isolation is None:
        raise WorkerAttestationError("ATTESTATION_PLATFORM_UNSUPPORTED")
    template = WorkerAttestation.completed(
        platform=platform,
        action_message_id=action_message_id,
        invocation=invocation,
        effective_effort=invocation.requested_effort,
        isolation_evidence=isolation,
        visible_capabilities=tuple(sorted(invocation.capabilities)),
        actual_model="unknown",
    ).to_dict()
    template["status"] = "pending"
    return template


__all__ = [
    "WorkerAttestation", "WorkerAttestationError", "attestation_template",
    "validate_attestations",
]
