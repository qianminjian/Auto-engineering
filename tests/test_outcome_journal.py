"""宿主候选 Result 与 Core 接受事实的事务边界。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_engineering.host.outcome_journal import (
    OutcomeJournal,
    OutcomeJournalTransitionError,
)


def _result(action_id: str, *, suffix: str = "1") -> dict[str, object]:
    return {
        "message_type": "result",
        "message_id": f"result-{suffix}",
        "causation_id": action_id,
    }


def test_candidate_is_not_accepted_until_core_confirms(tmp_path: Path) -> None:
    journal = OutcomeJournal(tmp_path)

    journal.prepare("action-1", _result("action-1"), fingerprint="fp-1")

    record = journal.load("action-1")
    assert record is not None
    assert record["status"] == "prepared"
    assert "accepted_result_message_id" not in record


def test_core_rejection_preserves_repairable_active_action(tmp_path: Path) -> None:
    journal = OutcomeJournal(tmp_path)
    journal.prepare("action-1", _result("action-1"), fingerprint="fp-1")

    journal.reject(
        "action-1",
        error_code="RESULT_FIELD_MISSING",
        violations=["scan_coverage"],
    )

    rejected = journal.load("action-1")
    assert rejected is not None
    assert rejected["status"] == "rejected"
    assert rejected["repairable"] is True
    assert rejected["action_message_id"] == "action-1"
    assert rejected["rejection"]["error_code"] == "RESULT_FIELD_MISSING"

    journal.prepare("action-1", _result("action-1", suffix="2"), fingerprint="fp-2")
    repaired = journal.load("action-1")
    assert repaired is not None
    assert repaired["status"] == "prepared"
    assert repaired["attempt"] == 2
    assert len(repaired["rejection_history"]) == 1


def test_assembly_rejection_starts_repair_transaction_before_result_exists(
    tmp_path: Path,
) -> None:
    journal = OutcomeJournal(tmp_path)

    rejected = journal.reject_assembly(
        "action-1",
        coordinator_payload={"section_findings": [{"section_ref": "1"}]},
        error_code="HOST_EVIDENCE_INVALID",
        violations=["SECTION_FINDING_UNKNOWN:1"],
    )

    assert rejected["status"] == "assembly_rejected"
    assert rejected["repairable"] is True
    assert rejected["semantic_payload"]["section_findings"][0]["section_ref"] == "1"

    journal.prepare("action-1", _result("action-1"), fingerprint="fp-2")
    repaired = journal.load("action-1")
    assert repaired is not None
    assert repaired["attempt"] == 2
    assert repaired["rejection_history"][0]["error_code"] == (
        "HOST_EVIDENCE_INVALID"
    )


def test_assembly_rejection_preserves_completed_worker_facts(
    tmp_path: Path,
) -> None:
    journal = OutcomeJournal(tmp_path)
    journal.prepare(
        "action-1",
        _result("action-1"),
        fingerprint="result-fp",
        extra={
            "outcomes_fingerprint": "worker-fp",
            "outcomes": [{"worker_id": "architect-0", "status": "completed"}],
            "completed_at": "2026-08-25T10:00:00+00:00",
        },
    )

    rejected = journal.reject_assembly(
        "action-1",
        coordinator_payload={"batch_plan": []},
        error_code="HOST_EVIDENCE_INVALID",
        violations=["PLAN_INVALID"],
    )

    assert rejected["outcomes_fingerprint"] == "worker-fp"
    assert rejected["outcomes"] == [
        {"worker_id": "architect-0", "status": "completed"}
    ]
    assert rejected["completed_at"] == "2026-08-25T10:00:00+00:00"


def test_only_prepared_candidate_can_be_accepted(tmp_path: Path) -> None:
    journal = OutcomeJournal(tmp_path)

    with pytest.raises(OutcomeJournalTransitionError, match="NOT_PREPARED"):
        journal.accept("action-1", accepted_result_message_id="result-1")

    journal.prepare("action-1", _result("action-1"), fingerprint="fp-1")
    journal.accept("action-1", accepted_result_message_id="result-1")

    accepted = json.loads(journal.path_for("action-1").read_text())
    assert accepted["status"] == "accepted"
    assert accepted["accepted_result_message_id"] == "result-1"
    assert accepted["repairable"] is False

    with pytest.raises(OutcomeJournalTransitionError, match="ALREADY_ACCEPTED"):
        journal.prepare("action-1", _result("action-1", suffix="2"), fingerprint="fp-2")
