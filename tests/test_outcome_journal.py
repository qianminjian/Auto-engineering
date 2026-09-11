"""宿主候选 Result 与 Core 接受事实的事务边界。"""

from __future__ import annotations

import hashlib
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


def test_core_repair_transaction_becomes_bounded_after_three_attempts(
    tmp_path: Path,
) -> None:
    """Core 连续拒绝同一 Action 时不能形成无限 Coordinator 修复循环。"""
    journal = OutcomeJournal(tmp_path)

    for attempt in range(1, 4):
        journal.prepare(
            "action-1",
            _result("action-1", suffix=str(attempt)),
            fingerprint=f"fp-{attempt}",
        )
        journal.reject(
            "action-1",
            error_code="ARCHITECT_PLAN_INVALID",
            violations=["OBLIGATION_UPDATE_REQUIRED:GAP-1"],
        )
        record = journal.load("action-1")
        assert record is not None
        assert record["attempt"] == attempt
        assert record["repairable"] is (attempt < 3)

    with pytest.raises(OutcomeJournalTransitionError, match="REPAIR_EXHAUSTED"):
        journal.prepare(
            "action-1",
            _result("action-1", suffix="4"),
            fingerprint="fp-4",
        )


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
    outcomes = [{"worker_id": "architect-0", "status": "completed"}]
    outcomes_fingerprint = hashlib.sha256(
        json.dumps(
            {"action_message_id": "action-1", "outcomes": outcomes},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    journal.prepare(
        "action-1",
        _result("action-1"),
        fingerprint="result-fp",
        extra={
            "outcomes_fingerprint": outcomes_fingerprint,
            "outcomes": outcomes,
            "completed_at": "2026-08-25T10:00:00+00:00",
        },
    )

    rejected = journal.reject_assembly(
        "action-1",
        coordinator_payload={"batch_plan": []},
        error_code="HOST_EVIDENCE_INVALID",
        violations=["PLAN_INVALID"],
    )

    assert rejected["outcomes_fingerprint"] == outcomes_fingerprint
    assert rejected["outcomes"] == outcomes
    assert rejected["completed_at"] == "2026-08-25T10:00:00+00:00"


def test_first_assembly_rejection_preserves_current_worker_facts(
    tmp_path: Path,
) -> None:
    """首次组装失败也必须保留本次已收集的 Worker 事实供恢复复用。"""
    journal = OutcomeJournal(tmp_path)
    outcomes = [{"worker_id": "architect-0", "status": "completed"}]

    rejected = journal.reject_assembly(
        "action-1",
        coordinator_payload={"plan": "过短"},
        error_code="HOST_EVIDENCE_INVALID",
        violations=["COORDINATOR_RESULT_INVALID"],
        outcomes=outcomes,
    )

    assert rejected["outcomes"] == outcomes
    assert rejected["outcomes_fingerprint"]


def test_assembly_rejection_repairs_inconsistent_outcome_pair(
    tmp_path: Path,
) -> None:
    """旧 Journal 的 outcomes 与指纹失配时不能继续复制损坏状态。"""
    journal = OutcomeJournal(tmp_path)
    first_outcomes = [{"worker_id": "architect-0", "status": "failed"}]
    journal.reject_assembly(
        "action-1",
        coordinator_payload={"plan": "首次计划"},
        error_code="HOST_EVIDENCE_INVALID",
        outcomes=first_outcomes,
    )

    corrupted = journal.load("action-1")
    assert corrupted is not None
    corrupted["outcomes_fingerprint"] = "0" * 64
    journal.path_for("action-1").write_text(
        json.dumps(corrupted),
        encoding="utf-8",
    )

    current_outcomes = [{"worker_id": "architect-0", "status": "completed"}]
    repaired = journal.reject_assembly(
        "action-1",
        coordinator_payload={"plan": "修复计划"},
        error_code="HOST_EVIDENCE_INVALID",
        outcomes=current_outcomes,
    )

    assert repaired["outcomes"] == current_outcomes
    expected = hashlib.sha256(
        json.dumps(
            {
                "action_message_id": "action-1",
                "outcomes": current_outcomes,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert repaired["outcomes_fingerprint"] == expected


def test_assembly_repair_becomes_bounded_after_three_attempts(
    tmp_path: Path,
) -> None:
    """同一 Action 的语义修复不能形成无限反馈循环。"""
    journal = OutcomeJournal(tmp_path)

    for attempt in range(1, 4):
        rejected = journal.reject_assembly(
            "action-1",
            coordinator_payload={"section_findings": []},
            error_code="HOST_EVIDENCE_INVALID",
            violations=["SECTION_FINDING_MISSING"],
        )
        assert rejected["attempt"] == attempt
        assert rejected["repairable"] is (attempt < 3)


def test_explicit_recovery_reopens_only_exhausted_assembly_repair(
    tmp_path: Path,
) -> None:
    journal = OutcomeJournal(tmp_path)

    for _ in range(3):
        journal.reject_assembly(
            "action-1",
            coordinator_payload={"section_findings": []},
            error_code="HOST_EVIDENCE_INVALID",
            violations=["SECTION_FINDING_MISSING"],
        )

    reopened = journal.reopen_assembly_repair(
        "action-1", reason="修复结果契约后显式恢复"
    )

    assert reopened["status"] == "assembly_rejected"
    assert reopened["attempt"] == 2
    assert reopened["repairable"] is True
    assert reopened["reopened_reason"] == "修复结果契约后显式恢复"
    assert len(reopened["rejection_history"]) == 3


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
