"""Phase 53 T248：SQLite append-only EventStore。"""

from __future__ import annotations

import inspect
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

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
) -> LoopEvent:
    return LoopEvent.create(
        thread_id=thread_id,
        sequence=sequence,
        event_type=event_type,
        payload={"sequence": sequence},
        causation_id=causation_id,
        correlation_id=thread_id,
        event_id=event_id,
    )


def test_append_batch_and_query_preserve_stream_order() -> None:
    with SQLiteEventStore(":memory:") as store:
        store.append([_event(0), _event(1, event_type=LoopEventType.ACTION_ISSUED)])

        assert [event.sequence for event in store.load_stream("thread-1")] == [0, 1]
        assert store.next_sequence("thread-1") == 2


def test_latest_thread_for_event_uses_event_store_without_runtime_lease() -> None:
    with SQLiteEventStore(":memory:") as store:
        assert store.latest_thread_for_event(LoopEventType.LOOP_COMPLETED) is None
        store.append([_event(
            0,
            thread_id="completed-thread",
            event_type=LoopEventType.LOOP_COMPLETED,
        )])

        assert store.latest_thread_for_event("LoopCompleted") == "completed-thread"


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


def test_file_store_allocates_sequences_safely_across_threads(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"
    with SQLiteEventStore(db_path) as store:
        def append_one(index: int) -> int:
            return store.append_new(
                thread_id="thread-1",
                event_type=LoopEventType.GUARDRAIL_EVALUATED,
                payload={"index": index},
                correlation_id="thread-1",
            ).sequence

        with ThreadPoolExecutor(max_workers=3) as pool:
            sequences = list(pool.map(append_one, range(12)))

        assert sorted(sequences) == list(range(12))
        assert len(store.load_stream("thread-1")) == 12


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
    source = inspect.getsource(SQLiteEventStore)
    assert "json.dumps" not in source
    assert "json.loads" not in source


def test_event_store_has_one_canonical_schema_initializer() -> None:
    source = inspect.getsource(SQLiteEventStore)
    assert event_store_module._ensure_schema is event_store_schema.ensure_schema
    assert "CREATE TABLE" not in source
