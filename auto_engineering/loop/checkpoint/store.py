"""SQLite Checkpoint 持久化 Store.

从 loop/checkpoint.py 拆分 (P1-E: checkpoint → checkpoint/ 子模块).
v2.5 P1-D 二次拆分: store.py 609 行 → store.py + _connection.py + _serialization.py.
- _connection.py: SQLite 连接管理 (":memory:" vs file 模式, lock, row_factory, schema 幂等)
- _serialization.py: 状态 JSON 互转 + 嵌套 dataclass 归一化
- 本文件: SQLiteCheckpointStore 业务方法 (save/load/list/delete/clear/count)
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from auto_engineering.loop.checkpoint._connection import _atomic, _with_conn, init_file_conn
from auto_engineering.loop.checkpoint._serialization import (
    deserialize_state,
    normalize_history_item,
    serialize_state,
)
from auto_engineering.loop.checkpoint.records import (
    Checkpoint,
    CheckpointMeta,
    CheckpointNotFoundError,
    CheckpointSchemaMismatchError,
    T,
)

# Schema 版本号 (变更时 +1, 用于未来兼容)
SCHEMA_VERSION = 1


class SQLiteCheckpointStore[T]:
    """SQLite Checkpoint 持久化.

    使用: SQLiteCheckpointStore[EngineState](db_path) — 类型安全.
    (v5.0: EngineState 替代 CheckpointEnvelope → LoopState 历史路径.)

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
        # v2.5 P2-D-3: file 模式缓存连接 + WAL, 避免每操作 connect/close
        self._file_conn: sqlite3.Connection | None = None
        if self._is_memory:
            # memory 模式: 启动时建共享 connection + schema
            with self._lock:
                self._shared_conn = sqlite3.connect(":memory:")
                self._shared_conn.row_factory = sqlite3.Row
                self._shared_conn.execute(
                    """CREATE TABLE IF NOT EXISTS checkpoints (
                        id TEXT PRIMARY KEY,
                        round INTEGER NOT NULL,
                        step INTEGER NOT NULL,
                        state_json TEXT NOT NULL,
                        history_json TEXT NOT NULL,
                        schema_version INTEGER NOT NULL,
                        parent_id TEXT,
                        tag TEXT,
                        created_at TEXT NOT NULL
                    )"""
                )
                self._shared_conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_checkpoints_round "
                    "ON checkpoints(round)"
                )
                self._shared_conn.commit()
        else:
            # v2.5 P2-D-3: file 模式初始化缓存连接 (WAL + schema 一次)
            self._file_conn = init_file_conn(self.db_path, self._lock)

    def _conn(self) -> Any:
        """获取连接的上下文管理器 (内部辅助, 让 save/load 等方法少 4 行样板).

        v2.5 P2-D-3: file 模式传 self._file_conn (缓存), memory 模式传
        self._shared_conn. _with_conn 复用, 不再 connect/close.
        """
        return _with_conn(
            self.db_path,
            is_memory=self._is_memory,
            lock=self._lock,
            shared_conn=self._shared_conn,
            file_conn=self._file_conn,
        )

    def close(self) -> None:
        """v2.5 P2-D-3: 关闭缓存的 file connection.

        长进程 (e.g. dev-loop 跑几十轮) 应该在结束时调 close() 释放
        SQLite 句柄 + 关闭 WAL 文件. 否则 GC 回收.
        """
        if self._file_conn is not None:
            self._file_conn.close()
            self._file_conn = None
        if self._shared_conn is not None:
            self._shared_conn.close()
            self._shared_conn = None

    def __enter__(self) -> "SQLiteCheckpointStore[T]":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    @staticmethod
    def _validate_state_serializable(state: object) -> None:
        """运行时验证 state 可被 serialize_state 处理 (v5.4 P2-2).

        TypeVar T bound=LoopStateProtocol 仅 mypy 层约束, 运行时无强制.
        此方法在 save 入口做 duck-type 检查: 必须是 dataclass / dict /
        或具有 model_dump 方法的对象.

        Raises:
            TypeError: state 类型无法序列化.
        """
        from dataclasses import is_dataclass

        if is_dataclass(state) and not isinstance(state, type):
            return
        if isinstance(state, dict):
            return
        if hasattr(state, "model_dump") and callable(state.model_dump):
            return
        if hasattr(state, "dict") and callable(state.dict):
            return
        raise TypeError(
            f"Cannot serialize state of type {type(state).__name__}: "
            f"must be a dataclass, dict, or have model_dump/dict method. "
            f"state={state!r}"
        )

    def save(
        self,
        state: T,
        round: int,
        step: int = 0,
        history: list[Any] | None = None,
        checkpoint_id: str | None = None,
        parent_id: str | None = None,
        tag: str | None = None,
    ) -> str:
        """保存 Checkpoint.

        Args:
            state: 满足 LoopStateProtocol 的对象 (典型: EngineState 实例)
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
        self._validate_state_serializable(state)
        cp_id = checkpoint_id or str(uuid.uuid4())
        state_json = serialize_state(state)
        history_dicts: list[dict[str, Any]] = []
        for h in history or []:
            if hasattr(h, "__dict__"):
                history_dicts.append(normalize_history_item(dict(h.__dict__)))
            elif isinstance(h, dict):
                history_dicts.append(normalize_history_item(h))
            else:
                history_dicts.append({"value": str(h)})
        history_json = json.dumps(history_dicts, default=str)
        now = datetime.now(UTC).isoformat()

        with self._conn() as conn, _atomic(conn):
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
        return cp_id

    def load(self, checkpoint_id: str) -> Checkpoint[T]:
        """按 ID 加载 Checkpoint.

        Raises:
            CheckpointNotFoundError: ID 不存在
            CheckpointSchemaMismatchError: schema_version 不匹配
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,)
            ).fetchone()
            if row is None:
                raise CheckpointNotFoundError(
                    f"Checkpoint '{checkpoint_id}' not found"
                )
            return _row_to_checkpoint(row)

    def load_latest(self) -> Checkpoint[T] | None:
        """加载最新 Checkpoint (按 round DESC, created_at DESC)."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM checkpoints "
                "ORDER BY round DESC, created_at DESC LIMIT 1"
            ).fetchone()
            return _row_to_checkpoint(row) if row else None

    def load_by_round(self, round: int) -> Checkpoint[T] | None:
        """加载指定轮次的 Checkpoint (返回该轮最近一条)."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM checkpoints WHERE round = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (round,),
            ).fetchone()
            return _row_to_checkpoint(row) if row else None

    def list_all(self) -> list[CheckpointMeta]:
        """列出所有 Checkpoint (按 round ASC, created_at ASC).

        Returns:
            元数据列表 (轻量, 不含 state/history)
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, round, step, created_at, schema_version, "
                "parent_id, tag FROM checkpoints "
                "ORDER BY round ASC, created_at ASC"
            ).fetchall()
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

    def list_threads(self) -> list[str]:
        """列出所有唯一 thread_id (从 state_json 提取).

        Returns:
            去重排序的 thread_id 列表.

        设计: B2.10 CheckpointStore.list_threads() → JSON 提取而非 schema column,
        因为 thread_id 已是 EngineState 字段但 checkpoint schema 无独立列.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT state_json FROM checkpoints"
            ).fetchall()
        thread_ids: set[str] = set()
        for row in rows:
            try:
                state = json.loads(row["state_json"])
                tid = state.get("thread_id")
                if tid and isinstance(tid, str):
                    thread_ids.add(tid)
            except (json.JSONDecodeError, TypeError):
                continue
        return sorted(thread_ids)

    def delete(self, checkpoint_id: str) -> bool:
        """删除指定 Checkpoint.

        Returns:
            True = 已删除, False = 不存在
        """
        with self._conn() as conn, _atomic(conn):
            cursor = conn.execute(
                "DELETE FROM checkpoints WHERE id = ?", (checkpoint_id,)
            )
            return cursor.rowcount > 0

    def clear(self) -> None:
        """清空所有 Checkpoint (主要用于测试).

        谨慎使用: 不可恢复.
        """
        with self._conn() as conn, _atomic(conn):
            conn.execute("DELETE FROM checkpoints")

    def count(self) -> int:
        """返回 Checkpoint 总数."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM checkpoints"
            ).fetchone()
            return row["cnt"]


def _row_to_checkpoint(row: Any) -> Checkpoint[T]:
    """将 sqlite Row 转 Checkpoint (校验 schema_version)."""
    schema_version = row["schema_version"]
    if schema_version != SCHEMA_VERSION:
        raise CheckpointSchemaMismatchError(
            found=schema_version, expected=SCHEMA_VERSION
        )
    state = deserialize_state(row["state_json"])
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
