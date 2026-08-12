"""Phase 82 T441：宿主能力协商与 Worker Attestation。"""

from __future__ import annotations

import pytest

from auto_engineering.host import HostPlatform
from auto_engineering.host.capabilities import HostCapabilities, HostCapabilityError
from auto_engineering.host.spawn_contract import WorkerInvocationSpec
from auto_engineering.host.worker_attestation import (
    WorkerAttestation,
    WorkerAttestationError,
    validate_attestations,
)


def _spec() -> WorkerInvocationSpec:
    return WorkerInvocationSpec(
        worker_id="architect-0",
        role="architect",
        prompt_ref="artifact://prompt",
        prompt_sha256="a" * 64,
        requested_effort="xhigh",
        isolation="fresh_context",
        capabilities={"may_drive_loop": False, "may_spawn_workers": False},
        receipt_path=".ae-state/spawn-proofs/token.json",
    )


def test_spawn_requires_isolated_worker_capability() -> None:
    with pytest.raises(HostCapabilityError, match="ISOLATED_WORKER_INVOCATION_REQUIRED"):
        HostCapabilities(
            native_subagents=True,
            isolated_worker_invocation=False,
        ).require_spawn()


def test_codex_attestation_records_observed_isolation_not_sandbox_claim() -> None:
    attestation = WorkerAttestation.completed(
        platform=HostPlatform.CODEX,
        action_message_id="action-1",
        invocation=_spec(),
        effective_effort="xhigh",
        isolation_evidence="fork_turns=none",
        visible_capabilities=("may_drive_loop", "may_spawn_workers"),
        actual_model="gpt-test",
    )

    assert attestation.isolation_evidence == "fork_turns=none"
    assert attestation.sandbox_guaranteed is False
    assert attestation.visible_capabilities_sha256


def test_attestation_rejects_platform_isolation_mismatch() -> None:
    attestation = WorkerAttestation.completed(
        platform=HostPlatform.CODEX,
        action_message_id="action-1",
        invocation=_spec(),
        effective_effort="xhigh",
        isolation_evidence="fresh_context",
        visible_capabilities=("may_drive_loop", "may_spawn_workers"),
        actual_model="gpt-test",
    )

    with pytest.raises(WorkerAttestationError, match="ATTESTATION_ISOLATION_MISMATCH"):
        attestation.validate(action_message_id="action-1", invocation=_spec())


def test_attestation_rejects_capability_snapshot_mismatch() -> None:
    attestation = WorkerAttestation.completed(
        platform=HostPlatform.CODEX,
        action_message_id="action-1",
        invocation=_spec(),
        effective_effort="xhigh",
        isolation_evidence="fork_turns=none",
        visible_capabilities=("unexpected",),
        actual_model="gpt-test",
    )

    with pytest.raises(WorkerAttestationError, match="ATTESTATION_CAPABILITIES_MISMATCH"):
        attestation.validate(action_message_id="action-1", invocation=_spec())


def test_attestation_must_bind_action_prompt_and_effort() -> None:
    attestation = WorkerAttestation.completed(
        platform=HostPlatform.CODEX,
        action_message_id="wrong-action",
        invocation=_spec(),
        effective_effort="high",
        isolation_evidence="fork_turns=none",
        visible_capabilities=(),
        actual_model="gpt-test",
    )

    with pytest.raises(WorkerAttestationError, match="ATTESTATION_ACTION_MISMATCH"):
        attestation.validate(action_message_id="action-1", invocation=_spec())


def test_attestation_rejects_effort_downgrade() -> None:
    attestation = WorkerAttestation.completed(
        platform=HostPlatform.CODEX,
        action_message_id="action-1",
        invocation=_spec(),
        effective_effort="high",
        isolation_evidence="fork_turns=none",
        visible_capabilities=(),
        actual_model="gpt-test",
    )

    with pytest.raises(WorkerAttestationError, match="ATTESTATION_EFFORT_MISMATCH"):
        attestation.validate(action_message_id="action-1", invocation=_spec())


def test_spawn_result_requires_exact_attestation_set() -> None:
    with pytest.raises(WorkerAttestationError, match="ATTESTATION_COUNT_MISMATCH"):
        validate_attestations(
            action_message_id="action-1",
            invocations=(_spec(),),
            attestations=[],
        )
