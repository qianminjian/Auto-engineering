"""v5.8 T320：rollover 崩溃恢复与成本基线。"""

from __future__ import annotations

from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
from auto_engineering.loop.resume_capsule import ResumeCapsule
from auto_engineering.metrics.usage_ledger import UsageLedger, UsageRecord


def test_crash_after_rollover_recovers_action_and_attributed_cost(tmp_path) -> None:
    checkpoint_path = tmp_path / "checkpoint.db"
    capsule = ResumeCapsule.create(
        thread_id="thread-1",
        source_session_id="session-1",
        projection_sequence=50,
        active_action={
            "message_id": "action-51",
            "action": "developer",
            "tick": 51,
        },
        state_digest={"stage": "developer", "tick": 50, "active_batch_id": "B8"},
        issued_at="2026-07-30T00:00:00+00:00",
    )
    before_crash = SQLiteCheckpointStore[dict](checkpoint_path)
    rollover = before_crash.record_session_rollover(
        thread_id="thread-1",
        source_session_id="session-1",
        reason="host_process_lost",
        capsule=capsule,
        claim_token="claim-50",
        artifact_id="capsule-50",
    )
    before_crash.close()

    after_restart = SQLiteCheckpointStore[dict](checkpoint_path)
    restored = after_restart.claim_session(
        claim_token=rollover["claim_token"],
        session_id="session-2",
        host="codex",
    )
    replay = after_restart.claim_session(
        claim_token=rollover["claim_token"],
        session_id="session-2",
        host="codex",
    )
    after_restart.close()

    ledger = UsageLedger(tmp_path / "usage.db")
    for session_id, tick, input_units in (
        ("session-1", 50, 600),
        ("session-2", 51, 40),
    ):
        ledger.append(UsageRecord(
            thread_id="thread-1",
            session_id=session_id,
            tick=tick,
            stage="developer",
            worker="main",
            input_units=input_units,
            cache_read_units=100 if session_id == "session-1" else 0,
            cache_write_units=0,
            output_units=10,
            provider="test-provider",
            model="test-model",
            usage_source="fixture",
            estimated=False,
        ))
    totals = ledger.aggregate("thread-1")
    ledger.close()

    assert restored == replay == capsule.active_action
    assert restored["message_id"] == "action-51"
    assert totals["input_units"] == 640
    assert totals["cache_read_units"] == 100
    assert totals["attribution_rate"] == 1.0
