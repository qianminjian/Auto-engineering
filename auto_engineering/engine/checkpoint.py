"""Checkpoint — SQLite 持久化.

参考 LangGraph `checkpoint-sqlite/__init__.py:85-120` (SqliteSaver).
关键设计:
    - 每个 thread 一个 .db 文件 (WAL 模式支持并发读)
    - checkpoints 表存状态快照;writes 表存 channel 级写入日志
    - P0 修复: state_json 用 LoopState.to_dict() 序列化(dataclass asdict)
    - 状态隔离: thread_id 是 dev-loop 运行实例的唯一标识

v3.1 B 类修复 (Plan A Phase 2):
    B3 (P2): CheckpointStore 实现 __enter__/__exit__ context manager.
        Why: 允许 `with CheckpointStore(path) as store:` 自动 close,
        避免 sqlite3 fd 泄漏(ResourceWarning).
"""

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from auto_engineering.engine.state import LoopState
from auto_engineering.errors import AEError, ErrorCode

CREATE_CHECKPOINTS_TABLE = """
CREATE TABLE IF NOT EXISTS checkpoints (
    id              TEXT PRIMARY KEY,
    parent_id       TEXT,
    thread_id       TEXT NOT NULL,
    step            INTEGER NOT NULL DEFAULT 0,
    state_json      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (parent_id) REFERENCES checkpoints(id)
);
"""

CREATE_WRITES_TABLE = """
CREATE TABLE IF NOT EXISTS writes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    checkpoint_id   TEXT NOT NULL,
    task_id         TEXT NOT NULL,
    channel         TEXT NOT NULL,
    value_json      TEXT NOT NULL,
    FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(id)
);
"""


class CheckpointStore:
    """SQLite 连接管理 + CRUD. WAL 模式支持并发读、单写者."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        """懒初始化连接. 首次调用建表."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
            self._conn.execute(CREATE_CHECKPOINTS_TABLE)
            self._conn.execute(CREATE_WRITES_TABLE)
        return self._conn

    def save_checkpoint(self, cp: "Checkpoint") -> None:
        """插入或替换 checkpoint 行. 独立事务 commit."""
        conn = self._get_conn()
        state_json = json.dumps(cp.state.to_dict(), ensure_ascii=False)
        try:
            conn.execute(
                """INSERT OR REPLACE INTO checkpoints
                   (id, parent_id, thread_id, step, state_json, status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
                (cp.id, cp.parent_id, cp.thread_id, cp.step, state_json, cp.status),
            )
            conn.commit()
        except sqlite3.Error as e:
            raise AEError(
                ErrorCode.CHECKPOINT_SAVE_FAILED,
                f"Failed to save checkpoint {cp.id}: {e}",
                original_error=e,
            ) from e

    def load_checkpoint(self, checkpoint_id: str) -> "Checkpoint":
        """按 id 加载 checkpoint. 不存在抛 CHECKPOINT_LOAD_FAILED."""
        conn = self._get_conn()
        row = conn.execute(
            """SELECT id, parent_id, thread_id, step, state_json, status
               FROM checkpoints WHERE id = ?""",
            (checkpoint_id,),
        ).fetchone()
        if row is None:
            raise AEError(
                ErrorCode.CHECKPOINT_LOAD_FAILED,
                f"Checkpoint not found: {checkpoint_id}",
            )
        return Checkpoint(
            id=row[0],
            parent_id=row[1],
            thread_id=row[2],
            step=row[3],
            state=LoopState.from_dict(json.loads(row[4])),
            status=row[5],
        )

    def save_writes(self, checkpoint_id: str, task_id: str, writes: dict) -> None:
        """记录 channel 级写入日志(append-only). 独立事务 commit."""
        conn = self._get_conn()
        try:
            for channel, value in writes.items():
                conn.execute(
                    """INSERT INTO writes
                       (checkpoint_id, task_id, channel, value_json)
                       VALUES (?, ?, ?, ?)""",
                    (checkpoint_id, task_id, channel, json.dumps(value, ensure_ascii=False)),
                )
            conn.commit()
        except sqlite3.Error as e:
            raise AEError(
                ErrorCode.CHECKPOINT_SAVE_FAILED,
                f"Failed to save writes for {checkpoint_id}: {e}",
                original_error=e,
            ) from e

    def close(self) -> None:
        """关闭连接. 显式调用,避免 fd 泄漏."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "CheckpointStore":
        """v3.1 B3: Context manager 入口. 允许 `with CheckpointStore(path) as store:`."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """v3.1 B3: Context manager 出口. 自动 close,避免 sqlite3 fd 泄漏."""
        self.close()

    def list_all(self) -> list[dict]:
        """列出所有 checkpoints. 返回 [{id, thread_id, step, status, created_at, updated_at}, ...]."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT id, thread_id, step, status, created_at, updated_at
               FROM checkpoints
               ORDER BY updated_at DESC"""
        ).fetchall()
        return [
            {
                "id": r[0],
                "thread_id": r[1],
                "step": r[2],
                "status": r[3],
                "created_at": r[4],
                "updated_at": r[5],
            }
            for r in rows
        ]

    def get_latest_for_thread(self, thread_id: str) -> "Checkpoint | None":
        """按 thread_id 取最新 Checkpoint. 不存在返回 None."""
        conn = self._get_conn()
        row = conn.execute(
            """SELECT id, parent_id, thread_id, step, state_json, status
               FROM checkpoints
               WHERE thread_id = ?
               ORDER BY step DESC LIMIT 1""",
            (thread_id,),
        ).fetchone()
        if row is None:
            return None
        return Checkpoint(
            id=row[0],
            parent_id=row[1],
            thread_id=row[2],
            step=row[3],
            state=LoopState.from_dict(json.loads(row[4])),
            status=row[5],
        )


@dataclass
class Checkpoint:
    """单次状态快照. 不可变 ID,可变 step/status/state."""

    id: str
    parent_id: str | None
    thread_id: str
    step: int
    state: "LoopState"
    status: str = "pending"

    @classmethod
    def create(
        cls,
        thread_id: str,
        state: "LoopState",
        parent_id: str | None = None,
    ) -> "Checkpoint":
        """新建 checkpoint. UUID 生成 ID, step=0."""
        return cls(
            id=str(uuid.uuid4()),
            parent_id=parent_id,
            thread_id=thread_id,
            step=0,
            state=state,
            status="pending",
        )

    def increment_step(self) -> None:
        """step 自增. 由 LoopEngine.after_tick() 调用."""
        self.step += 1

    def apply_writes(self, writes: dict) -> None:
        """将 Stage 输出写入 state channels. 委托给 LoopState.set_channels."""
        self.state.set_channels(writes)
