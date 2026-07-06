"""P2-B-4 (deep audit) — loop/checkpoint/records.py 直接测试.

95 行 records.py (CheckpointMeta + Checkpoint[T] + 3 异常类) 之前
仅通过 __init__.py re-export + store.py 间接使用, 没有直接测试
Checkpoint[T] 泛型 + meta() 提取 + 异常类属性. SQLiteCheckpointStore
依赖这些数据类的字段契约.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from auto_engineering.loop.checkpoint.records import (
    Checkpoint,
    CheckpointError,
    CheckpointMeta,
    CheckpointNotFoundError,
    CheckpointSchemaMismatchError,
)
from auto_engineering.loop.convergence import RoundHistory


class TestCheckpointMeta:
    """CheckpointMeta 轻量元数据."""

    def test_construction(self) -> None:
        now = datetime.now(timezone.utc)
        meta = CheckpointMeta(
            id="cp-1",
            round=1,
            step=0,
            created_at=now,
            schema_version=1,
        )
        assert meta.id == "cp-1"
        assert meta.round == 1
        assert meta.parent_id is None
        assert meta.tag is None

    def test_with_parent_and_tag(self) -> None:
        meta = CheckpointMeta(
            id="cp-2",
            round=2,
            step=1,
            created_at=datetime.now(timezone.utc),
            schema_version=1,
            parent_id="cp-1",
            tag="before-refactor",
        )
        assert meta.parent_id == "cp-1"
        assert meta.tag == "before-refactor"


class TestCheckpoint:
    """Checkpoint[T] 泛型 + meta() 提取."""

    def test_construction_with_state(self) -> None:
        """构造 Checkpoint, state 是 Any 类型 (典型 CheckpointEnvelope)."""
        state = {"requirement": "build X"}  # duck-typed
        cp = Checkpoint[dict](
            id="cp-1",
            round=1,
            step=0,
            state=state,
            history=[],
            created_at=datetime.now(timezone.utc),
            schema_version=1,
        )
        assert cp.state is state
        assert cp.history == []

    def test_meta_extracts_metadata(self) -> None:
        """meta() 从 Checkpoint 提取 CheckpointMeta (用于 list_all 轻量)."""
        now = datetime.now(timezone.utc)
        cp = Checkpoint[dict](
            id="cp-1",
            round=1,
            step=0,
            state={"x": 1},
            history=[RoundHistory(round_id=1)],
            created_at=now,
            schema_version=1,
            parent_id="cp-0",
            tag="manual",
        )
        meta = cp.meta()
        assert meta.id == "cp-1"
        assert meta.round == 1
        assert meta.step == 0
        assert meta.created_at == now
        assert meta.schema_version == 1
        assert meta.parent_id == "cp-0"
        assert meta.tag == "manual"

    def test_meta_excludes_state_and_history(self) -> None:
        """meta() 提取元数据, 不含 state/history (轻量目的)."""
        cp = Checkpoint[dict](
            id="cp-1",
            round=1,
            step=0,
            state={"huge": "x" * 10000},
            history=[RoundHistory(round_id=1)] * 100,
            created_at=datetime.now(timezone.utc),
            schema_version=1,
        )
        meta = cp.meta()
        # meta 没有 state/history 字段 (dataclass CheckpointMeta)
        assert not hasattr(meta, "state")
        assert not hasattr(meta, "history")


class TestCheckpointExceptions:
    """3 个异常类 + 错误链."""

    def test_checkpoint_error_is_exception(self) -> None:
        err = CheckpointError("base error")
        assert isinstance(err, Exception)
        assert str(err) == "base error"

    def test_checkpoint_not_found_error_inherits_base(self) -> None:
        err = CheckpointNotFoundError("cp-xyz not found")
        assert isinstance(err, CheckpointError)
        assert isinstance(err, Exception)
        assert "cp-xyz not found" in str(err)

    def test_checkpoint_schema_mismatch_error_attributes(self) -> None:
        """SchemaMismatchError 暴露 found/expected 字段供上层处理."""
        err = CheckpointSchemaMismatchError(found=2, expected=1)
        assert err.found == 2
        assert err.expected == 1
        assert isinstance(err, CheckpointError)
        assert "found 2" in str(err)
        assert "expected 1" in str(err)


# ============================================================
# IV. SQLiteCheckpointStore 连接缓存 + WAL (P2-D-3, v2.5)
# ============================================================


class TestStoreFileConnectionCache:
    """v2.5 P2-D-3: file 模式缓存连接 + WAL 加速.

    之前每操作 connect/close + CREATE TABLE 检查 (~3 DDL) + 默认
    DELETE journal mode. 改为: 启动时一次 init_file_conn (WAL +
    schema), 后续操作复用 self._file_conn. close() 显式释放.
    """

    def test_file_mode_caches_connection(self, tmp_path: Path) -> None:
        """file 模式启动后 self._file_conn 不为 None (缓存生效)."""
        from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

        db_path = tmp_path / "test.db"
        store = SQLiteCheckpointStore(str(db_path))
        try:
            assert store._file_conn is not None
            # 多次操作复用同一 connection (id 相同)
            cid1 = store._file_conn  # 保存引用
            store.save(state={"x": 1}, round=1)
            assert store._file_conn is cid1
            store.save(state={"x": 2}, round=2)
            assert store._file_conn is cid1
        finally:
            store.close()

    def test_file_mode_uses_wal_journal(self, tmp_path: Path) -> None:
        """file 模式连接应启用 PRAGMA journal_mode=WAL."""
        from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

        db_path = tmp_path / "test.db"
        store = SQLiteCheckpointStore(str(db_path))
        try:
            journal_mode = store._file_conn.execute(
                "PRAGMA journal_mode"
            ).fetchone()[0]
            assert journal_mode.lower() == "wal", (
                f"file 模式应启用 WAL, 实际: {journal_mode!r}"
            )
        finally:
            store.close()

    def test_close_releases_connection(self, tmp_path: Path) -> None:
        """close() 释放 self._file_conn (置 None)."""
        from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

        db_path = tmp_path / "test.db"
        store = SQLiteCheckpointStore(str(db_path))
        assert store._file_conn is not None
        store.close()
        assert store._file_conn is None
        assert store._shared_conn is None

    def test_context_manager_protocol(self, tmp_path: Path) -> None:
        """with SQLiteCheckpointStore(...) as store: → 自动 close."""
        from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

        db_path = tmp_path / "test.db"
        with SQLiteCheckpointStore(str(db_path)) as store:
            assert store._file_conn is not None
        # 退出 with 块 → close 自动调
        assert store._file_conn is None

    def test_memory_mode_unchanged(self) -> None:
        """:memory: 模式仍走 _shared_conn + threading.Lock (无 WAL)."""
        from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

        with SQLiteCheckpointStore(":memory:") as store:
            assert store._shared_conn is not None
            assert store._file_conn is None  # file 模式不适用
            # memory 模式默认 DELETE journal, 不强制 WAL
            journal_mode = store._shared_conn.execute(
                "PRAGMA journal_mode"
            ).fetchone()[0]
            assert journal_mode.lower() == "memory", (
                f"memory 模式应报 journal_mode=memory, 实际: {journal_mode!r}"
            )
