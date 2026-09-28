"""宿主进程退出边界的纯协议回归，不依赖外部 CLI 或系统工具链。"""

from __future__ import annotations

import json
from hashlib import sha256
from io import StringIO
from pathlib import Path

import pytest

from auto_engineering.host.outcome_recovery import OutcomeRecoveryService
from auto_engineering.host.process_exit import (
    _last_json_object,
    _stream_termination_reason,
    _termination_reason,
    _termination_reason_from_value,
    main,
)
from auto_engineering.host.runtime_driver import (
    HostRunLease,
    HostRunLeaseStore,
    fencing_token_for,
)
from auto_engineering.host.worker_evidence import (
    HostEvidenceValidationError,
    _canonical_bytes,
)


def _save_lease(root: Path, *, session_id: str = "session-1") -> None:
    HostRunLeaseStore(root).save(
        HostRunLease(
            schema_version="1.0",
            thread_id="thread-1",
            action_message_id="action-1",
            platform="claude-code",
            host_session_id=session_id,
            build_id="build-1",
            disposition="CONTINUE",
            continuation_required=True,
            yield_allowed=False,
            fencing_token=fencing_token_for("action-1", session_id, 1),
        )
    )


def test_last_json_object_chooses_last_object_and_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "stream.jsonl"
    path.write_text(
        "not-json\n[1, 2]\n{" + '"first": true}\n' + '{"last": true}\n',
        encoding="utf-8",
    )

    assert _last_json_object(path) == {"last": True}
    assert _last_json_object(tmp_path / "missing.jsonl") is None
    path.write_bytes(b"\xff")
    assert _last_json_object(path) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"result": "API Error: Stream idle timeout - no chunks received"}, "HOST_PROVIDER_STREAM_IDLE_TIMEOUT"),
        ({"text": "API Error: Stream idle timeout - no chunks received"}, "HOST_PROVIDER_STREAM_IDLE_TIMEOUT"),
        ({"content": [{"item": {"error_code": "NESTED_ERROR"}}]}, "NESTED_ERROR"),
        ({"terminal_reason": "terminal"}, "terminal"),
        ({"stop_reason": "stopped"}, "stopped"),
        ({"error_code": "coded"}, "coded"),
        ({"item": {"text": '{"error_code":"embedded"}'}}, "embedded"),
        ({"text": "not-json"}, None),
        ([], None),
    ],
)
def test_termination_reason_accepts_only_structured_nested_evidence(
    value: object, expected: str | None
) -> None:
    assert _termination_reason_from_value(value) == expected


def test_stream_termination_reason_reads_latest_valid_signal(tmp_path: Path) -> None:
    path = tmp_path / "stream.jsonl"
    path.write_text(
        "not-json\n"
        + json.dumps({"error_code": "old"})
        + "\n"
        + json.dumps({"terminal_reason": "latest"})
        + "\n",
        encoding="utf-8",
    )

    assert _stream_termination_reason(path) == "latest"
    assert _stream_termination_reason(tmp_path / "missing.jsonl") is None
    assert _termination_reason(None) == "process_exit"
    assert _termination_reason({"error_code": "explicit"}) == "explicit"


def test_process_exit_without_lease_is_a_noop_response(tmp_path: Path) -> None:
    output = StringIO()
    host_output = tmp_path / "host.jsonl"
    host_output.write_text("not-json\n", encoding="utf-8")

    assert main(
        [
            "--project-root",
            str(tmp_path),
            "--host-output",
            str(host_output),
            "--exit-code",
            "0",
        ],
        stdout=output,
    ) == 0
    assert json.loads(output.getvalue()) == {
        "systemMessage": "Auto-Engineering 未发现活动宿主租约"
    }


def test_process_exit_preserves_lease_only_when_explicitly_requested(
    tmp_path: Path,
) -> None:
    _save_lease(tmp_path)
    host_output = tmp_path / "host.jsonl"
    host_output.write_text(
        json.dumps({"type": "result", "session_id": "session-1"}) + "\n",
        encoding="utf-8",
    )
    output = StringIO()

    assert main(
        [
            "--project-root",
            str(tmp_path),
            "--host-output",
            str(host_output),
            "--exit-code",
            "0",
            "--preserve-lease",
        ],
        stdout=output,
    ) == 0
    assert HostRunLeaseStore(tmp_path).load() is not None
    response = json.loads(output.getvalue())
    assert response["reason_code"] == "HOST_RUNTIME_PROTOCOL_ERROR"


def test_process_exit_rejects_negative_exit_code(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "--project-root",
                str(tmp_path),
                "--host-output",
                str(tmp_path / "host.jsonl"),
                "--exit-code",
                "-1",
            ]
        )


def _recovery_service(tmp_path: Path) -> OutcomeRecoveryService:
    return OutcomeRecoveryService(
        tmp_path,
        finalize=lambda **_: {},
        finalize_to_file=lambda **_: {},
    )


