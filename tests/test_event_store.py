"""Phase 53 T248：SQLite append-only EventStore。"""

from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.loop import event_store as event_store_module
from auto_engineering.loop import event_store_codec, event_store_schema
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.events import LoopEvent, LoopEventType


def _event(
    sequence: int,
    *,
    thread_id: str = "thread-1",
    event_type: LoopEventType = LoopEventType.LOOP_INITIALIZED,
    causation_id: str | None = None,
    event_id: str | None = None,
    created_at: str | None = None,
) -> LoopEvent:
    return LoopEvent.create(
        thread_id=thread_id,
        sequence=sequence,
        event_type=event_type,
        payload={"sequence": sequence},
        causation_id=causation_id,
        correlation_id=thread_id,
        event_id=event_id,
        created_at=created_at,
    )


def test_append_batch_and_query_preserve_stream_order() -> None:
    with SQLiteEventStore(":memory:") as store:
        store.append([_event(0), _event(1, event_type=LoopEventType.ACTION_ISSUED)])

        assert [event.sequence for event in store.load_stream("thread-1")] == [0, 1]
        assert store.next_sequence("thread-1") == 2


def test_append_rejects_cross_thread_batch() -> None:
    with SQLiteEventStore(":memory:") as store:
        with pytest.raises(ValueError, match="一个 thread"):
            store.append([
                _event(0, thread_id="thread-1"),
                _event(0, thread_id="thread-2"),
            ])


def test_latest_thread_uses_latest_event_without_checkpoint() -> None:
    with SQLiteEventStore(":memory:") as store:
        store.append(
            [_event(0, thread_id="older-thread", created_at="2026-01-01T00:00:00+00:00")]
        )
        store.append(
            [
                _event(
                    0,
                    thread_id="newer-thread",
                    created_at="2026-01-02T00:00:00+00:00",
                )
            ]
        )

        assert store.latest_thread() == "newer-thread"


def test_unfinished_threads_finds_older_thread_after_newer_terminal_thread() -> None:
    with SQLiteEventStore(":memory:") as store:
        store.append([_event(0, thread_id="unfinished-thread")])
        store.append([_event(0, thread_id="finished-thread")])
        store.append([
            _event(
                1,
                thread_id="finished-thread",
                event_type=LoopEventType.LOOP_COMPLETED,
            )
        ])

        assert store.unfinished_threads() == ["unfinished-thread"]


def test_current_thread_prefers_older_unfinished_thread_over_newer_terminal_thread() -> None:
    with SQLiteEventStore(":memory:") as store:
        store.append([_event(0, thread_id="unfinished-thread")])
        store.append([_event(0, thread_id="finished-thread")])
        store.append([
            _event(
                1,
                thread_id="finished-thread",
                event_type=LoopEventType.LOOP_COMPLETED,
            )
        ])

        assert store.current_thread() == "unfinished-thread"


def test_current_thread_is_empty_after_all_threads_are_terminal() -> None:
    with SQLiteEventStore(":memory:") as store:
        store.append([_event(0, thread_id="finished-thread")])
        store.append([_event(
            1,
            thread_id="finished-thread",
            event_type=LoopEventType.LOOP_COMPLETED,
        )])

        assert store.current_thread() is None


def test_current_thread_rejects_multiple_unfinished_threads() -> None:
    with SQLiteEventStore(":memory:") as store:
        store.append([_event(0, thread_id="thread-a")])
        store.append([_event(0, thread_id="thread-b")])

        with pytest.raises(ValueError, match="PROJECT_THREAD_AMBIGUOUS"):
            store.current_thread()


def test_duplicate_event_id_rolls_back_entire_batch() -> None:
    with SQLiteEventStore(":memory:") as store:
        duplicate_id = "same-event"

        with pytest.raises(sqlite3.IntegrityError):
            store.append([_event(0, event_id=duplicate_id), _event(1, event_id=duplicate_id)])

        assert store.load_stream("thread-1") == []


