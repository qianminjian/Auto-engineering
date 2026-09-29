"""Worker 失败服务的分类、幂等和结果路径边界。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from auto_engineering.host.worker_evidence import (
    HostEvidenceValidationError,
    NativeWorkerOutcome,
)
from auto_engineering.host.worker_failure import WorkerFailureService
from auto_engineering.host.worker_observation import (
    WorkerObservationContract,
    WorkerObservationRecord,
    observation_relative_path,
)
from auto_engineering.host.worker_observation_store import WorkerObservationStore


def _action(tmp_path: Path) -> dict[str, object]:
    from tests.test_host_execution_assembler import _action as build_action

    return build_action(tmp_path)


def _failure(*, status: str = "failed", error_code: str | None = None) -> NativeWorkerOutcome:
    payload = {"verdict": "FAIL"}
    if error_code is not None:
        payload["error_code"] = error_code
    return NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="native-failure",
        status=status,
        payload=payload,
        summary="Worker failure",
        actual_model="deterministic-test",
    )


def test_worker_failure_is_classified_and_idempotent(tmp_path: Path) -> None:
    service = WorkerFailureService(tmp_path)
    action = _action(tmp_path)
    result = service.finalize_worker_failure(action=action, outcomes=[_failure()])
    assert result["spawned"] is False
    assert result["spawn_error_code"] == "HOST_WORKER_FAILED"
    assert service.finalize_worker_failure(action=action, outcomes=[_failure()]) == result


def test_worker_failure_classifies_timeout_and_protocol_separately(tmp_path: Path) -> None:
    service = WorkerFailureService(tmp_path)
    timeout_action = _action(tmp_path)
    timeout = service.finalize_worker_failure(
        action=timeout_action,
        outcomes=[_failure(status="timed_out")],
    )
    assert timeout["spawn_error_code"] == "HOST_WORKER_TIMEOUT"

    protocol_action = deepcopy(timeout_action)
    protocol_action["message_id"] = "protocol-action"
    protocol = service.finalize_worker_failure(
        action=protocol_action,
        outcomes=[_failure(error_code="HOST_PROTOCOL_FAILURE")],
    )
    assert protocol["spawn_error_code"] == "HOST_PROTOCOL_FAILURE"


def _native_wait_timeout_action(tmp_path: Path) -> dict[str, object]:
    action = _action(tmp_path)
    action["execution_generation"] = 1
    action["fencing_token"] = "a" * 64
    action["host_execution"]["worker_observation"] = (
        WorkerObservationContract.for_platform("codex").to_dict()
    )
    worker = action["host_execution"]["workers"][0]
    worker.update({
        "execution_generation": 1,
        "fencing_token": "a" * 64,
        "observation_path": str(observation_relative_path(
            "action-1", "critic-0", 1
        )),
    })
    action["spawn"]["invocations"][0]["outcome_path"] = (
        ".ae-state/host-runtime/worker-outcomes/action-1-critic-0-g1.json"
    )
    return action


def _native_wait_timeout_outcome() -> NativeWorkerOutcome:
    return NativeWorkerOutcome(
        worker_id="critic-0",
        native_worker_handle="native-timeout",
        status="timed_out",
        payload={},
        summary="native worker timed out",
        actual_model="deterministic-test",
        execution_generation=1,
        fencing_token="a" * 64,
    )


def test_native_wait_timeout_without_termination_proof_becomes_owner_lost(
    tmp_path: Path,
) -> None:
    result = WorkerFailureService(tmp_path).finalize_worker_failure(
        action=_native_wait_timeout_action(tmp_path),
        outcomes=[_native_wait_timeout_outcome()],
    )

    assert result["spawn_error_code"] == "HOST_WORKER_OWNER_LOST"
    assert "WORKER_OBSERVATION_MISSING:critic-0" in result["spawn_error"]


def test_native_wait_timeout_requires_matching_terminal_observation(
    tmp_path: Path,
) -> None:
    action = _native_wait_timeout_action(tmp_path)
    WorkerObservationStore(tmp_path).save(WorkerObservationRecord(
        schema_version="1.0",
        action_message_id="action-1",
        worker_id="critic-0",
        execution_generation=1,
        fencing_token="a" * 64,
        observed_at="2026-09-29T00:00:00+00:00",
        native_status="timed_out",
        wait_attempt=1,
        owner_known=True,
        native_worker_handle="native-timeout",
    ))

    result = WorkerFailureService(tmp_path).finalize_worker_failure(
        action=action,
        outcomes=[_native_wait_timeout_outcome()],
    )

    assert result["spawn_error_code"] == "HOST_WORKER_TIMEOUT"


@pytest.mark.parametrize(
    "mutator, violation",
    [
        (lambda action: action.pop("message_id"), "ACTION_MESSAGE_ID_MISSING"),
        (lambda action: action.pop("thread_id"), "THREAD_ID_MISSING"),
        (lambda action: action.pop("stage"), "STAGE_MISSING"),
        (lambda action: action.__setitem__("tick", -1), "ACTION_TICK_INVALID"),
    ],
)
def test_worker_failure_rejects_incomplete_action_identity(
    tmp_path: Path, mutator: object, violation: str
) -> None:
    service = WorkerFailureService(tmp_path)
    action = _action(tmp_path)
    mutator(action)  # type: ignore[operator]
    with pytest.raises(HostEvidenceValidationError, match=violation):
        service.finalize_worker_failure(action=action, outcomes=[_failure()])


def test_missing_worker_output_writes_bounded_result_and_rejects_escape(
    tmp_path: Path,
) -> None:
    service = WorkerFailureService(tmp_path)
    action = _action(tmp_path)
    result_path = tmp_path / ".ae-state/host-runtime/result.json"
    result = service.finalize_missing_worker_output(
        action=action,
        reason_code="HOST_WORKER_OUTPUT_INVALID",
        result_path=result_path,
    )
    assert result["spawn_error_code"] == "HOST_PROTOCOL_FAILURE"
    assert result_path.is_file()
    with pytest.raises(HostEvidenceValidationError, match="RESULT_OUTPUT_PATH_OUTSIDE_PROJECT"):
        escape_action = deepcopy(action)
        escape_action["message_id"] = "escape-action"
        service.finalize_missing_worker_output(
            action=escape_action,
            result_path=tmp_path.parent / "escape.json",
        )
