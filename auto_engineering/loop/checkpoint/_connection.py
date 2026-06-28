"""SQLite 连接管理 — _with_conn 上下文管理器.

从 loop/checkpoint/store.py 拆分 (v2.5 P1-D: store.py 609 行 → store.py + _connection.py + _serialization.py).
将 ":memory:" / file 模式的连接获取/释放/锁/行工厂 集中管理, store.py 中的公开方法
(save/load/load_latest/load_by_round/list_all/delete/clear/count) 不再各自重复这层样板.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def _with_conn(
    db_path: str,
    *,
    is_memory: bool,
    lock: threading.Lock,
    shared_conn: sqlite3.Connection | None,
) -> Iterator[sqlite3.Connection]:
    """获取一个 sqlite3.Connection, 用完自动关闭 (除 ":memory:" 模式外).

    线程安全策略:
        - ":memory:" 模式: 取 lock, 返回共享 connection, 不关闭
        - file 模式: 每调用创建独立 connection, 调用方 yield 后自动 close

    Schema 幂等创建: 每次获取 file 模式 connection 时都执行 CREATE TABLE IF NOT EXISTS,
    跨进程/线程安全.

    Yields:
        sqlite3.Connection (row_factory=sqlite3.Row).
    """
    if is_memory:
        assert shared_conn is not None, "memory store 必须在初始化后才能 _with_conn"
        with lock:
            yield shared_conn
        return
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    try:
        yield conn
    finally:
        conn.close()


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


__all__ = ["_with_conn", "_ensure_schema"]