def _recovery_action(message_id: str = "action-recovery") -> dict[str, object]:
    return {
        "message_id": message_id,
        "thread_id": "thread-recovery",
        "stage": "developer",
        "tick": 3,
    }


def _write_journal(tmp_path: Path, message_id: str, journal: dict[str, object]) -> None:
    path = tmp_path / ".ae-state/host-runtime/outcomes" / f"{message_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(journal), encoding="utf-8")


def test_outcome_recovery_restores_committed_result_and_outcomes(tmp_path: Path) -> None:
    action = _recovery_action()
    result = {
        "message_type": "result",
        "causation_id": "action-recovery",
        "thread_id": "thread-recovery",
        "stage": "developer",
        "tick": 3,
        "spawned": True,
    }
    _write_journal(
        tmp_path,
        "action-recovery",
        {
            "schema_version": "1.1",
            "status": "committed",
            "action_message_id": "action-recovery",
            "result": result,
            "outcomes": [{"worker_id": "developer-0"}],
        },
    )

    restored = _recovery_service(tmp_path).restore_committed_result_to_file(
        action=action,
        result_path=Path("result.json"),
        outcomes_path=Path("outcomes.json"),
    )

    assert restored == result
    assert json.loads((tmp_path / "result.json").read_text()) == result
    assert json.loads((tmp_path / "outcomes.json").read_text()) == {
        "outcomes": [{"worker_id": "developer-0"}]
    }


def test_outcome_recovery_handles_prepared_rejected_and_missing_journal_states(
    tmp_path: Path,
) -> None:
    service = _recovery_service(tmp_path)
    action = _recovery_action("action-prepared")
    assert service.restore_committed_result_to_file(
        action=action, result_path=Path("result.json")
    ) is None

    _write_journal(
        tmp_path,
        "action-prepared",
        {
            "status": "prepared",
            "schema_version": "1.0",
            "action_message_id": "action-prepared",
            "outcomes": [{"worker_id": "worker-0"}],
        },
    )
    assert service.restore_committed_result_to_file(
        action=action, result_path=Path("result.json"), outcomes_path=Path("prepared.json")
    ) is None
    assert (tmp_path / "prepared.json").is_file()

    _write_journal(
        tmp_path,
        "action-prepared",
        {
            "status": "assembly_rejected",
            "action_message_id": "action-prepared",
            "outcomes": [{"worker_id": "worker-1"}],
        },
    )
    assert service.restore_committed_result_to_file(
        action=action, result_path=Path("result.json"), outcomes_path=Path("assembly.json")
    ) is None
    assert (tmp_path / "assembly.json").is_file()

    _write_journal(
        tmp_path,
        "action-prepared",
        {
            "status": "rejected",
            "action_message_id": "action-prepared",
            "outcomes": [{"worker_id": "worker-2"}],
        },
    )
    assert service.restore_committed_result_to_file(
        action=action, result_path=Path("result.json"), outcomes_path=Path("rejected.json")
    ) is None
    assert (tmp_path / "rejected.json").is_file()


@pytest.mark.parametrize(
    ("journal", "expected"),
    [
        ({"status": "prepared", "schema_version": "2.0", "outcomes": []}, "OUTCOME_JOURNAL_PREPARED_INVALID"),
        ({"status": "accepted", "schema_version": "1.0", "result": {}}, "OUTCOME_JOURNAL_RESULT_IDENTITY_MISMATCH"),
    ],
)
def test_outcome_recovery_rejects_malformed_journal_identity(
    tmp_path: Path, journal: dict[str, object], expected: str
) -> None:
    action = _recovery_action("action-invalid-journal")
    journal = {**journal, "action_message_id": "action-invalid-journal"}
    _write_journal(tmp_path, "action-invalid-journal", journal)

    with pytest.raises(HostEvidenceValidationError, match=expected):
        _recovery_service(tmp_path).restore_committed_result_to_file(
            action=action, result_path=Path("result.json")
        )


def test_outcome_recovery_authoritative_outcomes_checks_identity_and_fingerprint() -> None:
    outcomes = [{"worker_id": "worker-0"}]
    fingerprint = sha256(
        _canonical_bytes({"action_message_id": "action-1", "outcomes": outcomes})
    ).hexdigest()
    assert OutcomeRecoveryService.authoritative_outcomes(
        journal={
            "action_message_id": "action-1",
            "outcomes": outcomes,
            "outcomes_fingerprint": fingerprint,
        },
        action_message_id="action-1",
        required=True,
    ) == outcomes

    with pytest.raises(
        HostEvidenceValidationError,
        match="OUTCOME_JOURNAL_OUTCOMES_FINGERPRINT_MISMATCH",
    ):
        OutcomeRecoveryService.authoritative_outcomes(
            journal={
                "action_message_id": "action-1",
                "outcomes": outcomes,
                "outcomes_fingerprint": "bad",
            },
            action_message_id="action-1",
            required=True,
        )
    assert OutcomeRecoveryService.authoritative_outcomes(
        journal={"action_message_id": "action-1"},
        action_message_id="action-1",
        required=False,
    ) is None


