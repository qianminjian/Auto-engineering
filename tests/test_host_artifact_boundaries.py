"""Worker artifact、失败记录和同 Action repair 的边界回归。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_engineering.host.outcome_repair import (
    assembly_rejection_can_extend_outcomes,
    merge_authoritative_outcomes,
)
from auto_engineering.host.spawn_contract import SpawnContractError, SpawnPlan
from auto_engineering.host.worker_artifact_repair import (
    bound_native_business_is_valid,
    quarantine_private_artifact,
)
from auto_engineering.host.worker_evidence import (
    HostEvidenceValidationError,
    NativeWorkerOutcome,
)
from auto_engineering.host.worker_evidence_contracts import (
    WorkerOutcomeCollectionError,
)
from auto_engineering.host.worker_failure_recovery import (
    read_recorded_failure_outcomes,
)
from auto_engineering.host.worker_outcome_collector import (
    collect_worker_outcomes_from_artifacts,
)


def _action(tmp_path: Path) -> dict[str, object]:
    from tests.test_host_execution_assembler import _action as build_action

    return build_action(tmp_path)


def _outcome(worker_id: str = "critic-0", status: str = "completed") -> NativeWorkerOutcome:
    return NativeWorkerOutcome(
        worker_id=worker_id,
        native_worker_handle="native-1",
        status=status,
        payload={"verdict": "APPROVE"},
        summary="测试结果",
        actual_model="deterministic-test",
    )


def test_outcome_repair_preserves_authoritative_fact_and_rejects_invalid_input() -> None:
    current = [_outcome()]
    merged = merge_authoritative_outcomes([_outcome().to_dict()], current)
    assert merged["critic-0"].native_worker_handle == "native-1"
    with pytest.raises(HostEvidenceValidationError, match="OUTCOME_JOURNAL_OUTCOMES_INVALID"):
        merge_authoritative_outcomes([{"worker_id": "critic-0"}], current)


def test_assembly_rejection_can_extend_outcomes_only_for_matching_authority() -> None:
    outcome = _outcome()
    assert assembly_rejection_can_extend_outcomes(
        {"status": "assembly_rejected", "outcomes": [outcome.to_dict()]},
        [outcome],
    ) is True
    assert assembly_rejection_can_extend_outcomes(
        {"status": "prepared", "outcomes": [outcome.to_dict()]}, [outcome]
    ) is False
    assert assembly_rejection_can_extend_outcomes(
        {"status": "assembly_rejected", "outcomes": [{"worker_id": "critic-0"}]},
        [outcome],
    ) is False
    assert assembly_rejection_can_extend_outcomes(
        {"status": "assembly_rejected", "outcomes": [outcome.to_dict(), "bad"]},
        [outcome],
    ) is False


def test_bound_native_business_and_quarantine_are_root_bound_and_idempotent(tmp_path: Path) -> None:
    action = _action(tmp_path)
    invocation = SpawnPlan.from_action(action).invocations[0]
    native_ref = ".ae-state/host-runtime/native-results/native.json"
    native_path = tmp_path / native_ref
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text(json.dumps({"verdict": "APPROVE"}), encoding="utf-8")
    template = {"native_result_path": native_ref}
    assert bound_native_business_is_valid(
        project_root=tmp_path, invocation=invocation, template=template
    ) is True
    assert bound_native_business_is_valid(
        project_root=tmp_path, invocation=invocation,
        template={"native_result_path": "../escape.json"},
    ) is False
    native_path.write_text("not-json", encoding="utf-8")
    assert bound_native_business_is_valid(
        project_root=tmp_path, invocation=invocation, template=template
    ) is False

    action_view = {"message_id": "action/artifact"}
    quarantine_private_artifact(
        project_root=tmp_path,
        action=action_view,
        worker_id="critic/0",
        outcome_ref="private.json",
        raw_bytes=b"broken",
        violations=["summary_missing"],
        execution_generation=2,
        fencing_token="a" * 64,
    )
    quarantine_root = tmp_path / ".ae-state/host-runtime/worker-outcome-quarantine"
    files = list(quarantine_root.glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["worker_id"] == "critic/0"
    with pytest.raises(HostEvidenceValidationError, match="QUARANTINE_BINDING_INVALID"):
        quarantine_private_artifact(
            project_root=tmp_path,
            action={},
            worker_id="critic-0",
            outcome_ref="private.json",
            raw_bytes=b"broken",
            violations=[],
            execution_generation=None,
            fencing_token=None,
        )


def test_failure_recovery_requires_current_action_and_all_workers_to_fail(tmp_path: Path) -> None:
    action = _action(tmp_path)
    assert read_recorded_failure_outcomes(tmp_path, {}) is None
    outcomes_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]  # type: ignore[index]
    outcomes_path.parent.mkdir(parents=True, exist_ok=True)
    outcomes_path.write_text("not-json", encoding="utf-8")
    action["host_execution"]["work_files"] = {"outcomes": str(outcomes_path)}  # type: ignore[index]
    assert read_recorded_failure_outcomes(tmp_path, action) is None

    action["host_execution"]["work_files"]["outcomes"] = "../outside.json"  # type: ignore[index]
    assert read_recorded_failure_outcomes(tmp_path, action) is None
    action["host_execution"]["work_files"]["outcomes"] = str(outcomes_path)  # type: ignore[index]
    outcomes_path.write_text(json.dumps({"outcomes": [{"worker_id": "critic-0"}]}), encoding="utf-8")
    assert read_recorded_failure_outcomes(tmp_path, action) is None
    outcomes_path.write_text(
        json.dumps({"outcomes": [_outcome(status="failed").to_dict()]}),
        encoding="utf-8",
    )
    recorded = read_recorded_failure_outcomes(tmp_path, action)
    assert recorded is not None and recorded[0].status == "failed"
    outcomes_path.write_text(
        json.dumps({"outcomes": [_outcome(status="completed").to_dict()]}),
        encoding="utf-8",
    )
    assert read_recorded_failure_outcomes(tmp_path, action) is None
    action["spawn"] = {}  # type: ignore[index]
    assert read_recorded_failure_outcomes(tmp_path, action) is None


def test_collector_rejects_missing_drift_and_unreported_worker_artifacts(tmp_path: Path) -> None:
    action = _action(tmp_path)
    worker = action["spawn"]["invocations"][0]  # type: ignore[index]
    outcomes_path = tmp_path / ".ae-state/host-runtime/work/outcomes.json"
    with pytest.raises(WorkerOutcomeCollectionError, match="HOST_WORKER_OUTPUT_MISSING"):
        collect_worker_outcomes_from_artifacts(
            project_root=tmp_path, action=action, outcomes_path=outcomes_path
        )
    action["host_execution"]["workers"][0]["outcome_path"] = "wrong.json"  # type: ignore[index]
    with pytest.raises(WorkerOutcomeCollectionError, match="outcome_path_drift"):
        collect_worker_outcomes_from_artifacts(
            project_root=tmp_path, action=action, outcomes_path=outcomes_path
        )
    action["host_execution"]["workers"][0]["outcome_path"] = worker["outcome_path"]  # type: ignore[index]
    private = tmp_path / worker["outcome_path"]
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_text(json.dumps({"worker_id": "critic-0", "status": "completed", "payload": {}}), encoding="utf-8")
    with pytest.raises(WorkerOutcomeCollectionError, match="HOST_WORKER_ATTESTATION_MISSING"):
        collect_worker_outcomes_from_artifacts(
            project_root=tmp_path, action=action, outcomes_path=outcomes_path
        )


def test_collector_rejects_outside_path_and_invalid_spawn_contract(tmp_path: Path) -> None:
    action = _action(tmp_path)
    action["spawn"]["invocations"][0]["outcome_path"] = "../outside.json"  # type: ignore[index]
    with pytest.raises(WorkerOutcomeCollectionError, match="HOST_PROTOCOL_FAILURE"):
        collect_worker_outcomes_from_artifacts(
            project_root=tmp_path, action=action, outcomes_path=tmp_path / "outcomes.json"
        )
    with pytest.raises(WorkerOutcomeCollectionError, match="HOST_PROTOCOL_FAILURE"):
        collect_worker_outcomes_from_artifacts(
            project_root=tmp_path, action={"spawn": {}}, outcomes_path=tmp_path / "outcomes.json"
        )
    with pytest.raises(SpawnContractError):
        SpawnPlan.for_recording({"host_execution": {"recovery": {"record_plan": {}}}})


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ([], "top_level_must_be_object"),
        (
            {
                "worker_id": "other",
                "native_worker_handle": "native",
                "status": "completed",
                "payload": {},
                "summary": "bad",
                "actual_model": "test",
            },
            "worker_id_mismatch",
        ),
        (
            {
                "worker_id": "critic-0",
                "native_worker_handle": "unreported:x",
                "status": "completed",
                "payload": {},
                "summary": "bad",
                "actual_model": "test",
            },
            "native_handle_unreported",
        ),
    ],
)
def test_collector_rejects_nonobject_identity_and_unreported_artifacts(
    tmp_path: Path, raw: object, message: str
) -> None:
    action = _action(tmp_path)
    worker = action["spawn"]["invocations"][0]  # type: ignore[index]
    private = tmp_path / worker["outcome_path"]
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(WorkerOutcomeCollectionError, match=message):
        collect_worker_outcomes_from_artifacts(
            project_root=tmp_path,
            action=action,
            outcomes_path=tmp_path / ".ae-state/host-runtime/work/outcomes.json",
        )


def test_collector_rejects_template_drift_and_unreadable_private_artifact(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    action["host_execution"]["workers"][0].pop("outcome_path")  # type: ignore[index]
    with pytest.raises(WorkerOutcomeCollectionError, match="outcome_path_missing"):
        collect_worker_outcomes_from_artifacts(
            project_root=tmp_path,
            action=action,
            outcomes_path=tmp_path / "outcomes.json",
        )
    action = _action(tmp_path / "nested")
    worker = action["spawn"]["invocations"][0]  # type: ignore[index]
    private = tmp_path / "nested" / worker["outcome_path"]
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_text("not-json", encoding="utf-8")
    with pytest.raises(WorkerOutcomeCollectionError, match="HOST_PROTOCOL_FAILURE"):
        collect_worker_outcomes_from_artifacts(
            project_root=tmp_path / "nested",
            action=action,
            outcomes_path=tmp_path / "nested/outcomes.json",
        )
