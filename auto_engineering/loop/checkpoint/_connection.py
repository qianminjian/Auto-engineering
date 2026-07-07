"""SQLite 连接管理 — _with_conn 上下文管理器.

从 loop/checkpoint/store.py 拆分 (v2.5 P1-D: store.py 609 行 → store.py + _connection.py + _serialization.py).
将 ":memory:" / file 模式的连接获取/释放/锁/行工厂 集中管理, store.py 中的公开方法
(save/load/load_latest/load_by_round/list_all/delete/clear/count) 不再各自重复这层样板.
v2.5 P1-D+1: 加 _atomic 上下文管理器 — 事务包装 + 失败自动 rollback, 让 save/delete/clear
的 try/except 模板不再重复.
v2.5 P2-D-3: file 模式连接缓存 + WAL — 每操作 connect/close + 无 WAL 模式, 慢.
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
    file_conn: sqlite3.Connection | None = None,
) -> Iterator[sqlite3.Connection]:
    """获取一个 sqlite3.Connection, 用完自动关闭 (除 ":memory:" 模式外).

    线程安全策略:
        - ":memory:" 模式: 取 lock, 返回共享 connection, 不关闭
        - file 模式: 复用 file_conn (缓存) — v2.5 P2-D-3 性能优化;
          如果调用方传 None (老调用方) 仍走一次性 connect/close 路径

    Schema 幂等创建: 每次获取 file 模式 connection 时都执行 CREATE TABLE IF NOT EXISTS,
    跨进程/线程安全.

    v2.5 P2-C-4 同步不变量: 本 context manager 是**完全同步**的 — `with`
    块内不要 `await` 任何东西. threading.Lock 在 sync 上下文获取/释放,
    安全 (asyncio 单线程事件循环不会释放到另一线程). 如果未来有
    refactor 在 `with` 块内 await — 必须先换 `asyncio.Lock` 或拆锁,
    否则事件循环永久 deadlock. 标志: yield 之后无 await.

    Yields:
        sqlite3.Connection (row_factory=sqlite3.Row).
    """
    if is_memory:
        assert shared_conn is not None, "memory store 必须在初始化后才能 _with_conn"
        with lock:
            yield shared_conn
        return
    if file_conn is not None:
        # v2.5 P2-D-3: 复用缓存的 file connection (WAL 模式 + skip schema 重复创建)
        with lock:
            yield file_conn
        return
    # 一次性连接 (无缓存, 老调用方或测试)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def _atomic(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """事务包装: 正常退出时 commit, sqlite3.Error 时 rollback 后重新抛出.

    用法: `with self._conn() as conn, _atomic(conn): conn.execute(...); ...`

    SQLite 也会在 connection close 时自动 rollback 未提交事务, 但显式
    rollback-on-error 给出清晰的失败契约 (P1-D 之前版本有显式 try/except rollback,
    P1-D 拆分时丢失, v2.5 P1-D+1 恢复).

    v2.5 P2-C-4 同步不变量: 与 _with_conn 同样**完全同步** —
    `with` 块内不要 `await`. commit/rollback 都是 SQLite sync 调用,
    在 thread pool (asyncio.to_thread) 上下文里也安全. 如果未来要
    在 `_atomic` 内 await, 必须先确认 conn 操作本身是 async (不是),
    或重构为 AsyncConnection (Python 3.12+ sqlite3 async API).
    """
    try:
        yield conn
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise


def init_file_conn(db_path: str, lock: threading.Lock) -> sqlite3.Connection:
    """初始化 file 模式缓存连接 (v2.5 P2-D-3).

    - 设 PRAGMA journal_mode=WAL — 写并发不互斥读
    - check_same_thread=False + threading.Lock 保护 — 多线程共享同一连接安全
    - 幂等创建 schema
    - 返回连接供 _with_conn 复用 (不关闭)

    调用方负责在 store 生命周期结束时 close().
    """
    with lock:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # WAL: 写并发不阻塞读, 提升 dev-loop 期间的多 round 吞吐
        # (round 1 写 checkpoint 时 round 2 还能读)
        conn.execute("PRAGMA journal_mode=WAL")
        _ensure_schema(conn)
    return conn


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


__all__ = ["init_file_conn"]  # _with_conn / _atomic 为包内私有, 不公开导出
