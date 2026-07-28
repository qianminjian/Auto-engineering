"""Phase 53 T251：v5.6 checkpoint 一次性导入事件日志。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.checkpoint.migration import import_v56_checkpoint
from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.events import LoopEventType


def test_import_is_idempotent_and_does_not_rewrite_checkpoint(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "v56.db"
    event_path = tmp_path / "v57.db"
    state = EngineState(thread_id="thread-1", current_stage="critic", tick=7)
    with SQLiteCheckpointStore[EngineState](checkpoint_path) as checkpoints:
        checkpoint_id = checkpoints.save(state, round=2, step=7)
        before = checkpoints.load(checkpoint_id)
        with SQLiteEventStore(event_path) as events:
            first = checkpoints.import_to_event_store(events, checkpoint_id)
            second = checkpoints.import_to_event_store(events, checkpoint_id)

            assert first.event_id == second.event_id
            assert first.event_type is LoopEventType.CHECKPOINT_IMPORTED
            assert len(events.load_stream("thread-1")) == 1
            assert events.load_projection("thread-1").to_dict() == state.to_dict()

        after = checkpoints.load(checkpoint_id)
        assert checkpoints.count() == 1
        assert after.state.to_dict() == before.state.to_dict()
        assert after.created_at == before.created_at


def test_corrupted_checkpoint_fails_closed_without_import_marker(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "v56.db"
    event_path = tmp_path / "v57.db"
    with SQLiteCheckpointStore[dict](checkpoint_path) as checkpoints:
        checkpoint_id = checkpoints.save({"corrupted": True}, round=0)
        with SQLiteEventStore(event_path) as events:
            with pytest.raises(ValueError, match="损坏"):
                import_v56_checkpoint(checkpoints, events, checkpoint_id)
            assert events.load_stream("thread-1") == []


def test_new_event_thread_does_not_create_legacy_tables(tmp_path: Path) -> None:
    event_path = tmp_path / "v57.db"
    state = EngineState(thread_id="thread-1", current_stage="architect")
    event_payload = {"state": state.to_dict()}
    with SQLiteEventStore(event_path) as events:
        event = events.import_checkpoint(
            checkpoint_id="seed",
            state=state,
        )
        assert event.to_dict()["payload"] == {
            "checkpoint_id": "seed",
            **event_payload,
        }

    with sqlite3.connect(event_path) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "checkpoints" not in names
    assert "protocol_actions" not in names
