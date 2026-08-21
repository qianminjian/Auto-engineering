"""Phase 83 T462：真实 Worker outcome 的原子证据终结。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from auto_engineering.host import HostPlatform
from auto_engineering.host.execution_assembler import (
    HostEvidenceValidationError,
    HostExecutionAssembler,
    NativeWorkerOutcome,
    collect_host_evidence_violations,
)
from auto_engineering.host.spawn_contract import WorkerInvocationSpec
from auto_engineering.host.worker_attestation import (
    attestation_template,
    validate_attestations,
)


def _action(tmp_path: Path) -> dict:
    prompt = "审查当前实现"
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    prompt_ref = ".ae-state/artifacts/prompt.json"
    prompt_path = tmp_path / prompt_ref
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    invocation = WorkerInvocationSpec(
        worker_id="critic-0",
        role="critic",
        prompt_ref=prompt_ref,
        prompt_sha256=prompt_hash,
        requested_effort="xhigh",
        isolation="fresh_context",
        capabilities={"may_drive_loop": False, "may_spawn_workers": False},
        receipt_path=".ae-state/spawn-proofs/worker-token.json",
    )
    challenge = {
        "token": "total-token",
        "thread_id": "thread-1",
        "action_message_id": "action-1",
        "stage": "critic",
        "proof_role": "total",
        "status": "pending",
    }
    challenge_path = tmp_path / ".ae-state/spawn-challenges/total-token.json"
    challenge_path.parent.mkdir(parents=True)
    challenge_path.write_text(json.dumps(challenge), encoding="utf-8")
    return {
        "schema_version": "1.1",
        "message_id": "action-1",
        "thread_id": "thread-1",
        "stage": "critic",
        "spawn_proof_token": "total-token",
        "spawn": {
            "contract_version": "1.0",
            "count": 1,
            "parallel": False,
            "effort": "xhigh",
            "invocations": [invocation.to_dict()],
        },
        "host_execution": {
            "schema_version": "1.0",
            "platform": "codex",
            "workers": [{
                "worker_id": "critic-0",
                "native_worker_handle": None,
                "prompt_ref": prompt_ref,
                "receipt_path": invocation.receipt_path,
                "receipt": {
                    "status": "pending",
                    "stage": "critic",
                    "worker": "critic-0",
                    "requested_effort": "xhigh",
                    "actual_model": "unknown",
                },
                "attestation": attestation_template(
                    platform=HostPlatform.CODEX,
                    action_message_id="action-1",
                    invocation=invocation,
                ),
            }],
        },
    }


def test_finalize_atomically_builds_all_worker_evidence(tmp_path: Path) -> None:
    action = _action(tmp_path)
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"verdict": "MAJOR", "findings": ["P1"]},
        summary="发现一个主要问题",
        actual_model="gpt-5.6-sol",
    )
    result = HostExecutionAssembler(tmp_path).finalize(
        action=action,
        outcomes=[outcome],
        coordinator_payload={"verdict": "MAJOR", "findings": ["P1"]},
    )

    assert result["spawned"] is True
    assert result["message_type"] == "result"
    assert result["correlation_id"] == "thread-1"
    assert result["extensions"] == {}
    assert result["spawn_proof_token"] == "total-token"
    assert result["verdict"] == "MAJOR"
    plan_invocations = tuple(
        WorkerInvocationSpec.from_dict(item)
        for item in action["spawn"]["invocations"]
    )
    validate_attestations(
        action_message_id="action-1",
        invocations=plan_invocations,
        attestations=result["worker_attestations"],
    )
    worker_receipt = json.loads(
        (tmp_path / ".ae-state/spawn-proofs/worker-token.json").read_text()
    )
    assert worker_receipt["status"] == "completed"
    assert worker_receipt["native_worker_handle"] == "agent-123"
    total_proof = json.loads(
        (tmp_path / ".ae-state/spawn-proofs/total-token.json").read_text()
    )
    assert total_proof["status"] == "completed"
    assert total_proof["workers"] == ["critic-0"]
    journal = json.loads(
        (tmp_path / ".ae-state/host-runtime/outcomes/action-1.json").read_text()
    )
    assert journal["status"] == "committed"


def test_finalize_worker_timeout_builds_failure_transaction_without_success_evidence(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-timeout-1",
        status="timeout",
        payload={"error": "native wait deadline exceeded"},
        summary="HOST_AGENT_TIMEOUT",
        actual_model="gpt-5.6-sol",
        isolation_evidence="fork_context=false",
    )

    result = HostExecutionAssembler(tmp_path).finalize(
        action=action,
        outcomes=[outcome],
        coordinator_payload={"verdict": "APPROVE", "findings": []},
    )

    assert result["spawned"] is False
    assert result["spawn_error_code"] == "HOST_WORKER_TIMEOUT"
    assert result["spawn_retry_attempt"] == 1
    assert result["causation_id"] == action["message_id"]
    assert "verdict" not in result
    assert "worker_attestations" not in result
    assert not (tmp_path / ".ae-state/spawn-proofs/total-token.json").exists()
    assert not (tmp_path / ".ae-state/spawn-proofs/worker-token.json").exists()
    journal = json.loads(
        (tmp_path / ".ae-state/host-runtime/outcomes/action-1.json").read_text()
    )
    assert journal["status"] == "worker_failed"
    assert journal["failure_attempt"] == 1
    assert journal["result"] == result
    assert HostExecutionAssembler(tmp_path).restore_committed_result_to_file(
        action=action,
        result_path=Path("retry-result.json"),
    ) is None


def test_successful_retry_replaces_worker_failure_without_journal_conflict(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    assembler = HostExecutionAssembler(tmp_path)
    assembler.finalize(
        action=action,
        outcomes=[NativeWorkerOutcome(
            worker_id="critic-0",
            native_worker_handle="agent-timeout-1",
            status="timed_out",
            payload={"error": "deadline"},
            summary="deadline exceeded",
            actual_model="gpt-5.6-sol",
        )],
        coordinator_payload={},
    )

    result = assembler.finalize(
        action=action,
        outcomes=[NativeWorkerOutcome(
            worker_id="critic-0",
            native_worker_handle="agent-retry-2",
            status="completed",
            payload={"verdict": "APPROVE", "findings": []},
            summary="重试完成",
            actual_model="gpt-5.6-sol",
        )],
        coordinator_payload={"verdict": "APPROVE", "findings": []},
    )

    assert result["spawned"] is True
    journal = json.loads(
        (tmp_path / ".ae-state/host-runtime/outcomes/action-1.json").read_text()
    )
    assert journal["status"] == "committed"


def test_repeated_worker_timeout_increments_core_visible_attempt(tmp_path: Path) -> None:
    action = _action(tmp_path)
    assembler = HostExecutionAssembler(tmp_path)
    first = assembler.finalize(
        action=action,
        outcomes=[NativeWorkerOutcome(
            worker_id="critic-0", native_worker_handle="agent-1",
            status="timeout", payload={}, summary="deadline",
            actual_model="unknown",
        )],
        coordinator_payload={},
    )
    second = assembler.finalize(
        action=action,
        outcomes=[NativeWorkerOutcome(
            worker_id="critic-0", native_worker_handle="agent-2",
            status="timed_out", payload={}, summary="deadline",
            actual_model="unknown",
        )],
        coordinator_payload={},
    )

    assert first["spawn_retry_attempt"] == 1
    assert second["spawn_retry_attempt"] == 2


def test_finalize_requires_and_records_selected_codex_isolation_semantics(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    action["host_execution"]["native_worker_tools"] = {
        "selection": "first_complete_exposed_family",
        "families": [{
            "spawn": "multi_agent_v1__spawn_agent",
            "wait": "multi_agent_v1__wait_agent",
            "close": "multi_agent_v1__close_agent",
        }],
    }
    missing = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"verdict": "APPROVE"},
        summary="通过",
        actual_model="gpt-5.6-sol",
    )
    with pytest.raises(
        HostEvidenceValidationError,
        match="WORKER_ISOLATION_EVIDENCE_MISSING:critic-0",
    ):
        HostExecutionAssembler(tmp_path).finalize(
            action=action,
            outcomes=[missing],
            coordinator_payload={"verdict": "APPROVE"},
        )

    completed = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"verdict": "APPROVE"},
        summary="通过",
        actual_model="gpt-5.6-sol",
        isolation_evidence="fork_context=false",
    )
    result = HostExecutionAssembler(tmp_path).finalize(
        action=action,
        outcomes=[completed],
        coordinator_payload={"verdict": "APPROVE"},
    )

    assert result["worker_attestations"][0]["isolation_evidence"] == "fork_context=false"


def test_finalize_routes_boundary_payload_to_artifact_before_journal_commit(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-boundary",
        status="completed",
        payload={"notes": "x" * 3950},
        summary="完整结果见 ArtifactRef",
        actual_model="gpt-5.6-sol",
    )

    result = HostExecutionAssembler(tmp_path).finalize(
        action=action,
        outcomes=[outcome],
        coordinator_payload={"verdict": "APPROVE"},
    )

    receipt = json.loads(
        (tmp_path / ".ae-state/spawn-proofs/worker-token.json").read_text()
    )
    assert "payload" not in receipt
    assert receipt["artifact_ref"]["kind"] == "worker_report"
    assert receipt["native_worker_handle"] == "agent-boundary"
    assert collect_host_evidence_violations(
        project_root=tmp_path,
        action=action,
        result=result,
        receipt_limit=4096,
        summary_limit=2048,
    ) == ()
    journal = json.loads(
        (tmp_path / ".ae-state/host-runtime/outcomes/action-1.json").read_text()
    )
    assert journal["status"] == "committed"


def test_preflight_returns_all_violations_without_completing_proof(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    bad = NativeWorkerOutcome(
        worker_id="wrong-worker",
        native_worker_handle="",
        status="failed",
        payload={},
        summary="",
        actual_model="",
    )

    with pytest.raises(HostEvidenceValidationError) as caught:
        HostExecutionAssembler(tmp_path).finalize(
            action=action,
            outcomes=[bad],
            coordinator_payload={"verdict": "MAJOR"},
        )

    assert set(caught.value.violations) >= {
        "WORKER_SET_MISMATCH",
        "WORKER_NOT_COMPLETED:wrong-worker",
        "NATIVE_WORKER_HANDLE_MISSING:wrong-worker",
        "ACTUAL_MODEL_MISSING:wrong-worker",
    }
    assert not (tmp_path / ".ae-state/spawn-proofs/total-token.json").exists()


def test_finalize_is_idempotent_after_outcome_journal_commit(tmp_path: Path) -> None:
    action = _action(tmp_path)
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"verdict": "PASS"},
        summary="通过",
        actual_model="gpt-5.6-sol",
    )
    assembler = HostExecutionAssembler(tmp_path)

    first = assembler.finalize(
        action=action,
        outcomes=[outcome],
        coordinator_payload={"verdict": "PASS"},
    )
    receipt_before = (
        tmp_path / ".ae-state/spawn-proofs/worker-token.json"
    ).read_bytes()
    second = assembler.finalize(
        action=action,
        outcomes=[outcome],
        coordinator_payload={"verdict": "PASS"},
    )

    assert second == first
    assert (
        tmp_path / ".ae-state/spawn-proofs/worker-token.json"
    ).read_bytes() == receipt_before


def test_restore_committed_result_binds_active_action_and_materializes_file(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"verdict": "PASS"},
        summary="通过",
        actual_model="gpt-5.6-sol",
    )
    assembler = HostExecutionAssembler(tmp_path)
    expected = assembler.finalize(
        action=action,
        outcomes=[outcome],
        coordinator_payload={"verdict": "PASS"},
    )

    restored = assembler.restore_committed_result_to_file(
        action=action,
        result_path=Path(".ae-state/host-runtime/work/recovery/result.json"),
    )

    assert restored == expected
    assert json.loads(
        (tmp_path / ".ae-state/host-runtime/work/recovery/result.json").read_text()
    ) == expected


def test_restore_committed_result_rejects_mismatched_causation(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    journal = tmp_path / ".ae-state/host-runtime/outcomes/action-1.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({
        "schema_version": "1.0",
        "status": "committed",
        "action_message_id": "action-1",
        "result": {
            "message_type": "result",
            "causation_id": "another-action",
            "thread_id": action["thread_id"],
            "stage": action["stage"],
        },
    }))

    with pytest.raises(
        HostEvidenceValidationError,
        match="OUTCOME_JOURNAL_RESULT_IDENTITY_MISMATCH",
    ):
        HostExecutionAssembler(tmp_path).restore_committed_result_to_file(
            action=action,
            result_path=Path("result.json"),
        )


def test_finalize_reuses_worker_outcome_when_coordinator_payload_is_repaired(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"verdict": "PASS"},
        summary="通过",
        actual_model="gpt-5.6-sol",
    )
    assembler = HostExecutionAssembler(tmp_path)
    first = assembler.finalize(
        action=action,
        outcomes=[outcome],
        coordinator_payload={"verdict": "PASS", "findings": ["stale"]},
    )

    repaired = assembler.finalize(
        action=action,
        outcomes=[outcome],
        coordinator_payload={"verdict": "PASS", "findings": []},
    )

    assert repaired["findings"] == []
    assert repaired["message_id"] != first["message_id"]


def test_finalize_rejects_changed_worker_outcome_during_payload_repair(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    assembler = HostExecutionAssembler(tmp_path)
    original = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"verdict": "PASS"},
        summary="通过",
        actual_model="gpt-5.6-sol",
    )
    assembler.finalize(
        action=action,
        outcomes=[original],
        coordinator_payload={"verdict": "PASS"},
    )
    changed = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-456",
        status="completed",
        payload={"verdict": "PASS"},
        summary="通过",
        actual_model="gpt-5.6-sol",
    )

    with pytest.raises(HostEvidenceValidationError, match="OUTCOME_JOURNAL_CONFLICT"):
        assembler.finalize(
            action=action,
            outcomes=[changed],
            coordinator_payload={"verdict": "PASS", "findings": []},
        )


def test_stale_coordinator_payload_is_rejected_before_journal_commit(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    action["expected_format"] = {
        "verdict": "APPROVE | MAJOR",
        "findings": "array",
    }
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"verdict": "APPROVE", "findings": []},
        summary="通过",
        actual_model="gpt-5.6-sol",
    )

    with pytest.raises(HostEvidenceValidationError) as caught:
        HostExecutionAssembler(tmp_path).finalize(
            action=action,
            outcomes=[outcome],
            coordinator_payload={"component": "stale", "coverage_map": []},
        )

    assert set(caught.value.violations) == {
        "COORDINATOR_FIELD_UNEXPECTED:component",
        "COORDINATOR_FIELD_UNEXPECTED:coverage_map",
    }
    assert not (
        tmp_path / ".ae-state/host-runtime/outcomes/action-1.json"
    ).exists()


def test_completed_evidence_preflight_reports_all_missing_artifacts(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)

    violations = collect_host_evidence_violations(
        project_root=tmp_path,
        action=action,
        result={"spawned": True, "spawn_proof_token": "total-token"},
        receipt_limit=4096,
        summary_limit=2048,
    )

    assert set(violations) == {
        "SPAWN_PROOF_INCOMPLETE",
        "WORKER_ATTESTATIONS_MISSING",
        "WORKER_RECEIPT_MISSING:critic-0",
    }


def test_finalize_non_spawn_action_builds_protocol_envelope(tmp_path: Path) -> None:
    """非 spawn Action 的协议身份必须来自 active Action，而非宿主手工复制。"""

    action = {
        "schema_version": "1.1",
        "message_type": "action",
        "message_id": "gap-action-1",
        "thread_id": "thread-1",
        "tick": 7,
        "stage": "gap_scan",
        "correlation_id": "correlation-1",
    }

    result = HostExecutionAssembler(tmp_path).finalize(
        action=action,
        outcomes=[],
        coordinator_payload={
            "gaps": [],
            "scanned_sections": 4,
            "has_blocking": False,
        },
    )

    assert result == {
        "schema_version": "1.1",
        "message_type": "result",
        "message_id": result["message_id"],
        "causation_id": "gap-action-1",
        "thread_id": "thread-1",
        "tick": 7,
        "stage": "gap_scan",
        "correlation_id": "correlation-1",
        "extensions": {},
        "gaps": [],
        "scanned_sections": 4,
        "has_blocking": False,
    }
    assert (
        HostExecutionAssembler(tmp_path).finalize(
            action=action,
            outcomes=[],
            coordinator_payload={
                "gaps": [],
                "scanned_sections": 4,
                "has_blocking": False,
            },
        )
        == result
    )

    repaired = HostExecutionAssembler(tmp_path).finalize(
        action=action,
        outcomes=[],
        coordinator_payload={
            "gaps": [],
            "scanned_sections": 5,
            "has_blocking": False,
        },
    )
    assert repaired["scanned_sections"] == 5
    assert repaired["message_id"] != result["message_id"]


def test_finalize_gap_auto_decision_rebinds_core_owned_fields(tmp_path: Path) -> None:
    """线程策略是 Core 事实，宿主只能补充 Fill 的具体内容。"""

    action = {
        "schema_version": "1.1",
        "message_type": "action",
        "message_id": "gap-action-auto-1",
        "thread_id": "thread-1",
        "tick": 8,
        "stage": "gap_review",
        "correlation_id": "correlation-1",
        "auto_decision": {
            "gap_id": "GAP-A2",
            "resolution": "Fill",
            "decision_source": "thread_policy",
            "policy": "remaining_recommendations",
        },
    }

    result = HostExecutionAssembler(tmp_path).finalize(
        action=action,
        outcomes=[],
        coordinator_payload={
            "decision": {
                "gap_id": "stale-gap",
                "resolution": "Defer",
                "decision_source": "host_inference",
                "fill_content": "补齐设计所需的错误状态与恢复行为。",
            }
        },
    )

    assert result["decision"] == {
        "gap_id": "GAP-A2",
        "resolution": "Fill",
        "decision_source": "thread_policy",
        "policy": "remaining_recommendations",
        "fill_content": "补齐设计所需的错误状态与恢复行为。",
    }


def test_finalize_non_spawn_rejects_worker_outcomes(tmp_path: Path) -> None:
    action = {
        "schema_version": "1.1",
        "message_id": "developer-action-1",
        "thread_id": "thread-1",
        "tick": 2,
        "stage": "developer",
    }
    outcome = NativeWorkerOutcome(
        worker_id="unexpected",
        native_worker_handle="agent-1",
        status="completed",
        payload={},
        summary="unexpected",
        actual_model="gpt-5.6-sol",
    )

    with pytest.raises(HostEvidenceValidationError) as caught:
        HostExecutionAssembler(tmp_path).finalize(
            action=action,
            outcomes=[outcome],
            coordinator_payload={"completed_tasks": ["T1"]},
        )

    assert caught.value.violations == ("UNEXPECTED_WORKER_OUTCOMES",)


def test_finalize_to_file_rejects_path_outside_project(tmp_path: Path) -> None:
    action = {
        "schema_version": "1.1",
        "message_id": "gap-action-1",
        "thread_id": "thread-1",
        "tick": 1,
        "stage": "gap_scan",
    }

    with pytest.raises(HostEvidenceValidationError) as caught:
        HostExecutionAssembler(tmp_path).finalize_to_file(
            action=action,
            outcomes=[],
            coordinator_payload={"gaps": []},
            result_path=tmp_path.parent / "outside-result.json",
        )

    assert caught.value.violations == ("RESULT_OUTPUT_PATH_OUTSIDE_PROJECT",)
