"""v2.0 SQLite Checkpoint 持久化.

设计来源: design/v2.0-Analysis-Loop.md §4.4 + §五 Phase 1.2

核心要点:
    - SQLite 持久化 LoopState + history
    - Schema 版本号 (兼容未来 schema 变更, 旧版可迁移或拒绝)
    - 事务保证 (save/load 原子性)
    - 并发安全: file 模式每线程独立 connection, ":memory:" 模式用单 connection + 锁
    - JSON 序列化 LoopState (Pydantic model_dump)

API:
    store = SQLiteCheckpointStore(db_path)
    store.save(state, round, history=...) -> checkpoint_id
    store.load_latest() -> Checkpoint | None
    store.load(checkpoint_id) -> Checkpoint | None
    store.list_all() -> list[CheckpointMeta]
    store.delete(checkpoint_id) -> bool

Note: SQLite ":memory:" 数据库是 per-connection 的, 跨 connection 不共享数据.
    本实现在 ":memory:" 模式下用单 connection + threading.Lock 序列化访问,
    满足测试场景的并发隔离需求.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Schema 版本号 (变更时 +1, 用于未来兼容)
SCHEMA_VERSION = 1


# ============================================================
# 数据类: Checkpoint 元数据 + 完整记录
# ============================================================


@dataclass
class CheckpointMeta:
    """Checkpoint 元数据 (轻量, 用于 list)."""

    id: str
    round: int
    step: int
    created_at: datetime
    schema_version: int
    parent_id: str | None = None
    tag: str | None = None


@dataclass
class Checkpoint:
    """完整 Checkpoint (含 state + history)."""

    id: str
    round: int
    step: int
    state: Any  # LoopState (避免循环引用, 类型宽泛)
    history: list[dict[str, Any]]  # RoundHistory 序列化列表
    created_at: datetime
    schema_version: int
    parent_id: str | None = None
    tag: str | None = None

    def meta(self) -> CheckpointMeta:
        """提取元数据."""
        return CheckpointMeta(
            id=self.id,
            round=self.round,
            step=self.step,
            created_at=self.created_at,
            schema_version=self.schema_version,
            parent_id=self.parent_id,
            tag=self.tag,
        )


# ============================================================
# Checkpoint Store 异常
# ============================================================


class CheckpointError(Exception):
    """Checkpoint 操作基础异常."""


class CheckpointNotFoundError(CheckpointError):
    """Checkpoint 不存在."""


class CheckpointSchemaMismatchError(CheckpointError):
    """Schema 版本不匹配."""

    def __init__(self, found: int, expected: int) -> None:
        self.found = found
        self.expected = expected
        super().__init__(
            f"Schema version mismatch: found {found}, expected {expected}"
        )


# ============================================================
# SQLite Checkpoint Store
# ============================================================


class SQLiteCheckpointStore:
    """SQLite Checkpoint 持久化.

    线程安全策略:
        - ":memory:" 模式: 单 connection + threading.Lock
          (SQLite 内存数据库跨 connection 不共享, 必须序列化访问)
        - file 模式: 每操作创建独立 connection
          (SQLite 文件锁自动处理, 跨 connection/线程安全)

    事务: save/delete/clear 在一个事务内完成 (BEGIN → INSERT/DELETE → COMMIT).
    失败自动 ROLLBACK, 调用方捕获异常.

    Schema:
        CREATE TABLE checkpoints (
            id TEXT PRIMARY KEY,
            round INTEGER NOT NULL,
            step INTEGER NOT NULL,
            state_json TEXT NOT NULL,
            history_json TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            parent_id TEXT,
            tag TEXT,
            created_at TEXT NOT NULL
        )
    """

    def __init__(self, db_path: str | Path) -> None:
        """初始化.

        Args:
            db_path: SQLite 数据库文件路径. ":memory:" 用于测试
        """
        self.db_path = str(db_path)
        self._is_memory = self.db_path == ":memory:"
        self._lock = threading.Lock()
        self._shared_conn: sqlite3.Connection | None = None
        self._init_schema()

    def _init_schema(self) -> None:
        """初始化 schema (幂等, 跨进程/线程安全)."""
        with self._lock:
            if self._is_memory:
                # ":memory:" 模式: 单一共享 connection
                self._shared_conn = sqlite3.connect(":memory:")
                self._shared_conn.row_factory = sqlite3.Row
                self._ensure_schema(self._shared_conn)
            else:
                # file 模式: 临时 connection 用于初始化
                conn = sqlite3.connect(self.db_path)
                try:
                    self._ensure_schema(conn)
                finally:
                    conn.close()

    def _connect(self) -> sqlite3.Connection:
        """获取一个可用的 connection (返回的 connection 由调用方关闭).

        - ":memory:" 模式: 返回共享 connection (不关闭)
        - file 模式: 返回新 connection (调用方关闭)

        Returns:
            sqlite3.Connection (调用方负责关闭, 除 ":memory:" 模式外)
        """
        if self._is_memory and self._shared_conn is not None:
            return self._shared_conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # file 模式: 各 connection 启动时确保 schema 存在
        self._ensure_schema(conn)
        return conn

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        """在指定 connection 上创建 schema (幂等)."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checkpoints (
                id TEXT PRIMARY KEY,
                round INTEGER NOT NULL,
                step INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                history_json TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                parent_id TEXT,
                tag TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_checkpoints_round
            ON checkpoints(round)
            """
        )
        conn.commit()

    # ============================================================
    # 序列化辅助
    # ============================================================

    @staticmethod
    def _serialize_state(state: Any) -> str:
        """序列化 LoopState → JSON string.

        支持 Pydantic model (优先) 和 dataclass/dict.
        """
        if hasattr(state, "model_dump"):
            # Pydantic v2
            return json.dumps(state.model_dump(mode="json"))
        if hasattr(state, "dict"):
            # Pydantic v1
            return json.dumps(state.dict())
        if isinstance(state, dict):
            return json.dumps(state)
        # Fallback: 假设可 JSON 序列化
        return json.dumps(state, default=str)

    @staticmethod
    def _deserialize_state(state_json: str) -> dict[str, Any]:
        """反序列化 JSON → dict (供 LoopState 重建)."""
        return json.loads(state_json)

    # ============================================================
    # Save / Load / List / Delete
    # ============================================================

    def save(
        self,
        state: Any,
        round: int,
        step: int = 0,
        history: list[Any] | None = None,
        checkpoint_id: str | None = None,
        parent_id: str | None = None,
        tag: str | None = None,
    ) -> str:
        """保存 Checkpoint.

        Args:
            state: LoopState (或 dict/任何可 JSON 序列化的对象)
            round: 当前轮次
            step: 当前 step (L1 Inner Loop 内 iteration 计数)
            history: RoundHistory 列表 (可为空)
            checkpoint_id: 显式指定 ID, None = 自动生成 UUID
            parent_id: 父 Checkpoint ID (用于版本链)
            tag: 可选标签 (如 "before-refactor")

        Returns:
            checkpoint_id (str)

        Raises:
            TypeError: state 无法 JSON 序列化
            sqlite3.IntegrityError: checkpoint_id 重复
        """
        cp_id = checkpoint_id or str(uuid.uuid4())
        state_json = self._serialize_state(state)

        # history 序列化: 支持 RoundHistory dataclass 或 dict
        history_dicts: list[dict[str, Any]] = []
        for h in history or []:
            if hasattr(h, "__dict__"):
                history_dicts.append(dict(h.__dict__))
            elif isinstance(h, dict):
                history_dicts.append(h)
            else:
                history_dicts.append({"value": str(h)})

        history_json = json.dumps(history_dicts, default=str)
        now = datetime.now(UTC).isoformat()

        # ":memory:" 模式需要 lock, file 模式 SQLite 自己处理锁
        if self._is_memory:
            with self._lock:
                assert self._shared_conn is not None
                conn = self._shared_conn
                try:
                    conn.execute("BEGIN")
                    conn.execute(
                        """
                        INSERT INTO checkpoints
                        (id, round, step, state_json, history_json,
                         schema_version, parent_id, tag, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            cp_id,
                            round,
                            step,
                            state_json,
                            history_json,
                            SCHEMA_VERSION,
                            parent_id,
                            tag,
                            now,
                        ),
                    )
                    conn.commit()
                except sqlite3.Error:
                    conn.rollback()
                    raise
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute(
                    """
                    INSERT INTO checkpoints
                    (id, round, step, state_json, history_json,
                     schema_version, parent_id, tag, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cp_id,
                        round,
                        step,
                        state_json,
                        history_json,
                        SCHEMA_VERSION,
                        parent_id,
                        tag,
                        now,
                    ),
                )
                conn.commit()
            except sqlite3.Error:
                conn.rollback()
                raise
            finally:
                conn.close()

        return cp_id

    def load(self, checkpoint_id: str) -> Checkpoint:
        """按 ID 加载 Checkpoint.

        Args:
            checkpoint_id: Checkpoint ID

        Returns:
            完整 Checkpoint

        Raises:
            CheckpointNotFoundError: ID 不存在
            CheckpointSchemaMismatchError: schema_version 不匹配
        """
        if self._is_memory:
            with self._lock:
                return self._load_from_conn(self._shared_conn, checkpoint_id)
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                return self._load_from_conn(conn, checkpoint_id)
            finally:
                conn.close()

    def load_latest(self) -> Checkpoint | None:
        """加载最新 Checkpoint (按 round DESC, created_at DESC).

        Returns:
            最新 Checkpoint 或 None (库为空)
        """
        if self._is_memory:
            with self._lock:
                assert self._shared_conn is not None
                row = self._shared_conn.execute(
                    """
                    SELECT * FROM checkpoints
                    ORDER BY round DESC, created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
                return self._row_to_checkpoint(row) if row else None
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    """
                    SELECT * FROM checkpoints
                    ORDER BY round DESC, created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
                return self._row_to_checkpoint(row) if row else None
            finally:
                conn.close()

    def load_by_round(self, round: int) -> Checkpoint | None:
        """加载指定轮次的 Checkpoint (返回该轮最近一条).

        Args:
            round: 轮次编号

        Returns:
            Checkpoint 或 None
        """
        if self._is_memory:
            with self._lock:
                assert self._shared_conn is not None
                row = self._shared_conn.execute(
                    """
                    SELECT * FROM checkpoints
                    WHERE round = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (round,),
                ).fetchone()
                return self._row_to_checkpoint(row) if row else None
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    """
                    SELECT * FROM checkpoints
                    WHERE round = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (round,),
                ).fetchone()
                return self._row_to_checkpoint(row) if row else None
            finally:
                conn.close()

    def list_all(self) -> list[CheckpointMeta]:
        """列出所有 Checkpoint (按 round ASC, created_at ASC).

        Returns:
            元数据列表 (轻量, 不含 state/history)
        """
        if self._is_memory:
            with self._lock:
                assert self._shared_conn is not None
                rows = self._shared_conn.execute(
                    """
                    SELECT id, round, step, created_at, schema_version,
                           parent_id, tag
                    FROM checkpoints
                    ORDER BY round ASC, created_at ASC
                    """
                ).fetchall()
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    """
                    SELECT id, round, step, created_at, schema_version,
                           parent_id, tag
                    FROM checkpoints
                    ORDER BY round ASC, created_at ASC
                    """
                ).fetchall()
            finally:
                conn.close()

        return [
            CheckpointMeta(
                id=row["id"],
                round=row["round"],
                step=row["step"],
                created_at=datetime.fromisoformat(row["created_at"]),
                schema_version=row["schema_version"],
                parent_id=row["parent_id"],
                tag=row["tag"],
            )
            for row in rows
        ]

    def delete(self, checkpoint_id: str) -> bool:
        """删除指定 Checkpoint.

        Args:
            checkpoint_id: Checkpoint ID

        Returns:
            True = 已删除, False = 不存在
        """
        if self._is_memory:
            with self._lock:
                assert self._shared_conn is not None
                conn = self._shared_conn
                try:
                    conn.execute("BEGIN")
                    cursor = conn.execute(
                        "DELETE FROM checkpoints WHERE id = ?", (checkpoint_id,)
                    )
                    conn.commit()
                    return cursor.rowcount > 0
                except sqlite3.Error:
                    conn.rollback()
                    raise
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute(
                    "DELETE FROM checkpoints WHERE id = ?", (checkpoint_id,)
                )
                conn.commit()
                return cursor.rowcount > 0
            except sqlite3.Error:
                conn.rollback()
                raise
            finally:
                conn.close()

    def clear(self) -> None:
        """清空所有 Checkpoint (主要用于测试).

        谨慎使用: 不可恢复.
        """
        if self._is_memory:
            with self._lock:
                assert self._shared_conn is not None
                conn = self._shared_conn
                try:
                    conn.execute("BEGIN")
                    conn.execute("DELETE FROM checkpoints")
                    conn.commit()
                except sqlite3.Error:
                    conn.rollback()
                    raise
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("DELETE FROM checkpoints")
                conn.commit()
            except sqlite3.Error:
                conn.rollback()
                raise
            finally:
                conn.close()

    def count(self) -> int:
        """返回 Checkpoint 总数."""
        if self._is_memory:
            with self._lock:
                assert self._shared_conn is not None
                row = self._shared_conn.execute(
                    "SELECT COUNT(*) as cnt FROM checkpoints"
                ).fetchone()
                return row["cnt"]
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM checkpoints"
                ).fetchone()
                return row["cnt"]
            finally:
                conn.close()

    # ============================================================
    # 内部辅助
    # ============================================================

    @staticmethod
    def _load_from_conn(conn: sqlite3.Connection, checkpoint_id: str) -> Checkpoint:
        """从指定 connection 按 ID 加载 (内部辅助)."""
        row = conn.execute(
            "SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,)
        ).fetchone()
        if row is None:
            raise CheckpointNotFoundError(f"Checkpoint '{checkpoint_id}' not found")
        return SQLiteCheckpointStore._row_to_checkpoint(row)  # type: ignore[return-value]

    @staticmethod
    def _row_to_checkpoint(row: Any) -> Checkpoint:
        """将 sqlite Row 转 Checkpoint (校验 schema_version)."""
        schema_version = row["schema_version"]
        if schema_version != SCHEMA_VERSION:
            raise CheckpointSchemaMismatchError(
                found=schema_version, expected=SCHEMA_VERSION
            )
        state = json.loads(row["state_json"])
        history = json.loads(row["history_json"])
        created_at = datetime.fromisoformat(row["created_at"])
        return Checkpoint(
            id=row["id"],
            round=row["round"],
            step=row["step"],
            state=state,
            history=history,
            created_at=created_at,
            schema_version=schema_version,
            parent_id=row["parent_id"],
            tag=row["tag"],
        )
