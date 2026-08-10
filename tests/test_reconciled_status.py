"""Phase 81 T427：协调后的状态只投影 Current Work Set。"""

from types import SimpleNamespace

from auto_engineering.loop.status_projection import reconciliation_status


def test_reconciliation_status_exposes_revision_history_and_true_next_task() -> None:
    state = SimpleNamespace(
        plan_reconciliation={
            "source_revision": 2,
            "current_revision": 3,
            "verified_completed": 1,
            "still_pending": 1,
            "superseded": 1,
            "unverifiable": 1,
        },
        superseded_tasks=[
            {"task_id": "B1-T2", "status": "superseded"},
            {"task_id": "B1-T3", "status": "unverifiable"},
        ],
    )
    batch_state = SimpleNamespace(
        is_all_complete=lambda: False,
        current_batch=lambda: {
            "batch_id": "B2",
            "tasks": [{"id": "B2-T1"}, {"id": "B2-T2"}],
        },
    )

    assert reconciliation_status(state, batch_state) == {
        "source_revision": 2,
        "current_revision": 3,
        "verified_completed": 1,
        "still_pending": 1,
        "superseded": 1,
        "unverifiable": 1,
        "historical_tasks": [
            {"task_id": "B1-T2", "status": "superseded"},
            {"task_id": "B1-T3", "status": "unverifiable"},
        ],
        "next_batch": "B2",
        "next_task": "B2-T1",
    }


def test_reconciliation_status_absent_before_reconciliation() -> None:
    state = SimpleNamespace(plan_reconciliation=None, superseded_tasks=[])

    assert reconciliation_status(state, None) is None