@pytest.mark.parametrize(
    "raw",
    ["[]", "not-json"],
)
def test_outcome_recovery_read_json_rejects_corrupt_or_non_object(
    tmp_path: Path, raw: str
) -> None:
    path = tmp_path / "journal.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(HostEvidenceValidationError, match="HOST_EVIDENCE_FILE"):
        OutcomeRecoveryService.read_json(path)


def test_outcome_recovery_rejects_missing_action_identity_and_rejected_without_outcomes(
    tmp_path: Path,
) -> None:
    service = _recovery_service(tmp_path)
    with pytest.raises(HostEvidenceValidationError, match="ACTION_IDENTITY_INVALID"):
        service.restore_committed_result_to_file(
            action={"message_id": "only-message"},
            result_path=Path("result.json"),
        )

    action = _recovery_action("action-rejected-missing")
    _write_journal(
        tmp_path,
        "action-rejected-missing",
        {"status": "rejected", "action_message_id": "action-rejected-missing"},
    )
    with pytest.raises(
        HostEvidenceValidationError,
        match="OUTCOME_JOURNAL_OUTCOMES_PATH_MISSING",
    ):
        service.restore_committed_result_to_file(
            action=action, result_path=Path("result.json")
        )

    _write_journal(
        tmp_path,
        "action-rejected-missing",
        {
            "status": "rejected",
            "action_message_id": "action-rejected-missing",
            "outcomes": "invalid",
        },
    )
    with pytest.raises(HostEvidenceValidationError, match="OUTCOME_JOURNAL_OUTCOMES_MISSING"):
        service.restore_committed_result_to_file(
            action=action,
            result_path=Path("result.json"),
            outcomes_path=Path("rejected.json"),
        )


def test_outcome_recovery_rejects_result_and_output_path_escapes(
    tmp_path: Path,
) -> None:
    action = _recovery_action("action-escape")
    result = {
        "message_type": "result",
        "causation_id": "action-escape",
        "thread_id": "thread-recovery",
        "stage": "developer",
        "tick": 3,
    }
    service = _recovery_service(tmp_path)
    _write_journal(
        tmp_path,
        "action-escape",
        {
            "status": "committed",
            "schema_version": "1.0",
            "action_message_id": "action-escape",
            "result": result,
            "outcomes": "invalid",
        },
    )
    with pytest.raises(HostEvidenceValidationError, match="RESULT_OUTPUT_PATH_OUTSIDE_PROJECT"):
        service.restore_committed_result_to_file(
            action=action, result_path=Path("../outside.json")
        )

    valid_outcomes_journal = {
        "status": "committed",
        "schema_version": "1.0",
        "action_message_id": "action-escape",
        "result": result,
        "outcomes": "invalid",
    }
    _write_journal(tmp_path, "action-escape", valid_outcomes_journal)
    with pytest.raises(HostEvidenceValidationError, match="OUTCOME_JOURNAL_OUTCOMES_INVALID"):
        service.restore_committed_result_to_file(
            action=action, result_path=Path("result.json"), outcomes_path=Path("outcomes.json")
        )

    _write_journal(
        tmp_path,
        "action-escape",
        {**valid_outcomes_journal, "outcomes": []},
    )
    with pytest.raises(HostEvidenceValidationError, match="OUTCOMES_OUTPUT_PATH_OUTSIDE_PROJECT"):
        service.restore_committed_result_to_file(
            action=action,
            result_path=Path("result.json"),
            outcomes_path=Path("../outside-outcomes.json"),
        )


def test_outcome_recovery_authoritative_outcomes_rejects_bad_shapes() -> None:
    with pytest.raises(
        HostEvidenceValidationError,
        match="OUTCOME_JOURNAL_ACTION_IDENTITY_MISMATCH",
    ):
        OutcomeRecoveryService.authoritative_outcomes(
            journal={"action_message_id": "other"},
            action_message_id="action-1",
            required=True,
        )
    with pytest.raises(HostEvidenceValidationError, match="OUTCOME_JOURNAL_OUTCOMES_MISSING"):
        OutcomeRecoveryService.authoritative_outcomes(
            journal={"action_message_id": "action-1"},
            action_message_id="action-1",
            required=True,
        )
    with pytest.raises(HostEvidenceValidationError, match="OUTCOME_JOURNAL_OUTCOMES_INVALID"):
        OutcomeRecoveryService.authoritative_outcomes(
            journal={"action_message_id": "action-1", "outcomes": ["bad"]},
            action_message_id="action-1",
            required=True,
        )
