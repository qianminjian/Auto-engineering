"""Tests for checkpoint/_connection.py + checkpoint/store.py."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from auto_engineering.loop.checkpoint._connection import (
    _atomic,
    _ensure_schema,
    _with_conn,
    init_file_conn,
)
from auto_engineering.loop.checkpoint.records import (
    Checkpoint,
    CheckpointMeta,
    CheckpointNotFoundError,
)
from auto_engineering.loop.checkpoint.store import (
    DB_SCHEMA_VERSION,
    SQLiteCheckpointStore,
)

# ============================================================
# Group 1: _with_conn
# ============================================================


class TestWithConn:
    def test_memory_mode_yields_shared_conn(self):
        shared = sqlite3.connect(":memory:")
        shared.row_factory = sqlite3.Row
        lock = threading.Lock()
        with _with_conn(":memory:", is_memory=True, lock=lock, shared_conn=shared) as conn:
            assert conn is shared

    def test_file_mode_one_shot_connects_and_closes(self, tmp_path: Path):
        db = str(tmp_path / "test.db")
        lock = threading.Lock()
        with _with_conn(db, is_memory=False, lock=lock, shared_conn=None) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS t (x int)")
            conn.execute("INSERT INTO t VALUES (1)")
            conn.commit()
        verify = sqlite3.connect(db)
        verify.row_factory = sqlite3.Row
        rows = verify.execute("SELECT * FROM t").fetchall()
        assert len(rows) == 1
        verify.close()

    def test_file_mode_reuses_cached_conn(self, tmp_path: Path):
        db = str(tmp_path / "test.db")
        lock = threading.Lock()
        cached = sqlite3.connect(db, check_same_thread=False)
        cached.row_factory = sqlite3.Row
        _ensure_schema(cached)
        with _with_conn(db, is_memory=False, lock=lock, shared_conn=None, file_conn=cached) as conn:
            assert conn is cached

    def test_file_mode_schema_created_on_first_use(self, tmp_path: Path):
        db = str(tmp_path / "test.db")
        lock = threading.Lock()
        with _with_conn(db, is_memory=False, lock=lock, shared_conn=None) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'"
            ).fetchall()
            assert len(tables) == 1


# ============================================================
# Group 2: _atomic
# ============================================================


class TestAtomic:
    def test_commit_on_success(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE t (x int)")
        with _atomic(conn):
            conn.execute("INSERT INTO t VALUES (42)")
        rows = conn.execute("SELECT * FROM t").fetchall()
        assert len(rows) == 1

    def test_rollback_on_sqlite_error(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE t (x int PRIMARY KEY)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
        try:
            with _atomic(conn):
                conn.execute("INSERT INTO t VALUES (2)")
                conn.execute("INSERT INTO t VALUES (2)")  # duplicate key
        except sqlite3.IntegrityError:
            pass
        rows = conn.execute("SELECT x FROM t").fetchall()
        assert [r[0] for r in rows] == [1]  # value 2 was rolled back


# ============================================================
# Group 3: init_file_conn
# ============================================================


class TestInitFileConn:
    def test_creates_connection_with_wal(self, tmp_path: Path):
        db = str(tmp_path / "test.db")
        lock = threading.Lock()
        conn = init_file_conn(db, lock)
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal.upper() == "WAL"
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'"
        ).fetchall()
        assert len(tables) == 1
        conn.close()


# ============================================================
# Group 4: SQLiteCheckpointStore
# ============================================================


@pytest.fixture
def store():
    s = SQLiteCheckpointStore[dict](":memory:")
    return s


def _fake_state(round_num: int = 0, step: str = "idle") -> dict:
    return {"round": round_num, "step": step, "status": "running"}


def _fake_history(item_count: int = 1) -> list[dict]:
    return [{"round_id": i, "verdict": "APPROVE"} for i in range(item_count)]


class TestStoreSaveLoad:
    def test_save_and_load_roundtrip(self, store):
        state = _fake_state(1, "developer")
        history = _fake_history(2)
        ck_id = store.save(state, round=1, history=history, step=1)
        assert isinstance(ck_id, str)

        ck: Checkpoint = store.load(ck_id)
        assert ck.round == 1
        assert ck.step == 1
        assert ck.schema_version == DB_SCHEMA_VERSION
        assert ck.state == state
        assert len(ck.history) == 2

    def test_save_preserves_state_identity(self, store):
        state = {"round": 5, "step": "critic", "status": "drained"}
        ck_id = store.save(state, round=5, history=[], step=3)
        ck = store.load(ck_id)
        assert ck.state == state

    def test_load_nonexistent_raises(self, store):
        with pytest.raises(CheckpointNotFoundError):
            store.load("nonexistent-id")

    def test_save_with_multiple_entries(self, store):
        for i in range(5):
            store.save(_fake_state(i), round=i, history=_fake_history(1), step=0)
        assert store.count() == 5


class TestStoreList:
    def test_list_all_returns_meta_sorted(self, store):
        for i in range(3):
            store.save(_fake_state(i), round=i, history=[], step=0)
        items = store.list_all()
        assert len(items) == 3
        assert all(isinstance(item, CheckpointMeta) for item in items)
        assert items[0].round <= items[1].round <= items[2].round

    def test_list_all_empty(self, store):
        assert store.list_all() == []


class TestStoreCount:
    def test_count_zero_initially(self, store):
        assert store.count() == 0

    def test_count_after_saves(self, store):
        store.save(_fake_state(), round=1, history=[], step=0)
        store.save(_fake_state(), round=2, history=[], step=0)
        assert store.count() == 2


class TestStoreDelete:
    def test_delete_existing(self, store):
        ck_id = store.save(_fake_state(), round=1, history=[], step=0)
        assert store.count() == 1
        store.delete(ck_id)
        assert store.count() == 0

    def test_delete_nonexistent_does_not_raise(self, store):
        store.delete("nonexistent-id")


class TestStoreClear:
    def test_clear_removes_all(self, store):
        for i in range(3):
            store.save(_fake_state(i), round=i, history=[], step=0)
        assert store.count() == 3
        store.clear()
        assert store.count() == 0


class TestStoreLoadLatest:
    def test_load_latest_returns_most_recent(self, store):
        store.save(_fake_state(1), round=1, history=[], step=0)
        store.save(_fake_state(3), round=3, history=[], step=1)
        store.save(_fake_state(2), round=2, history=[], step=0)
        ck = store.load_latest()
        assert ck is not None
        assert ck.round == 2  # 最后保存的 round=2, 非最高 round=3

    def test_load_latest_empty_store_returns_none(self, store):
        assert store.load_latest() is None


class TestStoreLoadByRound:
    def test_load_by_round_finds_match(self, store):
        store.save(_fake_state(1), round=1, history=[], step=0)
        s2 = {"special": True, "round": 2, "step": "critic", "status": "running"}
        store.save(s2, round=2, history=[], step=1)
        ck = store.load_by_round(2)
        assert ck is not None
        assert ck.round == 2

    def test_load_by_round_not_found_returns_none(self, store):
        store.save(_fake_state(1), round=1, history=[], step=0)
        assert store.load_by_round(99) is None


class TestStoreMemoryVsFile:
    def test_file_store_persists_across_connections(self, tmp_path: Path):
        db = str(tmp_path / "ck.db")
        s1 = SQLiteCheckpointStore[dict](db)
        ck_id = s1.save(_fake_state(42), round=42, history=[], step=0)

        s2 = SQLiteCheckpointStore[dict](db)
        ck = s2.load(ck_id)
        assert ck.state["round"] == 42
        s1.close()
        s2.close()
