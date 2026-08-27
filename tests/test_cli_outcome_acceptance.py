"""CLI 必须以 Core 响应决定宿主候选 Result 的最终状态。"""

from __future__ import annotations

import json
from pathlib import Path

from auto_engineering.cli.dev_loop import (
    _project_result_repair_action,
    _record_outcome_acceptance,
)
from auto_engineering.host.outcome_journal import OutcomeJournal


def _prepared(tmp_path: Path) -> Path:
    result = {
        "message_type": "result",
        "message_id": "result-1",
        "causation_id": "action-1",
    }
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    OutcomeJournal(tmp_path).prepare("action-1", result, fingerprint="fp-1")
    return path


def test_next_action_marks_candidate_accepted(tmp_path: Path) -> None:
    result_path = _prepared(tmp_path)

    rejected = _record_outcome_acceptance(
        root=tmp_path,
        submitted_result_file=result_path,
        core_response={"action": "developer", "message_id": "action-2"},
    )

    record = OutcomeJournal(tmp_path).load("action-1")
    assert record is not None
    assert record["status"] == "accepted"
    assert rejected is False


def test_protocol_error_marks_candidate_rejected_for_same_action_repair(
    tmp_path: Path,
) -> None:
    result_path = _prepared(tmp_path)

    rejected = _record_outcome_acceptance(
        root=tmp_path,
        submitted_result_file=result_path,
        core_response={
            "action": "error",
            "error_code": "RESULT_FIELD_MISSING",
            "violations": ["scan_coverage"],
        },
    )

    record = OutcomeJournal(tmp_path).load("action-1")
    assert record is not None
    assert record["status"] == "rejected"
    assert record["repairable"] is True
    assert record["action_message_id"] == "action-1"
    assert rejected is True


def test_repair_projection_keeps_active_action_and_continue_control() -> None:
    active = {
        "message_id": "action-1",
        "stage": "gap_scan",
        "extensions": {"ae": {"execution_control": {
            "disposition": "CONTINUE",
            "continuation_required": True,
        }}},
    }

    projected = _project_result_repair_action(
        active,
        {"action": "error", "error_code": "RESULT_FIELD_MISSING"},
    )

    assert projected["message_id"] == "action-1"
    assert projected["stage"] == "gap_scan"
    assert projected["extensions"] == active["extensions"]
    assert projected["result_rejection"]["repair_required"] is True
