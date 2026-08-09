"""Phase 53 T252：投影删除后的端到端重放验收。"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.events import LoopEvent, LoopEventType, LoopEventValidationError


def _action(message_id: str, tick: int, stage: str) -> dict[str, object]:
    return {
        "schema_version": "1.1",
        "message_type": "action",
        "message_id": message_id,
        "thread_id": "thread-1",
        "tick": tick,
        "stage": stage,
        "correlation_id": "thread-1",
        "extensions": {},
        "action": stage,
    }


def test_deleted_projection_rebuilds_to_last_committed_state(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"
    initial = EngineState(
        thread_id="thread-1",
        requirement="重放验收",
        current_stage="architect",
    )
    final = EngineState.from_dict(
        {
            **initial.to_dict(),
            "tick": 1,
            "round": 1,
            "current_stage": "developer",
            "files_changed": ["auto_engineering/loop/event_store.py"],
        }
    )
    with SQLiteEventStore(db_path) as store:
        initialized = LoopEvent.create(
            thread_id="thread-1",
            sequence=0,
            event_type=LoopEventType.LOOP_INITIALIZED,
            payload={"state": initial.to_dict()},
            correlation_id="thread-1",
        )
        issued = LoopEvent.create(
            thread_id="thread-1",
            sequence=1,
            event_type=LoopEventType.ACTION_ISSUED,
            payload={"action": _action("action-1", 0, "architect")},
            correlation_id="thread-1",
        )
        store.commit_tick(
            events=[initialized, issued],
            state=initial,
            action=_action("action-1", 0, "architect"),
        )
        accepted = LoopEvent.create(
            thread_id="thread-1",
            sequence=2,
            event_type=LoopEventType.RESULT_ACCEPTED,
                payload={
                    "result_message_id": "result-1",
                    "state_patch": final.to_dict(),
                    "legacy_import": True,
                },
            causation_id="action-1",
            correlation_id="thread-1",
        )
        next_action = LoopEvent.create(
            thread_id="thread-1",
            sequence=3,
            event_type=LoopEventType.ACTION_ISSUED,
            payload={"action": _action("action-2", 1, "developer")},
            causation_id="result-1",
            correlation_id="thread-1",
        )
        store.commit_tick(
            events=[accepted, next_action],
            state=final,
            action=_action("action-2", 1, "developer"),
        )

    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "DELETE FROM engine_state_projections WHERE thread_id = ?",
            ("thread-1",),
        )
        conn.commit()

    with SQLiteEventStore(db_path) as store:
        assert store.load_projection("thread-1") is None
        rebuilt = store.rebuild_projection("thread-1")
        assert rebuilt.to_dict() == final.to_dict()
        assert store.load_projection("thread-1").to_dict() == final.to_dict()
        assert store.load_action_snapshot("thread-1") == _action(
            "action-2", 1, "developer"
        )


def test_payload_tampering_is_detected_before_replay(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"
    state = EngineState(thread_id="thread-1")
    with SQLiteEventStore(db_path) as store:
        store.import_checkpoint(checkpoint_id="cp-1", state=state)

    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "UPDATE loop_events SET payload_json = ? WHERE thread_id = ?",
            ('{"checkpoint_id":"cp-1","state":{"thread_id":"tampered"}}', "thread-1"),
        )
        conn.commit()

    with SQLiteEventStore(db_path) as store:
        with pytest.raises(LoopEventValidationError, match="payload_sha256"):
            store.rebuild_projection("thread-1")