def test_duplicate_stream_sequence_is_rejected_without_partial_write() -> None:
    with SQLiteEventStore(":memory:") as store:
        store.append([_event(0)])

        with pytest.raises(ValueError, match="连续"):
            store.append([_event(1), _event(0, event_type=LoopEventType.ACTION_ISSUED)])

        assert [event.sequence for event in store.load_stream("thread-1")] == [0]


def test_result_accepted_requires_causation_id() -> None:
    with SQLiteEventStore(":memory:") as store:
        with pytest.raises(ValueError, match="causation_id"):
            store.append([_event(0, event_type=LoopEventType.RESULT_ACCEPTED)])


def test_store_rejects_sequence_gap() -> None:
    with SQLiteEventStore(":memory:") as store:
        with pytest.raises(ValueError, match="连续"):
            store.append([_event(1)])


def test_file_store_appends_explicit_sequences(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"
    with SQLiteEventStore(db_path) as store:
        for index in range(12):
            store.append([_event(index, event_type=LoopEventType.GUARDRAIL_EVALUATED)])
        assert len(store.load_stream("thread-1")) == 12


def test_semantic_signature_is_canonical_thread_scoped_and_read_only(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "events.db"
    with SQLiteEventStore(db_path) as store:
        store.append([_event(0, thread_id="thread-1")])
        store.append([_event(0, thread_id="thread-2")])
        signature = store.semantic_signature("thread-1")
        assert signature is not None
        assert signature[0] == "thread-1"
        assert signature[1:3] == (0, 1)

    with SQLiteEventStore(db_path, read_only=True) as store:
        assert store.semantic_signature("thread-1") == signature
        with pytest.raises(sqlite3.OperationalError):
            store.append([_event(1, thread_id="thread-1")])


def test_semantic_signature_without_active_thread_is_empty() -> None:
    with SQLiteEventStore(":memory:") as store:
        store.append([_event(0, event_type=LoopEventType.LOOP_COMPLETED)])
        assert store.semantic_signature() is None

    with pytest.raises(ValueError, match="READ_ONLY"):
        SQLiteEventStore(":memory:", read_only=True)


def test_close_is_idempotent_and_rejects_further_use(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.db")
    store.close()
    store.close()

    with pytest.raises(RuntimeError, match="已关闭"):
        store.load_stream("thread-1")


def test_event_store_has_one_canonical_persistence_codec() -> None:
    """持久化编解码必须集中在单一模块，避免 EventStore 再长出第二套逻辑。"""

    assert event_store_module._json_dumps is event_store_codec.dumps
    assert event_store_module._json_loads is event_store_codec.loads
    assert SQLiteEventStore._row_to_event is event_store_codec.event_from_row


def test_event_store_rebuilds_projection_from_its_event_stream() -> None:
    state = EngineState(thread_id="thread-1", current_stage="architect")
    event = LoopEvent.create(
        thread_id=state.thread_id,
        sequence=0,
        event_type=LoopEventType.LOOP_INITIALIZED,
        payload={"state": state.to_dict()},
        correlation_id=state.thread_id,
    )
    with SQLiteEventStore(":memory:") as store:
        store.append([event])
        store._conn.execute(
            "DELETE FROM engine_state_projections WHERE thread_id = ?",
            (state.thread_id,),
        )
        store._conn.commit()

        rebuilt = store.rebuild_projection(state.thread_id)

        assert rebuilt.thread_id == state.thread_id
        assert store.load_projection(state.thread_id) is not None


def test_event_store_rejects_replacing_unknown_result_replay() -> None:
    with SQLiteEventStore(":memory:") as store:
        with pytest.raises(ValueError, match="回放记录"):
            store.replace_protocol_result_response(
                "thread-1", "missing-result", {"action": "done"}
            )
    source = inspect.getsource(SQLiteEventStore)
    assert "json.dumps" not in source
    assert "json.loads" not in source


def test_event_store_has_one_canonical_schema_initializer() -> None:
    source = inspect.getsource(SQLiteEventStore)
    assert event_store_module._ensure_schema is event_store_schema.ensure_schema
    assert "CREATE TABLE" not in source
