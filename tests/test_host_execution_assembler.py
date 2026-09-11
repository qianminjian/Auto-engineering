"""Phase 83 T462：真实 Worker outcome 的原子证据终结。"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from auto_engineering.host import HostPlatform
from auto_engineering.host.execution_assembler import (
    HostEvidenceValidationError,
    HostExecutionAssembler,
    NativeWorkerOutcome,
    WorkerOutcomeCollectionError,
    collect_host_evidence_violations,
)
from auto_engineering.host.outcome_recovery import OutcomeRecoveryService
from auto_engineering.host.result_contract import ResultContractService
from auto_engineering.host.spawn_contract import WorkerInvocationSpec
from auto_engineering.host.worker_attestation import (
    attestation_template,
    validate_attestations,
)
from auto_engineering.host.worker_evidence import (
    HostEvidenceValidationError as WorkerEvidenceValidationError,
)
from auto_engineering.host.worker_evidence import (
    NativeWorkerOutcome as WorkerEvidenceOutcome,
)
from auto_engineering.host.worker_failure import WorkerFailureService


def test_worker_evidence_primitives_have_one_canonical_module() -> None:
    """Assembler 只重导出 evidence 原语，不能保留第二套定义。"""

    assert HostEvidenceValidationError is WorkerEvidenceValidationError
    assert NativeWorkerOutcome is WorkerEvidenceOutcome


def test_assembler_uses_one_outcome_recovery_service(tmp_path: Path) -> None:
    assembler = HostExecutionAssembler(tmp_path)

    assert isinstance(assembler._outcome_recovery, OutcomeRecoveryService)
    assert assembler._outcome_recovery.project_root == tmp_path.resolve()


def test_assembler_uses_one_result_contract_service(tmp_path: Path) -> None:
    assembler = HostExecutionAssembler(tmp_path)

    assert isinstance(assembler._result_contract, ResultContractService)


def test_assembler_uses_one_worker_failure_service(tmp_path: Path) -> None:
    assembler = HostExecutionAssembler(tmp_path)

    assert isinstance(assembler._worker_failure, WorkerFailureService)


def test_architect_coordinator_cannot_shrink_committed_worker_plan(
    tmp_path: Path,
) -> None:
    """Worker 的完整 Architect 计划不可被 Coordinator 修复为子集。"""

    action = _action(tmp_path)
    action.update({"action": "architect", "stage": "architect"})
    challenge_path = tmp_path / ".ae-state/spawn-challenges/total-token.json"
    challenge = json.loads(challenge_path.read_text(encoding="utf-8"))
    challenge["stage"] = "architect"
    challenge_path.write_text(json.dumps(challenge), encoding="utf-8")
    full_plan = [
        {
            "batch_id": "B1",
            "component": "Core",
            "tasks": [{"id": "B1-T1", "description": "实现 B1"}],
        },
        {
            "batch_id": "B2",
            "component": "Core",
            "tasks": [{"id": "B2-T1", "description": "实现 B2"}],
        },
    ]
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"plan": "完整计划", "file_list": [], "batch_plan": full_plan},
        summary="完整 Architect 计划",
        actual_model="gpt-5.6-sol",
    )

    with pytest.raises(
        HostEvidenceValidationError,
        match="ARCHITECT_RESULT_COVERAGE_LOSS",
    ):
        HostExecutionAssembler(tmp_path).finalize(
            action=action,
            outcomes=[outcome],
            coordinator_payload={
                "plan": "完整计划",
                "file_list": [],
                "batch_plan": [full_plan[0]],
            },
        )


def test_architect_finalize_records_worker_plan_manifest(tmp_path: Path) -> None:
    action = _action(tmp_path)
    action.update({"action": "architect", "stage": "architect"})
    challenge_path = tmp_path / ".ae-state/spawn-challenges/total-token.json"
    challenge = json.loads(challenge_path.read_text(encoding="utf-8"))
    challenge["stage"] = "architect"
    challenge_path.write_text(json.dumps(challenge), encoding="utf-8")
    plan = [{
        "batch_id": "B1",
        "component": "Core",
        "tasks": [{"id": "B1-T1", "description": "实现 B1"}],
    }]
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"plan": "计划", "file_list": [], "batch_plan": plan},
        summary="Architect 计划",
        actual_model="gpt-5.6-sol",
    )

    result = HostExecutionAssembler(tmp_path).finalize(
        action=action,
        outcomes=[outcome],
        coordinator_payload={"plan": "计划", "file_list": [], "batch_plan": plan},
    )

    coverage = result["extensions"]["architect_plan_coverage"]
    assert coverage["batch_ids"] == ["B1"]
    assert coverage["task_ids"] == ["B1-T1"]
    assert len(coverage["digest"]) == 64


def test_core_host_evidence_check_rejects_architect_plan_subset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = _action(tmp_path)
    action.update({"action": "architect", "stage": "architect"})
    challenge_path = tmp_path / ".ae-state/spawn-challenges/total-token.json"
    challenge = json.loads(challenge_path.read_text(encoding="utf-8"))
    challenge["stage"] = "architect"
    challenge_path.write_text(json.dumps(challenge), encoding="utf-8")
    proof_path = tmp_path / ".ae-state/spawn-proofs/total-token.json"
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(
        json.dumps({"status": "completed", "token": "total-token",
                    "thread_id": "thread-1", "action_message_id": "action-1",
                    "stage": "architect"}),
        encoding="utf-8",
    )
    invocation = action["spawn"]["invocations"][0]
    outcome_path = tmp_path / invocation["outcome_path"]
    outcome_path.parent.mkdir(parents=True, exist_ok=True)
    full_plan = [
        {"batch_id": "B1", "tasks": [{"id": "B1-T1"}]},
        {"batch_id": "B2", "tasks": [{"id": "B2-T1"}]},
    ]
    outcome_path.write_text(
        json.dumps({
            "worker_id": "critic-0",
            "status": "completed",
            "payload": {"batch_plan": full_plan},
            "summary": "Architect",
        }),
        encoding="utf-8",
    )
    receipt_path = tmp_path / invocation["receipt_path"]
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps({"worker": "critic-0", "native_worker_handle": "agent-123"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "auto_engineering.host.execution_assembler.validate_attestations",
        lambda **_: None,
    )
    monkeypatch.setattr(
        "auto_engineering.host.execution_assembler.validate_worker_receipt",
        lambda *args, **kwargs: None,
    )

    violations = collect_host_evidence_violations(
        project_root=tmp_path,
        action=action,
        result={
            "spawned": True,
            "spawn_proof_token": "total-token",
            "worker_attestations": [],
            "batch_plan": [full_plan[0]],
        },
        receipt_limit=4096,
        summary_limit=1024,
    )

    assert "ARCHITECT_RESULT_COVERAGE_LOSS" in violations


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
        outcome_path=".ae-state/host-runtime/worker-outcomes/worker-token.json",
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
                "outcome_path": invocation.outcome_path,
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
    assert journal["status"] == "prepared"


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


def test_finalize_missing_worker_output_builds_deterministic_failure(
    tmp_path: Path,
) -> None:
    """宿主没有写出任何 outcome 时，也必须形成可重试的失败事务。"""
    action = _action(tmp_path)
    result_path = tmp_path / "retry-result.json"
    result = HostExecutionAssembler(tmp_path).finalize_missing_worker_output(
        action=action,
        reason_code="HOST_WORKER_OUTPUT_MISSING",
        detail="Worker 已结束，但未产生 outcomes 或 Coordinator payload",
        result_path=result_path,
    )

    assert result["spawned"] is False
    assert result["spawn_error_code"] == "HOST_WORKER_FAILED"
    assert result["spawn_retry_attempt"] == 1
    assert "verdict" not in result
    journal = json.loads(
        (tmp_path / ".ae-state/host-runtime/outcomes/action-1.json").read_text()
    )
    assert journal["status"] == "worker_failed"
    assert journal["outcomes"][0]["status"] == "failed"
    assert journal["outcomes"][0]["payload"]["error_code"] == (
        "HOST_WORKER_OUTPUT_MISSING"
    )
    assert json.loads(result_path.read_text(encoding="utf-8")) == result


def test_finalize_missing_preserves_recorded_invalid_native_failure(
    tmp_path: Path,
) -> None:
    """已记录的 native invalid 失败不能被重新降级为 missing 并消耗重试预算。"""

    action = _action(tmp_path)
    outcomes_ref = ".ae-state/host-runtime/work/action-1/outcomes.json"
    action["host_execution"]["work_files"] = {"outcomes": outcomes_ref}
    outcomes_path = tmp_path / outcomes_ref
    outcomes_path.parent.mkdir(parents=True, exist_ok=True)
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="native-invalid",
        status="failed",
        payload={
            "error_code": "HOST_WORKER_OUTPUT_INVALID",
            "detail": "WORKER_NATIVE_RESULT_INVALID:critic-0",
            "native_output_available": True,
        },
        summary="HOST_WORKER_OUTPUT_INVALID:critic-0",
        actual_model="unreported",
        isolation_evidence="fork_context=false",
    )
    outcomes_path.write_text(
        json.dumps({"outcomes": [outcome.to_dict()]}),
        encoding="utf-8",
    )

    result = HostExecutionAssembler(tmp_path).finalize_missing_worker_output(
        action=action,
        reason_code="HOST_WORKER_OUTPUT_INVALID",
        result_path=tmp_path / ".ae-state/host-runtime/work/action-1/result.json",
    )

    assert result["spawned"] is False
    assert result["spawn_error_code"] == "HOST_WORKER_FAILED"
    assert result["spawn_retry_attempt"] == 1
    assert result["spawn_error"] == "HOST_WORKER_OUTPUT_INVALID:critic-0"


def test_missing_coordinator_recovers_completed_single_worker_artifact(
    tmp_path: Path,
) -> None:
    """Worker 已落盘但 Coordinator 崩溃时，失败分支不能遮蔽成功事实。"""
    action = _action(tmp_path)
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "native_worker_handle": "native-late",
        "status": "completed",
        "payload": {"verdict": "APPROVE", "findings": []},
        "summary": "Worker 已完成",
        "actual_model": "deterministic-host",
        "isolation_evidence": "fork_context=false",
    }), encoding="utf-8")

    result = HostExecutionAssembler(tmp_path).finalize_missing_worker_output(
        action=action,
        reason_code="HOST_WORKER_OUTPUT_MISSING",
        result_path=tmp_path / "recovered-result.json",
    )

    assert result["spawned"] is True
    assert result["verdict"] == "APPROVE"
    assert json.loads((tmp_path / "recovered-result.json").read_text()) == result
    journal = json.loads(
        (tmp_path / ".ae-state/host-runtime/outcomes/action-1.json").read_text()
    )
    assert journal["status"] == "prepared"


def test_late_completed_artifact_has_priority_over_previous_missing_failure(
    tmp_path: Path,
) -> None:
    """失败落盘后 Worker 晚到，成功事实必须优先完成同一 Action。"""

    action = _action(tmp_path)
    assembler = HostExecutionAssembler(tmp_path)
    first = assembler.finalize_missing_worker_output(
        action=action,
        reason_code="HOST_WORKER_OUTPUT_MISSING",
    )
    assert first["spawned"] is False

    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "native_worker_handle": "native-late-success",
        "status": "completed",
        "payload": {"verdict": "APPROVE", "findings": []},
        "summary": "晚到但已完成",
        "actual_model": "deterministic-host",
        "isolation_evidence": "fork_context=false",
    }), encoding="utf-8")

    result = assembler.finalize_missing_worker_output(
        action=action,
        reason_code="HOST_WORKER_OUTPUT_MISSING",
    )

    assert result["spawned"] is True
    assert result["verdict"] == "APPROVE"
    journal = json.loads(
        (tmp_path / ".ae-state/host-runtime/outcomes/action-1.json").read_text()
    )
    assert journal["status"] == "prepared"


def test_collect_worker_outcomes_from_private_worker_artifact(tmp_path: Path) -> None:
    action = _action(tmp_path)
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "native_worker_handle": "native-1",
        "status": "completed",
        "payload": {"verdict": "APPROVE"},
        "summary": "完成审查",
        "actual_model": "deterministic-host",
        "isolation_evidence": "fork_context=false",
    }), encoding="utf-8")

    outcomes_path = tmp_path / ".ae-state/host-runtime/work/outcomes.json"
    outcomes = HostExecutionAssembler(tmp_path).collect_worker_outcomes_from_artifacts(
        action=action,
        outcomes_path=outcomes_path,
    )

    assert outcomes[0].worker_id == "critic-0"
    assert json.loads(outcomes_path.read_text(encoding="utf-8"))["outcomes"][0][
        "native_worker_handle"
    ] == "native-1"


def test_record_worker_outcome_merges_business_artifact_with_host_fact(
    tmp_path: Path,
) -> None:
    """宿主命令负责合并事实，调用方无需手写共享 outcomes。"""

    action = _action(tmp_path)
    action["host_execution"]["work_files"] = {
        "outcomes": ".ae-state/host-runtime/work/outcomes.json",
    }
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "status": "completed",
        "payload": {"verdict": "APPROVE"},
        "summary": "业务结果",
    }), encoding="utf-8")

    recorded = HostExecutionAssembler(tmp_path).record_worker_outcome(
        action=action,
        worker_id="critic-0",
        native_worker_handle="native-host-1",
        status="completed",
        actual_model="host-model",
        isolation_evidence="fork_turns=none",
    )

    assert recorded["native_worker_handle"] == "native-host-1"
    outcomes = json.loads(
        (tmp_path / ".ae-state/host-runtime/work/outcomes.json").read_text()
    )["outcomes"]
    assert outcomes == [recorded]


def test_record_worker_outcome_routes_business_test_failure_to_worker_failure(
    tmp_path: Path,
) -> None:
    """测试失败不能被误记为 completed，也不能要求模型修改私有 outcome。"""

    action = _action(tmp_path)
    action["host_execution"]["work_files"] = {
        "outcomes": ".ae-state/host-runtime/work/outcomes.json",
    }
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_business = {
        "worker_id": "critic-0",
        "status": "completed",
        "payload": {
            "batch_id": "B1",
            "test_results": {"passed": 14, "failed": 1, "errors": 0},
            "red_evidence": ["VoiceResult 使用了错误的字段名"],
        },
        "summary": "发现业务测试失败",
    }
    private_path.write_text(json.dumps(private_business), encoding="utf-8")

    recorded = HostExecutionAssembler(tmp_path).record_worker_outcome(
        action=action,
        worker_id="critic-0",
        native_worker_handle="native-host-1",
        status="completed",
        actual_model="host-model",
        isolation_evidence="fork_turns=none",
    )

    assert recorded["status"] == "failed"
    assert recorded["payload"] == private_business["payload"]
    assert json.loads(private_path.read_text(encoding="utf-8")) == private_business
    assert json.loads(
        (tmp_path / ".ae-state/host-runtime/work/outcomes.json").read_text()
    )["outcomes"] == [recorded]

    result = HostExecutionAssembler(tmp_path).finalize(
        action=action,
        outcomes=[NativeWorkerOutcome(**recorded)],
        coordinator_payload={},
    )
    assert result["spawned"] is False
    assert result["spawn_error_code"] == "HOST_WORKER_FAILED"


def test_record_worker_outcome_repairs_host_only_shared_work_file(
    tmp_path: Path,
) -> None:
    """完整原生回写可以修复宿主提前污染的共享 outcomes 工作副本。"""

    action = _action(tmp_path)
    native_ref = ".ae-state/host-runtime/native-results/native.json"
    outcomes_ref = ".ae-state/host-runtime/work/outcomes.json"
    action["host_execution"]["work_files"] = {"outcomes": outcomes_ref}
    action["host_execution"]["workers"][0]["native_result_path"] = native_ref

    # 私有 outcome 完全缺失时，Host 才能从绑定的 native 业务对象恢复。
    outcomes_path = tmp_path / outcomes_ref
    outcomes_path.parent.mkdir(parents=True, exist_ok=True)
    outcomes_path.write_text(json.dumps({"outcomes": [{
        "worker_id": "critic-0",
        "status": "completed",
        "native_worker_handle": "stale-host-fact",
        "actual_model": "unreported",
        "isolation_evidence": "fork_turns=none",
    }]}), encoding="utf-8")
    native_path = tmp_path / native_ref
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text(json.dumps({
        "component": "Goal",
        "coverage_map": [],
        "missing_count": 0,
        "diverged_count": 0,
        "recheck_log": [],
    }), encoding="utf-8")

    recorded = HostExecutionAssembler(tmp_path).record_worker_outcome(
        action=action,
        worker_id="critic-0",
        native_worker_handle="native-host-1",
        native_result_file=native_path,
        status="completed",
        actual_model="unreported",
        isolation_evidence="fork_turns=none",
    )

    assert recorded["payload"]["component"] == "Goal"
    assert json.loads(outcomes_path.read_text(encoding="utf-8")) == {
        "outcomes": [recorded]
    }


def test_record_worker_outcome_ingests_native_agent_envelope_when_private_file_missing(
    tmp_path: Path,
) -> None:
    """原生 Agent 漏写私有文件时，唯一回写边界仍可安全完成交接。"""

    action = _action(tmp_path)
    native_ref = ".ae-state/host-runtime/native-results/native.json"
    action["host_execution"]["work_files"] = {
        "outcomes": ".ae-state/host-runtime/work/outcomes.json",
    }
    action["host_execution"]["workers"][0]["native_result_path"] = native_ref
    native_path = tmp_path / native_ref
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text(json.dumps({
        "agentId": "native-agent-1",
        "content": [{
            "type": "text",
            "text": "完成。\n```json\n"
            "{\"batch_id\":\"B1\",\"test_results\":{\"passed\":8}}\n"
            "```",
        }],
    }), encoding="utf-8")

    recorded = HostExecutionAssembler(tmp_path).record_worker_outcome(
        action=action,
        worker_id="critic-0",
        native_worker_handle="native-agent-1",
        native_result_file=native_path,
        status="completed",
        actual_model="unreported",
        isolation_evidence="fork_turns=none",
    )

    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private = json.loads(private_path.read_text(encoding="utf-8"))
    assert private == {
        "worker_id": "critic-0",
        "status": "completed",
        "payload": {
            "batch_id": "B1",
            "test_results": {"passed": 8},
        },
        "summary": "native_worker_result",
    }
    assert recorded["payload"] == private["payload"]


def test_stage_native_result_preserves_exact_envelope_atomically(
    tmp_path: Path,
) -> None:
    """Host 可把原生回包原样暂存到当前 Action 绑定路径。"""

    action = _action(tmp_path)
    native_ref = ".ae-state/host-runtime/native-results/native.json"
    action["host_execution"]["workers"][0]["native_result_path"] = native_ref
    native_path = tmp_path / native_ref
    raw_envelope = b'{\n  "result": {"batch_id": "B1"}\n}\n'

    HostExecutionAssembler(tmp_path).stage_native_result(
        action=action,
        worker_id="critic-0",
        native_result_file=native_path,
        raw_envelope=raw_envelope,
    )

    assert native_path.read_bytes() == raw_envelope


def test_record_only_recovery_view_reuses_plan_without_spawn(
    tmp_path: Path,
) -> None:
    """恢复视图隐藏 spawn 后，仍可回写同一 Worker 的宿主事实。"""

    action = _action(tmp_path)
    invocation = action["spawn"]["invocations"][0]
    native_ref = ".ae-state/host-runtime/native-results/recovery.json"
    outcomes_ref = ".ae-state/host-runtime/work/recovery-outcomes.json"
    action["host_execution"]["work_files"] = {"outcomes": outcomes_ref}
    action["host_execution"]["workers"][0]["native_result_path"] = native_ref
    action["host_execution"]["recovery"] = {
        "schema_version": "1.0",
        "status": "worker_attestation_pending",
        "spawn_permitted": False,
        "record_plan": deepcopy(action["spawn"]),
    }
    action.pop("spawn")
    private_path = tmp_path / invocation["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": invocation["worker_id"],
        "status": "completed",
        "payload": {"verdict": "APPROVE"},
        "summary": "恢复回写",
    }), encoding="utf-8")

    assembler = HostExecutionAssembler(tmp_path)
    assembler.stage_native_result(
        action=action,
        worker_id=invocation["worker_id"],
        native_result_file=tmp_path / native_ref,
        raw_envelope=b'{"status":"completed"}',
    )
    recorded = assembler.record_worker_outcome(
        action=action,
        worker_id=invocation["worker_id"],
        native_worker_handle="recovered-native-worker",
        status="completed",
        actual_model="gpt-5.6-sol",
        isolation_evidence="fork_turns=none",
    )

    assert recorded["native_worker_handle"] == "recovered-native-worker"
    assert json.loads((tmp_path / outcomes_ref).read_text())["outcomes"] == [
        recorded
    ]


def test_finalize_treats_attestation_recovery_as_worker_action(
    tmp_path: Path,
) -> None:
    """恢复 Action 最终化仍必须生成 Worker 证据，不能降级为 inline。"""

    action = _action(tmp_path)
    action["host_execution"]["recovery"] = {
        "schema_version": "1.0",
        "status": "worker_attestation_pending",
        "spawn_permitted": False,
        "record_plan": deepcopy(action["spawn"]),
    }
    action.pop("spawn")
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="recovered-native-worker",
        status="completed",
        payload={"verdict": "APPROVE"},
        summary="恢复完成",
        actual_model="gpt-5.6-sol",
        isolation_evidence="fork_turns=none",
    )

    result = HostExecutionAssembler(tmp_path).finalize(
        action=action,
        outcomes=[outcome],
        coordinator_payload={"verdict": "APPROVE"},
    )

    assert result["spawned"] is True
    assert result["worker_attestations"][0]["worker_id"] == "critic-0"


def test_stage_native_result_rejects_unbound_path(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    unbound_path = tmp_path / ".ae-state/host-runtime/native-results/other.json"

    with pytest.raises(
        HostEvidenceValidationError,
        match="WORKER_NATIVE_RESULT_PATH_INVALID:critic-0",
    ):
        HostExecutionAssembler(tmp_path).stage_native_result(
            action=action,
            worker_id="critic-0",
            native_result_file=unbound_path,
            raw_envelope=b'{"batch_id":"B1"}',
        )


def test_stage_native_result_rejects_empty_envelope(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    native_ref = ".ae-state/host-runtime/native-results/native.json"
    action["host_execution"]["workers"][0]["native_result_path"] = native_ref

    with pytest.raises(
        HostEvidenceValidationError,
        match="WORKER_NATIVE_RESULT_EMPTY:critic-0",
    ):
        HostExecutionAssembler(tmp_path).stage_native_result(
            action=action,
            worker_id="critic-0",
            native_result_file=tmp_path / native_ref,
            raw_envelope=b" \n",
        )


def test_record_worker_outcome_ingests_codex_result_wrapper_when_private_file_missing(
    tmp_path: Path,
) -> None:
    """Codex 原生回包的单层 result 包装必须在 Host 边界解包。"""

    action = _action(tmp_path)
    native_ref = ".ae-state/host-runtime/native-results/native.json"
    action["host_execution"]["work_files"] = {
        "outcomes": ".ae-state/host-runtime/work/outcomes.json",
    }
    action["host_execution"]["workers"][0]["native_result_path"] = native_ref
    native_path = tmp_path / native_ref
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text(json.dumps({
        "result": {
            "plan": "先实现 API，再实现页面",
            "batch_plan": [{"batch_id": "B1", "tasks": ["api"]}],
            "contracts": {"clone-api": {"kind": "function"}},
            "file_list": ["src/voiceCloneApi.ts"],
            "obligations": [{"id": "O1", "summary": "实现 API"}],
            "decision_impacts": [],
        },
    }), encoding="utf-8")

    recorded = HostExecutionAssembler(tmp_path).record_worker_outcome(
        action=action,
        worker_id="critic-0",
        native_worker_handle="native-codex-worker-1",
        native_result_file=native_path,
        status="completed",
        actual_model="unreported",
        isolation_evidence="fork_turns=none",
    )

    assert recorded["payload"]["plan"] == "先实现 API，再实现页面"
    assert recorded["payload"]["batch_plan"][0]["batch_id"] == "B1"
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    assert json.loads(private_path.read_text(encoding="utf-8"))["payload"] == recorded[
        "payload"
    ]


def test_record_worker_outcome_normalizes_missing_native_summary_metadata(
    tmp_path: Path,
) -> None:
    """原生业务 envelope 可省略非业务 summary，由 Host 确定性补齐。"""

    action = _action(tmp_path)
    native_ref = ".ae-state/host-runtime/native-results/native.json"
    action["host_execution"]["workers"][0]["native_result_path"] = native_ref
    native_path = tmp_path / native_ref
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "status": "completed",
        "payload": {"assessment": "Needs rework", "findings": []},
    }), encoding="utf-8")

    recorded = HostExecutionAssembler(tmp_path).record_worker_outcome(
        action=action,
        worker_id="critic-0",
        native_worker_handle="native-critic-1",
        native_result_file=native_path,
        status="completed",
        actual_model="unreported",
        isolation_evidence="fork_turns=none",
    )

    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    assert json.loads(private_path.read_text(encoding="utf-8")) == {
        "worker_id": "critic-0",
        "status": "completed",
        "payload": {"assessment": "Needs rework", "findings": []},
        "summary": "native_worker_result",
    }
    assert recorded["payload"]["assessment"] == "Needs rework"


def test_record_worker_outcome_normalizes_missing_private_summary_metadata(
    tmp_path: Path,
) -> None:
    """私有 envelope 缺少非业务 summary 时也由唯一边界确定性补齐。"""

    action = _action(tmp_path)
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "status": "completed",
        "payload": {"assessment": "Needs rework", "findings": []},
    }), encoding="utf-8")

    recorded = HostExecutionAssembler(tmp_path).record_worker_outcome(
        action=action,
        worker_id="critic-0",
        native_worker_handle="native-critic-1",
        native_result_file=None,
        status="completed",
        actual_model="unreported",
        isolation_evidence="fork_turns=none",
    )

    assert json.loads(private_path.read_text(encoding="utf-8")) == {
        "worker_id": "critic-0",
        "status": "completed",
        "payload": {"assessment": "Needs rework", "findings": []},
    }
    assert recorded["payload"]["assessment"] == "Needs rework"


def test_record_worker_outcome_rejects_nested_codex_result_wrapper(
    tmp_path: Path,
) -> None:
    """多层包装不属于当前原生合同，不能被宽松递归解析。"""

    action = _action(tmp_path)
    native_ref = ".ae-state/host-runtime/native-results/native.json"
    action["host_execution"]["workers"][0]["native_result_path"] = native_ref
    native_path = tmp_path / native_ref
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text(json.dumps({
        "result": {"result": {"plan": "ambiguous"}},
    }), encoding="utf-8")

    with pytest.raises(
        HostEvidenceValidationError,
        match="WORKER_NATIVE_RESULT_INVALID:critic-0",
    ):
        HostExecutionAssembler(tmp_path).record_worker_outcome(
            action=action,
            worker_id="critic-0",
            native_worker_handle="native-codex-worker-1",
            native_result_file=native_path,
            status="completed",
            actual_model="unreported",
            isolation_evidence="fork_turns=none",
        )


def test_record_worker_outcome_parses_nested_json_business_object(
    tmp_path: Path,
) -> None:
    """完整嵌套业务对象不能被正则在内层右括号处截断。"""

    action = _action(tmp_path)
    native_ref = ".ae-state/host-runtime/native-results/native.json"
    action["host_execution"]["workers"][0]["native_result_path"] = native_ref
    native_path = tmp_path / native_ref
    native_path.parent.mkdir(parents=True, exist_ok=True)
    business = {
        "verdict": "APPROVE",
        "findings": [{"path": "src/App.tsx", "details": {"line": 12}}],
    }
    native_path.write_text(json.dumps({
        "content": [{
            "type": "text",
            "text": f"完成。```json\n{json.dumps(business)}\n```",
        }],
    }), encoding="utf-8")

    recorded = HostExecutionAssembler(tmp_path).record_worker_outcome(
        action=action,
        worker_id="critic-0",
        native_worker_handle="native-critic-nested",
        native_result_file=native_path,
        status="completed",
        actual_model="unreported",
        isolation_evidence="fork_turns=none",
    )

    assert recorded["payload"] == business


def test_record_worker_outcome_rejects_ambiguous_top_level_json_objects(
    tmp_path: Path,
) -> None:
    """正文含两个顶层对象时必须拒绝，不能猜测业务结果。"""

    action = _action(tmp_path)
    native_ref = ".ae-state/host-runtime/native-results/native.json"
    action["host_execution"]["workers"][0]["native_result_path"] = native_ref
    native_path = tmp_path / native_ref
    native_path.parent.mkdir(parents=True, exist_ok=True)
    first = {"verdict": "APPROVE", "note": "literal } brace"}
    second = {"verdict": "REJECT"}
    native_path.write_text(json.dumps({
        "content": [{
            "type": "text",
            "text": f"{json.dumps(first)}\n补充说明\n{json.dumps(second)}",
        }],
    }), encoding="utf-8")

    with pytest.raises(
        HostEvidenceValidationError,
        match="WORKER_NATIVE_RESULT_INVALID:critic-0",
    ):
        HostExecutionAssembler(tmp_path).record_worker_outcome(
            action=action,
            worker_id="critic-0",
            native_worker_handle="native-critic-ambiguous",
            native_result_file=native_path,
            status="completed",
            actual_model="unreported",
            isolation_evidence="fork_turns=none",
        )


def test_record_worker_outcome_rejects_malformed_private_file_without_fallback(
    tmp_path: Path,
) -> None:
    """私有文件格式损坏时必须保留当前 Action，不能启用第二条业务路径。"""

    action = _action(tmp_path)
    native_ref = ".ae-state/host-runtime/native-results/native.json"
    action["host_execution"]["work_files"] = {
        "outcomes": ".ae-state/host-runtime/work/outcomes.json",
    }
    action["host_execution"]["workers"][0]["native_result_path"] = native_ref
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    malformed_private = {"batch_id": "private-but-unwrapped"}
    private_path.write_text(json.dumps(malformed_private), encoding="utf-8")
    native_path = tmp_path / native_ref
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text(json.dumps({
        "content": [{
            "type": "text",
            "text": '{"batch_id":"native-authoritative"}',
        }],
    }), encoding="utf-8")

    with pytest.raises(
        HostEvidenceValidationError,
        match="WORKER_BUSINESS_ARTIFACT_INVALID:critic-0",
    ):
        HostExecutionAssembler(tmp_path).record_worker_outcome(
            action=action,
            worker_id="critic-0",
            native_worker_handle="native-agent-1",
            native_result_file=native_path,
            status="completed",
            actual_model="unreported",
            isolation_evidence="fork_turns=none",
        )

    assert json.loads(private_path.read_text(encoding="utf-8")) == malformed_private


def test_record_invalid_worker_failure_preserves_private_artifact_and_finalizes_failure(
    tmp_path: Path,
) -> None:
    """非法私有产物只转为宿主失败事实，不能被 native 回包重写。"""

    action = _action(tmp_path)
    action["host_execution"]["work_files"] = {
        "outcomes": ".ae-state/host-runtime/work/outcomes.json",
    }
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    malformed_private = {"batch_id": "private-but-invalid"}
    private_path.write_text(json.dumps(malformed_private), encoding="utf-8")

    assembler = HostExecutionAssembler(tmp_path)
    recorded = assembler.record_invalid_worker_failure(
        action=action,
        worker_id="critic-0",
        native_worker_handle="native-agent-1",
        actual_model="sonnet",
        isolation_evidence="fresh_context",
        detail="WORKER_BUSINESS_ARTIFACT_INVALID:critic-0",
    )

    assert recorded["status"] == "failed"
    assert recorded["payload"]["error_code"] == "HOST_WORKER_OUTPUT_INVALID"
    shared = json.loads(
        (tmp_path / ".ae-state/host-runtime/work/outcomes.json").read_text()
    )
    assert shared["outcomes"] == [recorded]
    assert json.loads(private_path.read_text(encoding="utf-8")) == malformed_private

    result = assembler.finalize(
        action=action,
        outcomes=[NativeWorkerOutcome(**recorded)],
        coordinator_payload={},
    )
    assert result["spawned"] is False
    assert result["spawn_error_code"] == "HOST_WORKER_FAILED"


def test_record_worker_outcome_rejects_bare_private_payload_before_native_summary(
    tmp_path: Path,
) -> None:
    """已存在的裸 payload 不得退回 native 摘要或被隐式修复。"""

    action = _action(tmp_path)
    native_ref = ".ae-state/host-runtime/native-results/native.json"
    action["host_execution"]["workers"][0]["native_result_path"] = native_ref
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "plan": "裸业务结果",
        "batch_plan": [{"batch_id": "B1"}],
    }), encoding="utf-8")
    native_path = tmp_path / native_ref
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text(json.dumps({
        "status": "completed",
        "agentId": "native-agent-summary-only",
        "content": [{
            "type": "text",
            "text": "Worker completed; the business result was written to outcome_path.",
        }],
    }), encoding="utf-8")

    with pytest.raises(
        HostEvidenceValidationError,
        match="WORKER_BUSINESS_ARTIFACT_INVALID:critic-0",
    ):
        HostExecutionAssembler(tmp_path).record_worker_outcome(
            action=action,
            worker_id="critic-0",
            native_worker_handle="native-agent-summary-only",
            native_result_file=native_path,
            status="completed",
            actual_model="unreported",
            isolation_evidence="fresh_context",
        )


def test_record_worker_outcome_normalizes_expected_bare_private_payload(
    tmp_path: Path,
) -> None:
    """Worker 已写出完整业务字段时，唯一回写边界可确定性补 envelope。"""

    action = _action(tmp_path)
    action["expected_format"] = {
        "batch_id": "string",
        "files_changed": "[string]",
        "test_results": "object",
    }
    native_ref = ".ae-state/host-runtime/native-results/native.json"
    action["host_execution"]["workers"][0]["native_result_path"] = native_ref
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    bare_payload = {
        "batch_id": "B1",
        "files_changed": ["src/counter.py"],
        "test_results": {"passed": 14, "failed": 0, "total": 14},
    }
    private_path.write_text(json.dumps(bare_payload), encoding="utf-8")
    native_path = tmp_path / native_ref
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text(json.dumps({"content": [{"type": "text", "text": "done"}]}), encoding="utf-8")

    recorded = HostExecutionAssembler(tmp_path).record_worker_outcome(
        action=action,
        worker_id="critic-0",
        native_worker_handle="native-agent-summary-only",
        native_result_file=native_path,
        status="completed",
        actual_model="unreported",
        isolation_evidence="fork_turns=none",
    )

    assert recorded["payload"] == bare_payload
    assert recorded["status"] == "completed"
    assert json.loads(private_path.read_text(encoding="utf-8")) == bare_payload


def test_record_worker_outcome_rejects_ambiguous_native_agent_result(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    native_ref = ".ae-state/host-runtime/native-results/native.json"
    action["host_execution"]["workers"][0]["native_result_path"] = native_ref
    native_path = tmp_path / native_ref
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text(json.dumps({
        "content": [{"type": "text", "text": "{} {}"}],
    }), encoding="utf-8")

    with pytest.raises(
        HostEvidenceValidationError,
        match="WORKER_NATIVE_RESULT_INVALID:critic-0",
    ):
        HostExecutionAssembler(tmp_path).record_worker_outcome(
            action=action,
            worker_id="critic-0",
            native_worker_handle="native-agent-1",
            native_result_file=native_path,
            status="completed",
            actual_model="unreported",
            isolation_evidence="fork_turns=none",
        )


@pytest.mark.parametrize("business_status", ["success", "ok", "complete"])
def test_record_worker_outcome_normalizes_completion_aliases(
    tmp_path: Path,
    business_status: str,
) -> None:
    """模型常用的成功别名必须在唯一交接边界归一为 completed。"""

    action = _action(tmp_path)
    action["host_execution"]["work_files"] = {
        "outcomes": ".ae-state/host-runtime/work/outcomes.json",
    }
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "status": business_status,
        "payload": {"verdict": "APPROVE"},
        "summary": "业务结果",
    }), encoding="utf-8")

    recorded = HostExecutionAssembler(tmp_path).record_worker_outcome(
        action=action,
        worker_id="critic-0",
        native_worker_handle="native-host-1",
        status="completed",
        actual_model="host-model",
        isolation_evidence="fork_turns=none",
    )

    assert recorded["status"] == "completed"
    assert json.loads(
        (tmp_path / ".ae-state/host-runtime/work/outcomes.json").read_text()
    )["outcomes"][0]["status"] == "completed"


def test_record_worker_outcome_rejects_completed_without_native_handle(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "status": "completed",
        "payload": {},
        "summary": "完成",
    }), encoding="utf-8")

    with pytest.raises(
        HostEvidenceValidationError,
        match="NATIVE_WORKER_HANDLE_MISSING:critic-0",
    ):
        HostExecutionAssembler(tmp_path).record_worker_outcome(
            action=action,
            worker_id="critic-0",
            native_worker_handle=None,
            status="completed",
        )


def test_record_worker_outcome_rejects_explicit_unreported_handle_for_completed(
    tmp_path: Path,
) -> None:
    """固定 argv 模板的缺失句柄哨兵不能伪装成 completed 事实。"""

    action = _action(tmp_path)
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "status": "completed",
        "payload": {},
        "summary": "完成",
    }), encoding="utf-8")

    with pytest.raises(
        HostEvidenceValidationError,
        match="NATIVE_WORKER_HANDLE_MISSING:critic-0",
    ):
        HostExecutionAssembler(tmp_path).record_worker_outcome(
            action=action,
            worker_id="critic-0",
            native_worker_handle="unreported",
            status="completed",
            isolation_evidence="fork_turns=none",
        )


def test_record_worker_outcome_rejects_unknown_private_business_fields(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "status": "completed",
        "payload": {},
        "summary": "完成",
        "execution_generation": 1,
    }), encoding="utf-8")

    with pytest.raises(
        HostEvidenceValidationError,
        match="WORKER_BUSINESS_BOUNDARY_VIOLATION:critic-0",
    ):
        HostExecutionAssembler(tmp_path).record_worker_outcome(
            action=action,
            worker_id="critic-0",
            native_worker_handle="native-host-1",
            status="completed",
        )


def test_record_worker_outcome_requires_actual_isolation_evidence(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "status": "completed",
        "payload": {},
        "summary": "完成",
    }), encoding="utf-8")

    with pytest.raises(
        HostEvidenceValidationError,
        match="NATIVE_ISOLATION_EVIDENCE_MISSING:critic-0",
    ):
        HostExecutionAssembler(tmp_path).record_worker_outcome(
            action=action,
            worker_id="critic-0",
            native_worker_handle="native-host-1",
            status="completed",
        )


def test_record_worker_outcome_rejects_host_business_status_conflict(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "status": "failed",
        "payload": {},
        "summary": "Worker 失败",
    }), encoding="utf-8")

    with pytest.raises(
        HostEvidenceValidationError,
        match="WORKER_STATUS_CONFLICT:critic-0",
    ):
        HostExecutionAssembler(tmp_path).record_worker_outcome(
            action=action,
            worker_id="critic-0",
            native_worker_handle="native-host-1",
            status="completed",
            isolation_evidence="fork_turns=none",
        )


def test_record_worker_outcome_is_idempotent_and_rejects_conflicting_retry(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    action["host_execution"]["work_files"] = {
        "outcomes": ".ae-state/host-runtime/work/outcomes.json",
    }
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "status": "completed",
        "payload": {"verdict": "APPROVE"},
        "summary": "业务结果",
    }), encoding="utf-8")
    assembler = HostExecutionAssembler(tmp_path)
    first = assembler.record_worker_outcome(
        action=action,
        worker_id="critic-0",
        native_worker_handle="native-host-1",
        status="completed",
        actual_model="host-model",
        isolation_evidence="fork_turns=none",
    )
    assert assembler.record_worker_outcome(
        action=action,
        worker_id="critic-0",
        native_worker_handle="native-host-1",
        status="completed",
        actual_model="host-model",
        isolation_evidence="fork_turns=none",
    ) == first
    with pytest.raises(
        HostEvidenceValidationError,
        match="OUTCOMES_CONFLICT:critic-0",
    ):
        assembler.record_worker_outcome(
            action=action,
            worker_id="critic-0",
            native_worker_handle="different-native-host",
            status="completed",
            actual_model="host-model",
            isolation_evidence="fork_turns=none",
        )


def test_record_worker_outcome_allows_same_generation_host_model_placeholder_repair(
    tmp_path: Path,
) -> None:
    """同一原生事实仅修正模型占位值时，回写必须保持幂等。"""

    action = _action(tmp_path)
    action["execution_generation"] = 1
    action["fencing_token"] = "a" * 64
    action["host_execution"]["workers"][0].update({
        "execution_generation": 1,
        "fencing_token": "b" * 64,
    })
    action["host_execution"]["work_files"] = {
        "outcomes": ".ae-state/host-runtime/work/outcomes.json",
    }
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "status": "failed",
        "payload": {"test_results": {"passed": 1, "failed": 1, "total": 2}},
        "summary": "业务失败",
    }), encoding="utf-8")

    assembler = HostExecutionAssembler(tmp_path)
    first = assembler.record_worker_outcome(
        action=action,
        worker_id="critic-0",
        native_worker_handle="native-host-1",
        status="failed",
        actual_model="unreported",
        isolation_evidence="fork_turns=none",
    )

    repaired = assembler.record_worker_outcome(
        action=action,
        worker_id="critic-0",
        native_worker_handle="native-host-1",
        status="failed",
        actual_model="unknown",
        isolation_evidence="fork_turns=none",
    )

    assert repaired["native_worker_handle"] == first["native_worker_handle"]
    assert repaired["payload"] == first["payload"]
    assert json.loads(
        (tmp_path / ".ae-state/host-runtime/work/outcomes.json").read_text()
    )["outcomes"] == [repaired]


def test_record_worker_outcome_replaces_failed_prior_generation_on_retry(
    tmp_path: Path,
) -> None:
    """更高代的合法重试必须替换同一 Action 的旧失败事实。"""

    first_action = _action(tmp_path)
    first_action["execution_generation"] = 1
    first_action["fencing_token"] = "a" * 64
    first_action["host_execution"]["workers"][0].update({
        "execution_generation": 1,
        "fencing_token": "b" * 64,
    })
    first_action["host_execution"]["work_files"] = {
        "outcomes": ".ae-state/host-runtime/work/outcomes.json",
    }
    first_private_path = (
        tmp_path / first_action["spawn"]["invocations"][0]["outcome_path"]
    )
    first_private_path.parent.mkdir(parents=True, exist_ok=True)
    first_private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "status": "failed",
        "payload": {"error": "temporary host failure"},
        "summary": "第一代失败",
    }), encoding="utf-8")
    assembler = HostExecutionAssembler(tmp_path)
    assembler.record_worker_outcome(
        action=first_action,
        worker_id="critic-0",
        native_worker_handle="native-failed",
        status="failed",
        actual_model="host-model",
        isolation_evidence="fork_turns=none",
    )

    retry_action = deepcopy(first_action)
    retry_action["execution_generation"] = 2
    retry_action["fencing_token"] = "c" * 64
    retry_action["host_execution"]["workers"][0].update({
        "execution_generation": 2,
        "fencing_token": "d" * 64,
        "outcome_path": (
            ".ae-state/host-runtime/worker-outcomes/worker-token-g2.json"
        ),
    })
    retry_private_path = (
        tmp_path / retry_action["host_execution"]["workers"][0]["outcome_path"]
    )
    retry_private_path.parent.mkdir(parents=True, exist_ok=True)
    retry_private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "status": "completed",
        "payload": {"verdict": "APPROVE"},
        "summary": "第二代成功",
    }), encoding="utf-8")

    replaced = assembler.record_worker_outcome(
        action=retry_action,
        worker_id="critic-0",
        native_worker_handle="native-completed",
        status="completed",
        actual_model="host-model",
        isolation_evidence="fork_turns=none",
    )

    assert replaced["status"] == "completed"
    assert replaced["execution_generation"] == 2
    outcomes = json.loads(
        (tmp_path / ".ae-state/host-runtime/work/outcomes.json").read_text()
    )
    assert outcomes["outcomes"] == [replaced]


def test_collect_rejects_noncanonical_worker_artifact_layout(
    tmp_path: Path,
) -> None:
    """当前 Worker 只能从 invocation 绑定的 canonical 路径读取产物。"""
    from auto_engineering.host.path_contract import action_key_for

    action = _action(tmp_path)
    legacy_path = (
        tmp_path / ".ae-state/host-runtime/worker-outcomes"
        / action_key_for("action-1") / "outcome-critic-0.json"
    )
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "native_worker_handle": "native-legacy",
        "status": "completed",
        "payload": {"verdict": "APPROVE"},
        "summary": "旧布局结果",
        "actual_model": "deterministic-host",
    }), encoding="utf-8")

    with pytest.raises(
        WorkerOutcomeCollectionError,
        match="HOST_WORKER_OUTPUT_MISSING:critic-0",
    ):
        HostExecutionAssembler(tmp_path).collect_worker_outcomes_from_artifacts(
            action=action,
            outcomes_path=tmp_path / "outcomes.json",
        )
    assert legacy_path.is_file()


def test_collect_worker_outcomes_reports_missing_private_artifact(tmp_path: Path) -> None:
    with pytest.raises(WorkerOutcomeCollectionError, match="HOST_WORKER_OUTPUT_MISSING:critic-0"):
        HostExecutionAssembler(tmp_path).collect_worker_outcomes_from_artifacts(
            action=_action(tmp_path),
            outcomes_path=tmp_path / "outcomes.json",
        )


def test_finalize_preserves_private_business_vs_host_attestation_failure(
    tmp_path: Path,
) -> None:
    """私有业务产物存在但未回写宿主事实时，诊断不得伪装成业务产物缺失。"""
    action = _action(tmp_path)
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "status": "completed",
        "payload": {"verdict": "APPROVE"},
        "summary": "完成",
    }), encoding="utf-8")

    result = HostExecutionAssembler(tmp_path).finalize_missing_worker_output(
        action=action,
        reason_code="HOST_WORKER_ATTESTATION_MISSING",
        detail="private_business_artifact_only",
    )

    assert result["spawned"] is False
    assert result["spawn_error_code"] == "HOST_WORKER_FAILED"
    assert result["spawn_error"] == (
        "HOST_WORKER_ATTESTATION_MISSING: private_business_artifact_only"
    )


def test_collect_rejects_unreported_native_handle_for_completed_worker(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "native_worker_handle": "unreported:critic-0",
        "status": "completed",
        "payload": {"verdict": "APPROVE"},
        "summary": "完成",
        "actual_model": "unreported",
    }), encoding="utf-8")

    with pytest.raises(
        WorkerOutcomeCollectionError,
        match="HOST_WORKER_OUTPUT_INVALID:critic-0:native_handle_unreported",
    ):
        HostExecutionAssembler(tmp_path).collect_worker_outcomes_from_artifacts(
            action=action,
            outcomes_path=tmp_path / "outcomes.json",
        )


def test_collect_rejects_private_business_artifact_without_host_attestation(
    tmp_path: Path,
) -> None:
    """Worker 业务产物不能被错误升级成宿主成功证据。"""

    action = _action(tmp_path)
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "status": "completed",
        "payload": {"verdict": "APPROVE"},
        "summary": "业务分析完成",
    }), encoding="utf-8")

    with pytest.raises(
        WorkerOutcomeCollectionError,
        match="HOST_WORKER_ATTESTATION_MISSING:critic-0:private_business_artifact_only",
    ):
        HostExecutionAssembler(tmp_path).collect_worker_outcomes_from_artifacts(
            action=action,
            outcomes_path=tmp_path / ".ae-state/work/outcomes.json",
        )


def test_collect_worker_outcomes_rejects_stale_execution_fence(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    action["host_execution"]["workers"][0].update({
        "execution_generation": 2,
        "fencing_token": "f" * 64,
    })
    private_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": "critic-0",
        "native_worker_handle": "late-agent",
        "status": "completed",
        "payload": {"verdict": "PASS"},
        "summary": "late result",
        "actual_model": "unreported",
        "execution_generation": 1,
        "fencing_token": "e" * 64,
    }), encoding="utf-8")

    with pytest.raises(
        WorkerOutcomeCollectionError,
        match="HOST_WORKER_OUTPUT_STALE:critic-0",
    ):
        HostExecutionAssembler(tmp_path).collect_worker_outcomes_from_artifacts(
            action=action,
            outcomes_path=tmp_path / "outcomes.json",
        )


def test_worker_timeout_bypasses_architect_business_contract(
    tmp_path: Path,
) -> None:
    """Worker 失败先落失败 Result，不能被空 Architect payload 的契约拦截。"""
    action = _action(tmp_path)
    action["stage"] = "architect"
    action["result_contract"] = {
        "schema_version": "1.0",
        "required": ["plan", "file_list", "batch_plan"],
        "properties": {
            "plan": {"type": "string"},
            "file_list": {"type": "array"},
            "batch_plan": {"type": "array"},
        },
        "additionalProperties": False,
    }
    action["spawn"]["invocations"][0]["role"] = "architect"
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-architect-timeout",
        status="timed_out",
        payload={},
        summary="architect worker exceeded the allowed wait window",
        actual_model="gpt-5.6-sol",
    )

    result_path = tmp_path / ".ae-state" / "host-runtime" / "work" / "result.json"
    result = HostExecutionAssembler(tmp_path).finalize_to_file(
        action=action,
        outcomes=[outcome],
        coordinator_payload={},
        result_path=result_path,
    )

    assert result["spawned"] is False
    assert result["spawn_error_code"] == "HOST_WORKER_TIMEOUT"
    assert result["spawn_retry_attempt"] == 1
    assert "plan" not in result
    assert json.loads(result_path.read_text(encoding="utf-8")) == result


def test_timeout_retry_budget_is_not_consumed_by_previous_non_timeout_failure(
    tmp_path: Path,
) -> None:
    """不同失败类别不能串用同一个连续超时次数。"""
    action = _action(tmp_path)
    assembler = HostExecutionAssembler(tmp_path)
    failed = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-hash-mismatch",
        status="failed",
        payload={"error": "prompt hash mismatch"},
        summary="WORKER_PROMPT_HASH_MISMATCH",
        actual_model="unreported",
    )
    first = assembler.finalize(
        action=action,
        outcomes=[failed],
        coordinator_payload={},
    )
    assert first["spawn_error_code"] == "HOST_WORKER_FAILED"
    assert first["spawn_retry_attempt"] == 1

    timed_out = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-timeout-after-retry",
        status="timed_out",
        payload={},
        summary="native worker timed out",
        actual_model="unreported",
    )
    second = assembler.finalize(
        action=action,
        outcomes=[timed_out],
        coordinator_payload={},
    )
    assert second["spawn_error_code"] == "HOST_WORKER_TIMEOUT"
    assert second["spawn_retry_attempt"] == 1
    journal = json.loads(
        (tmp_path / ".ae-state/host-runtime/outcomes/action-1.json").read_text()
    )
    assert journal["failure_kind"] == "timeout"
    assert len(journal["attempt_history"]) == 1
    assert journal["attempt_history"][0]["failure_kind"] == "worker"
    assert journal["attempt_history"][0]["failure_attempt"] == 1
    assert journal["attempt_history"][0]["spawn_error_code"] == "HOST_WORKER_FAILED"
    assert len(journal["attempt_history"][0]["fingerprint"]) == 64


@pytest.mark.parametrize(
    ("status", "summary", "error_code"),
    [
        ("timed_out", "native worker deadline exceeded", "HOST_WORKER_TIMEOUT"),
        ("failed", "native worker exited", "HOST_WORKER_FAILED"),
        ("cancelled", "native worker cancelled", "HOST_WORKER_FAILED"),
    ],
)
def test_all_worker_failure_states_precede_success_contract_validation(
    tmp_path: Path,
    status: str,
    summary: str,
    error_code: str,
) -> None:
    """所有失败态都必须走失败事务，不能被阶段成功字段拦截。"""
    action = _action(tmp_path)
    action["stage"] = "architect"
    action["result_contract"] = {
        "schema_version": "1.0",
        "required": ["plan", "file_list", "batch_plan"],
        "properties": {
            "plan": {"type": "string"},
            "file_list": {"type": "array"},
            "batch_plan": {"type": "array"},
        },
        "additionalProperties": False,
    }
    action["spawn"]["invocations"][0]["role"] = "architect"
    result = HostExecutionAssembler(tmp_path).finalize(
        action=action,
        outcomes=[NativeWorkerOutcome(
            worker_id="critic-0",
            native_worker_handle=f"agent-{status}",
            status=status,
            payload={},
            summary=summary,
            actual_model="gpt-5.6-sol",
        )],
        coordinator_payload={},
    )

    assert result["spawned"] is False
    assert result["spawn_error_code"] == error_code
    assert "plan" not in result


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
    assert journal["status"] == "prepared"


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
    assert journal["status"] == "prepared"


def test_finalize_rejects_oversized_summary_before_writing_journal(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-oversized",
        status="completed",
        payload={"notes": "x" * 5000},
        summary="摘要" * 2000,
        actual_model="gpt-5.6-sol",
    )

    with pytest.raises(HostEvidenceValidationError) as caught:
        HostExecutionAssembler(tmp_path).finalize(
            action=action,
            outcomes=[outcome],
            coordinator_payload={"verdict": "APPROVE"},
        )

    assert caught.value.violations == ("WORKER_RECEIPT_TOO_LARGE:critic-0",)
    assert not (
        tmp_path / ".ae-state/host-runtime/outcomes/action-1.json"
    ).exists()


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


def test_invalid_attestation_does_not_prepare_outcome_journal(
    tmp_path: Path,
) -> None:
    """无效隔离证明必须在不可变 journal 与 receipt 落盘前被拒绝。"""
    action = _action(tmp_path)
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"verdict": "MAJOR", "findings": []},
        summary="发现问题",
        actual_model="gpt-5.6-sol",
        isolation_evidence={"fork_context": True},  # type: ignore[arg-type]
    )

    with pytest.raises(
        HostEvidenceValidationError,
        match="ATTESTATION_ISOLATION_MISMATCH",
    ):
        HostExecutionAssembler(tmp_path).finalize(
            action=action,
            outcomes=[outcome],
            coordinator_payload={"verdict": "MAJOR", "findings": []},
        )

    assert not (
        tmp_path / ".ae-state/host-runtime/outcomes/action-1.json"
    ).exists()
    assert not (
        tmp_path / ".ae-state/spawn-proofs/worker-token.json"
    ).exists()
    assert not (
        tmp_path / ".ae-state/spawn-proofs/total-token.json"
    ).exists()


def test_native_isolation_object_is_canonicalized_before_commit(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"verdict": "APPROVE", "findings": []},
        summary="通过",
        actual_model="gpt-5.6-sol",
        isolation_evidence={"fork_context": False},  # type: ignore[arg-type]
    )

    result = HostExecutionAssembler(tmp_path).finalize(
        action=action,
        outcomes=[outcome],
        coordinator_payload={"verdict": "APPROVE", "findings": []},
    )

    assert result["worker_attestations"][0]["isolation_evidence"] == (
        "fork_context=false"
    )
    journal = json.loads((
        tmp_path / ".ae-state/host-runtime/outcomes/action-1.json"
    ).read_text())
    assert journal["outcomes"][0]["isolation_evidence"] == "fork_context=false"


def test_combined_native_isolation_object_is_canonicalized_before_commit(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"verdict": "APPROVE", "findings": []},
        summary="通过",
        actual_model="gpt-5.6-sol",
        isolation_evidence={  # type: ignore[arg-type]
            "fork_context": False,
            "fork_turns": "none",
        },
    )

    result = HostExecutionAssembler(tmp_path).finalize(
        action=action,
        outcomes=[outcome],
        coordinator_payload={"verdict": "APPROVE", "findings": []},
    )

    assert result["worker_attestations"][0]["isolation_evidence"] == (
        "fork_context=false"
    )


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


def test_restore_prepared_journal_materializes_authoritative_outcomes(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    original = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"verdict": "PASS"},
        summary="通过",
        actual_model="gpt-5.6-sol",
        isolation_evidence="fork_context=false",
    ).to_dict()
    journal = tmp_path / ".ae-state/host-runtime/outcomes/action-1.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({
        "schema_version": "1.0",
        "status": "prepared",
        "action_message_id": "action-1",
        "outcomes": [original],
    }))
    work_copy = Path(".ae-state/host-runtime/work/recovery/outcomes.json")
    target = tmp_path / work_copy
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"outcomes": [{
        **original,
        "isolation_evidence": "fork_turns=none",
    }]}))

    restored = HostExecutionAssembler(tmp_path).restore_committed_result_to_file(
        action=action,
        result_path=Path("result.json"),
        outcomes_path=work_copy,
    )

    assert restored is None
    assert json.loads(target.read_text()) == {"outcomes": [original]}


def test_restore_rejected_journal_materializes_authoritative_outcomes(
    tmp_path: Path,
) -> None:
    """Core 拒绝候选 Result 后，修复上下文仍只能复用首个 Worker 事实。"""
    action = _action(tmp_path)
    original = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"verdict": "PASS"},
        summary="通过",
        actual_model="gpt-5.6-sol",
        isolation_evidence="fork_context=false",
    ).to_dict()
    journal = tmp_path / ".ae-state/host-runtime/outcomes/action-1.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({
        "schema_version": "1.1",
        "status": "rejected",
        "action_message_id": "action-1",
        "outcomes": [original],
            "outcomes_fingerprint": hashlib.sha256(
                json.dumps({
                    "action_message_id": "action-1",
                    "outcomes": [original],
                }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        "rejection": {"error_code": "RESULT_FIELD_MISSING"},
    }))

    work_copy = Path(".ae-state/host-runtime/work/recovery/outcomes.json")
    restored = HostExecutionAssembler(tmp_path).restore_committed_result_to_file(
        action=action,
        result_path=Path("result.json"),
        outcomes_path=work_copy,
    )

    assert restored is None
    assert json.loads((tmp_path / work_copy).read_text()) == {
        "outcomes": [original]
    }


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


def test_finalize_reuses_authoritative_worker_outcome_after_core_rejection(
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
    first = assembler.finalize(
        action=action,
        outcomes=[original],
        coordinator_payload={"verdict": "PASS"},
    )
    from auto_engineering.host.outcome_journal import OutcomeJournal

    OutcomeJournal(tmp_path).reject(
        "action-1", error_code="RESULT_FIELD_MISSING"
    )
    changed = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="different-context-worker",
        status="completed",
        payload={"verdict": "PASS"},
        summary="通过",
        actual_model="gpt-5.6-sol",
    )

    repaired = assembler.finalize(
        action=action,
        outcomes=[changed],
        coordinator_payload={"verdict": "PASS", "findings": []},
    )

    assert repaired["findings"] == []
    assert repaired["worker_attestations"][0]["worker_id"] == "critic-0"
    assert repaired["worker_attestations"][0]["actual_model"] == "gpt-5.6-sol"
    assert repaired["message_id"] != first["message_id"]


def test_finalize_archives_invalid_legacy_prepared_outcome_before_repair(
    tmp_path: Path,
) -> None:
    """旧版在证明校验前写入的非法 prepared journal 必须可审计地迁移。"""
    action = _action(tmp_path)
    invalid = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"verdict": "MAJOR", "findings": []},
        summary="发现问题",
        actual_model="gpt-5.6-sol",
        isolation_evidence={"fork_context": False},  # type: ignore[arg-type]
    ).to_dict()
    journal = tmp_path / ".ae-state/host-runtime/outcomes/action-1.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({
        "schema_version": "1.0",
        "status": "prepared",
        "fingerprint": "legacy-invalid",
        "outcomes_fingerprint": "legacy-invalid",
        "action_message_id": "action-1",
        "completed_at": "2026-08-22T00:00:00+00:00",
        "outcomes": [invalid],
    }))
    corrected = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"verdict": "MAJOR", "findings": []},
        summary="发现问题",
        actual_model="gpt-5.6-sol",
        isolation_evidence={"fork_context": False},  # type: ignore[arg-type]
    )

    result = HostExecutionAssembler(tmp_path).finalize(
        action=action,
        outcomes=[corrected],
        coordinator_payload={"verdict": "MAJOR", "findings": []},
    )

    assert result["spawned"] is True
    archived = list((
        tmp_path / ".ae-state/host-runtime/rejected-outcomes"
    ).glob("action-1-*.json"))
    assert len(archived) == 1
    rejected = json.loads(archived[0].read_text())
    assert rejected["reason"] == "ATTESTATION_ISOLATION_MISMATCH"
    assert rejected["journal"]["fingerprint"] == "legacy-invalid"
    assert json.loads(journal.read_text())["status"] == "prepared"


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


def test_coordinator_whitelist_comes_from_machine_result_contract() -> None:
    action = {
        "expected_format": {"findings": "array"},
        "result_contract": {
            "properties": {
                "findings": {"type": "array"},
                "sources": {"type": "array"},
            },
        },
    }

    violations = HostExecutionAssembler._coordinator_payload_violations(
        action,
        {"findings": [], "sources": []},
    )

    assert violations == []


def test_finalize_recovers_once_from_json_stringified_array_field(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    action["expected_format"] = {
        "verdict": "APPROVE | MAJOR",
        "findings": "array",
    }
    action["result_contract"] = {
        "schema_version": "1.0",
        "required": ["verdict", "findings"],
        "properties": {
            "verdict": {"type": "string"},
            "findings": {"type": "array"},
        },
        "additionalProperties": False,
    }
    findings = [{
        "severity": "P1",
        "file": "src/example.ts",
        "issue": "缺少边界校验",
    }]
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"verdict": "MAJOR", "findings": findings},
        summary="发现一个主要问题",
        actual_model="gpt-5.6-sol",
    )

    result = HostExecutionAssembler(tmp_path).finalize(
        action=action,
        outcomes=[outcome],
        coordinator_payload={
            "verdict": "MAJOR",
            "findings": json.dumps(findings, ensure_ascii=False),
        },
    )

    assert result["findings"] == findings
    journal = json.loads((
        tmp_path / ".ae-state/host-runtime/outcomes/action-1.json"
    ).read_text())
    assert journal["result"]["findings"] == findings


def test_finalize_rejects_unrecoverable_business_type_before_journal(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    action["expected_format"] = {
        "verdict": "APPROVE | MAJOR",
        "findings": "array",
    }
    action["result_contract"] = {
        "schema_version": "1.0",
        "required": ["verdict", "findings"],
        "properties": {
            "verdict": {"type": "string"},
            "findings": {"type": "array"},
        },
        "additionalProperties": False,
    }
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"verdict": "MAJOR", "findings": []},
        summary="审查完成",
        actual_model="gpt-5.6-sol",
    )

    with pytest.raises(HostEvidenceValidationError) as caught:
        HostExecutionAssembler(tmp_path).finalize(
            action=action,
            outcomes=[outcome],
            coordinator_payload={
                "verdict": "MAJOR",
                "findings": "not-json",
            },
        )

    assert caught.value.violations == (
        "COORDINATOR_FIELD_TYPE_INVALID:findings:array",
    )
    assert not (
        tmp_path / ".ae-state/host-runtime/outcomes/action-1.json"
    ).exists()


def test_finalize_rejects_invalid_stage_semantics_before_journal(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    action["expected_format"] = {
        "verdict": "APPROVE | MAJOR",
        "findings": "array",
    }
    action["result_contract"] = {
        "schema_version": "1.0",
        "required": ["verdict", "findings"],
        "properties": {
            "verdict": {"type": "string"},
            "findings": {"type": "array"},
        },
        "additionalProperties": False,
    }
    outcome = NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="agent-123",
        status="completed",
        payload={"verdict": "MAYBE", "findings": []},
        summary="审查完成",
        actual_model="gpt-5.6-sol",
    )

    with pytest.raises(HostEvidenceValidationError) as caught:
        HostExecutionAssembler(tmp_path).finalize(
            action=action,
            outcomes=[outcome],
            coordinator_payload={"verdict": "MAYBE", "findings": []},
        )

    assert caught.value.violations[0].startswith(
        "COORDINATOR_RESULT_INVALID:verdict 非法",
    )
    assert not (
        tmp_path / ".ae-state/host-runtime/outcomes/action-1.json"
    ).exists()


def test_inline_finalize_rejects_field_outside_strict_result_contract(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    action.pop("spawn")
    action.pop("host_execution")
    action.pop("spawn_proof_token")
    action["tick"] = 1
    action["result_contract"] = {
        "schema_version": "1.0",
        "required": ["verdict", "findings"],
        "properties": {
            "verdict": {"type": "string"},
            "findings": {"type": "array"},
        },
        "additionalProperties": False,
    }

    with pytest.raises(HostEvidenceValidationError) as caught:
        HostExecutionAssembler(tmp_path).finalize(
            action=action,
            outcomes=[],
            coordinator_payload={
                "verdict": "APPROVE",
                "findings": [],
                "untyped_details": {"hidden": "value"},
            },
        )

    assert caught.value.violations == (
        "COORDINATOR_FIELD_UNEXPECTED:untyped_details",
    )
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


def test_gap_scan_contract_rejects_empty_substitute_when_work_result_is_lost(
    tmp_path: Path,
) -> None:
    """丢失 Action-scoped 产物时不得用 gaps=[] 绕过逐章节扫描。"""
    action = {
        "schema_version": "1.1",
        "message_type": "action",
        "message_id": "gap-action-strict-1",
        "thread_id": "thread-1",
        "tick": 7,
        "stage": "gap_scan",
        "correlation_id": "correlation-1",
        "result_contract": {
            "schema_version": "1.0",
            "required": [
                "gaps", "scanned_sections", "has_blocking",
                "design_doc_digest", "scan_coverage",
            ],
            "properties": {
                "gaps": {"type": "array"},
                "scanned_sections": {"type": "integer"},
                "has_blocking": {"type": "boolean"},
                "design_doc_digest": {"type": "string"},
                "scan_coverage": {"type": "array"},
            },
            "additionalProperties": False,
        },
    }

    with pytest.raises(HostEvidenceValidationError) as caught:
        HostExecutionAssembler(tmp_path).finalize(
            action=action,
            outcomes=[],
            coordinator_payload={
                "gaps": [],
                "scanned_sections": 0,
                "has_blocking": False,
            },
        )

    assert set(caught.value.violations) == {
        "COORDINATOR_FIELD_REQUIRED:design_doc_digest",
        "COORDINATOR_FIELD_REQUIRED:scan_coverage",
    }


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


def test_gap_semantic_findings_report_all_identity_violations_before_journal(
    tmp_path: Path,
) -> None:
    action = {
        "schema_version": "1.1",
        "message_id": "gap-scan-action-1",
        "thread_id": "thread-1",
        "tick": 1,
        "stage": "gap_scan",
        "correlation_id": "thread-1",
        "context": {
            "design_doc_digest": "sha256:" + "1" * 64,
            "design_sections": [
                {
                    "section_id": "section:1111111111111111",
                    "design_section": "§1.1",
                },
                {
                    "section_id": "section:2222222222222222",
                    "design_section": "§1.2",
                },
            ],
        },
        "result_contract": {
            "schema_version": "1.0",
            "required": ["gaps", "section_findings"],
            "properties": {
                "gaps": {"type": "array"},
                "section_findings": {"type": "array"},
            },
            "additionalProperties": False,
        },
    }

    with pytest.raises(HostEvidenceValidationError) as caught:
        HostExecutionAssembler(tmp_path).finalize(
            action=action,
            outcomes=[],
            coordinator_payload={
                "gaps": [],
                "section_findings": [
                    {
                        "section_id": "section:ffffffffffffffff",
                        "verdict": "clear",
                        "evidence": ["未知章节"],
                    },
                    {
                        "section_id": "section:1111111111111111",
                        "verdict": "clear",
                        "evidence": [],
                    },
                ],
            },
        )

    assert set(caught.value.violations) == {
        "SECTION_FINDING_UNKNOWN:section:ffffffffffffffff",
        "SECTION_FINDING_INVALID:1",
        "SECTION_FINDING_MISSING:section:1111111111111111",
        "SECTION_FINDING_MISSING:section:2222222222222222",
    }
    journal = (
        tmp_path
        / ".ae-state/host-runtime/outcomes/gap-scan-action-1.json"
    )
    assert not journal.exists()


def test_gap_assembler_normalizes_legacy_string_impact(tmp_path: Path) -> None:
    action = {
        "schema_version": "1.1", "message_id": "gap-impact-action",
        "thread_id": "thread-1", "tick": 1, "stage": "gap_scan",
        "correlation_id": "thread-1",
        "context": {
            "design_doc_digest": "sha256:" + "1" * 64,
            "design_sections": [{
                "section_id": "section:1111111111111111",
                "design_section": "§1.1",
            }],
        },
        "result_contract": {
            "schema_version": "1.0", "required": ["gaps", "section_findings"],
            "properties": {"gaps": {"type": "array"},
                           "section_findings": {"type": "array"}},
            "additionalProperties": False,
        },
    }
    gap = {
        "id": "GAP-1", "design_section_ref": "§1.1",
        "grade": "component", "clarity": "partial", "summary": "契约不完整",
        "depends_on": [], "evidence": ["缺少错误语义"],
        "problem_statement": "无法实现", "impact": "影响接口和测试",
        "dependencies": [], "recommendation": {
            "resolution": "Fill", "reason": "补齐契约", "confidence": "high",
        },
        "options": [{"resolution": "Fill", "meaning": "补齐", "enabled": True}],
        "blocking_rule": "可在实现前补齐",
    }

    result = HostExecutionAssembler(tmp_path).finalize(
        action=action, outcomes=[], coordinator_payload={
            "gaps": [gap],
            "section_findings": [{
                "section_ref": "§1.1", "verdict": "gap", "evidence": ["存在缺口"],
            }],
        },
    )

    assert result["gaps"][0]["impact"] == ["影响接口和测试"]


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


def test_finalize_accepts_matching_stage_echo_but_core_owns_result_identity(
    tmp_path: Path,
) -> None:
    action = {
        "schema_version": "1.1",
        "message_id": "setup-action-1",
        "thread_id": "thread-1",
        "tick": 1,
        "stage": "project_setup",
    }

    result = HostExecutionAssembler(tmp_path).finalize(
        action=action,
        outcomes=[],
        coordinator_payload={
            "stage": "project_setup",
            "result_type": "project_setup_completed",
            "artifacts": ["pyproject.toml"],
        },
    )

    assert result["stage"] == "project_setup"
    assert result["causation_id"] == "setup-action-1"
    assert result["result_type"] == "project_setup_completed"


def test_finalize_rejects_mismatched_stage_echo(tmp_path: Path) -> None:
    action = {
        "schema_version": "1.1",
        "message_id": "setup-action-1",
        "thread_id": "thread-1",
        "tick": 1,
        "stage": "project_setup",
    }

    with pytest.raises(
        HostEvidenceValidationError,
        match="COORDINATOR_IDENTITY_OVERRIDE",
    ):
        HostExecutionAssembler(tmp_path).finalize(
            action=action,
            outcomes=[],
            coordinator_payload={
                "stage": "developer",
                "result_type": "project_setup_completed",
                "artifacts": ["pyproject.toml"],
            },
        )


def test_finalize_unwraps_exact_host_business_result_envelope(tmp_path: Path) -> None:
    action = {
        "schema_version": "1.1",
        "message_id": "gap-action-1",
        "thread_id": "thread-1",
        "tick": 3,
        "stage": "gap_scan",
        "action": "gap_scan",
    }

    result = HostExecutionAssembler(tmp_path).finalize(
        action=action,
        outcomes=[],
        coordinator_payload={
            "action": "gap_scan",
            "stage": "gap_scan",
            "tick": 3,
            "thread_id": "thread-1",
            "status": "ok",
            "result": {"gaps": [], "has_blocking": False, "scanned_sections": 1},
        },
    )

    assert result["gaps"] == []
    assert result["has_blocking"] is False
    assert "result" not in result


def test_finalize_rejects_host_result_envelope_with_identity_drift(
    tmp_path: Path,
) -> None:
    action = {
        "schema_version": "1.1",
        "message_id": "gap-action-1",
        "thread_id": "thread-1",
        "tick": 3,
        "stage": "gap_scan",
        "action": "gap_scan",
    }

    with pytest.raises(
        HostEvidenceValidationError,
        match="COORDINATOR_IDENTITY_OVERRIDE",
    ):
        HostExecutionAssembler(tmp_path).finalize(
            action=action,
            outcomes=[],
            coordinator_payload={
                "action": "gap_scan",
                "stage": "developer",
                "tick": 3,
                "thread_id": "thread-1",
                "status": "ok",
                "result": {"gaps": []},
            },
        )


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


def test_missing_worker_failure_preserves_action_execution_binding(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    action["execution_generation"] = 3
    action["fencing_token"] = "f" * 64
    action["host_execution"]["workers"][0]["execution_generation"] = 3
    action["host_execution"]["workers"][0]["fencing_token"] = "f" * 64

    result = HostExecutionAssembler(tmp_path).finalize_missing_worker_output(
        action=action,
    )

    journal = json.loads(
        (tmp_path / ".ae-state/host-runtime/outcomes/action-1.json")
        .read_text(encoding="utf-8")
    )
    assert journal["outcomes"][0]["execution_generation"] == 3
    assert journal["outcomes"][0]["fencing_token"] == "f" * 64
    assert result["spawn_error_code"] == "HOST_WORKER_FAILED"


def test_worker_template_cannot_drift_from_action_execution_binding(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    action["execution_generation"] = 3
    action["fencing_token"] = "f" * 64
    action["host_execution"]["workers"][0]["execution_generation"] = 2
    action["host_execution"]["workers"][0]["fencing_token"] = "e" * 64

    with pytest.raises(
        HostEvidenceValidationError,
        match="WORKER_EXECUTION_BINDING_MISMATCH:critic-0",
    ):
        HostExecutionAssembler(tmp_path).finalize_missing_worker_output(
            action=action,
        )
