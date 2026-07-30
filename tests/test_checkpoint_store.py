"""Tests for checkpoint/_connection.py + checkpoint/store.py."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from auto_engineering.engine.state import EngineState
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
from auto_engineering.loop.resume_capsule import ResumeCapsule
from auto_engineering.loop.session_handoff import SessionHandoffError

# ============================================================
# Group 1: _with_conn
# ============================================================


class TestWithConn:
    def test_memory_mode_yields_shared_conn(self):
        shared = sqlite3.connect(":memory:")
        try:
            shared.row_factory = sqlite3.Row
            lock = threading.Lock()
            with _with_conn(":memory:", is_memory=True, lock=lock, shared_conn=shared) as conn:
                assert conn is shared
        finally:
            shared.close()

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
        try:
            cached.row_factory = sqlite3.Row
            _ensure_schema(cached)
            with _with_conn(db, is_memory=False, lock=lock, shared_conn=None, file_conn=cached) as conn:
                assert conn is cached
        finally:
            cached.close()

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
        try:
            conn.execute("CREATE TABLE t (x int)")
            with _atomic(conn):
                conn.execute("INSERT INTO t VALUES (42)")
            rows = conn.execute("SELECT * FROM t").fetchall()
            assert len(rows) == 1
        finally:
            conn.close()

    def test_rollback_on_sqlite_error(self):
        conn = sqlite3.connect(":memory:")
        try:
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
        finally:
            conn.close()


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

    def test_closes_connection_when_initialization_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """初始化 PRAGMA 或 schema 失败时不得泄漏已创建的连接."""
        class FailingConnection:
            closed = False
            row_factory = None

            def execute(self, _sql: str) -> None:
                raise sqlite3.DatabaseError("corrupted database")

            def close(self) -> None:
                self.closed = True

        conn = FailingConnection()
        monkeypatch.setattr(sqlite3, "connect", lambda *_args, **_kwargs: conn)

        with pytest.raises(sqlite3.DatabaseError, match="corrupted database"):
            init_file_conn("corrupt.db", threading.Lock())

        assert conn.closed is True


# ============================================================
# Group 4: SQLiteCheckpointStore
# ============================================================


@pytest.fixture
def store():
    s = SQLiteCheckpointStore[dict](":memory:")
    try:
        yield s
    finally:
        s.close()


def _fake_state(round_num: int = 0, step: int | str = 0) -> dict:
    return {"round": round_num, "step": step, "status": "running"}


def _fake_history(item_count: int = 1) -> list[dict]:
    return [{"round_id": i, "verdict": "APPROVE"} for i in range(item_count)]


class TestStoreSaveLoad:
    def test_large_state_fields_are_content_addressed_and_reused(self, store):
        shared_plan = [{"batch_id": "B1", "payload": "x" * 4096}]
        first = EngineState(
            thread_id="thread-1",
            batch_plan=shared_plan,
            progress_tree_json="y" * 4096,
            tick=1,
        )
        second = EngineState(
            thread_id="thread-1",
            batch_plan=shared_plan,
            progress_tree_json="y" * 4096,
            tick=2,
        )

        first_id = store.save(first, round=1)
        second_id = store.save(second, round=2)

        with store._conn() as conn:
            blobs = conn.execute(
                "SELECT COUNT(*) AS count FROM checkpoint_blobs"
            ).fetchone()["count"]
            persisted = conn.execute(
                "SELECT state_json FROM checkpoints WHERE id = ?",
                (second_id,),
            ).fetchone()["state_json"]
        assert blobs == 2
        assert len(persisted) < 2000
        assert store.load(first_id).state == first
        assert store.load(second_id).state == second

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


class TestSessionHandoffPersistence:
    @staticmethod
    def _capsule() -> ResumeCapsule:
        return ResumeCapsule.create(
            thread_id="thread-1",
            source_session_id="session-1",
            projection_sequence=5,
            active_action={"message_id": "action-5", "action": "developer"},
            state_digest={"stage": "developer"},
            issued_at="2026-07-30T00:00:00+00:00",
        )

    def test_rollover_and_claim_survive_store_reopen(self, tmp_path: Path):
        db = tmp_path / "handoff.db"
        first = SQLiteCheckpointStore[dict](db)
        action = first.record_session_rollover(
            thread_id="thread-1",
            source_session_id="session-1",
            reason="tick_limit",
            capsule=self._capsule(),
            claim_token="claim-1",
            artifact_id="capsule-1",
        )
        first.close()

        second = SQLiteCheckpointStore[dict](db)
        replay = second.record_session_rollover(
            thread_id="thread-1",
            source_session_id="session-1",
            reason="tick_limit",
            capsule=self._capsule(),
            claim_token="different-ignored",
            artifact_id="different-ignored",
        )
        claimed = second.claim_session(
            claim_token="claim-1",
            session_id="session-2",
            host="codex",
        )

        assert replay == action
        assert claimed == {"message_id": "action-5", "action": "developer"}
        second.close()

    def test_competing_persistent_claim_is_rejected(self, store):
        store.record_session_rollover(
            thread_id="thread-1",
            source_session_id="session-1",
            reason="manual",
            capsule=self._capsule(),
            claim_token="claim-1",
            artifact_id="capsule-1",
        )
        store.claim_session(
            claim_token="claim-1",
            session_id="session-2",
            host="claude_code",
        )

        with pytest.raises(SessionHandoffError) as exc:
            store.claim_session(
                claim_token="claim-1",
                session_id="session-3",
                host="codex",
            )

        assert exc.value.error_code == "SESSION_CLAIM_CONFLICT"
