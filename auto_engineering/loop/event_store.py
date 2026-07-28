"""SQLite append-only LoopEvent 存储。"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.projector import EngineStateProjector


class SQLiteEventStore:
    """按 thread_id 分流、按 sequence 严格连续的事件存储。"""

    def __init__(
        self,
        db_path: str | Path,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self._closed = False
        self._fault_injector = fault_injector
        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        if self.db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("EventStore 已关闭")

    def _ensure_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS loop_events (
                event_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                sequence INTEGER NOT NULL CHECK (sequence >= 0),
                event_type TEXT NOT NULL,
                causation_id TEXT,
                correlation_id TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(thread_id, sequence)
            );
            CREATE INDEX IF NOT EXISTS idx_loop_events_stream
            ON loop_events(thread_id, sequence);
            CREATE TABLE IF NOT EXISTS engine_state_projections (
                thread_id TEXT PRIMARY KEY,
                sequence INTEGER NOT NULL CHECK (sequence >= 0),
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS action_snapshots (
                thread_id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL UNIQUE,
                sequence INTEGER NOT NULL CHECK (sequence >= 0),
                action_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS checkpoint_imports (
                checkpoint_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL UNIQUE,
                event_id TEXT NOT NULL UNIQUE,
                imported_at TEXT NOT NULL
            );
            """
        )

    def append(self, events: Iterable[LoopEvent]) -> None:
        """原子追加一批连续事件；任意失败不会留下部分写入。"""

        batch = list(events)
        if not batch:
            return
        thread_id = batch[0].thread_id
        if any(event.thread_id != thread_id for event in batch):
            raise ValueError("单次 append 只能写入一个 thread")
        self._validate_batch(batch)

        with self._lock:
            self._ensure_open()
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._append_in_transaction(batch)
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    def _append_in_transaction(self, batch: list[LoopEvent]) -> None:
        thread_id = batch[0].thread_id
        row = self._conn.execute(
            "SELECT COALESCE(MAX(sequence) + 1, 0) AS next_sequence "
            "FROM loop_events WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        expected = int(row["next_sequence"])
        actual = [event.sequence for event in batch]
        wanted = list(range(expected, expected + len(batch)))
        if actual != wanted:
            raise ValueError(
                f"事件 sequence 必须严格连续；期望 {wanted}，实际 {actual}"
            )
        self._conn.executemany(
            """
            INSERT INTO loop_events (
                event_id, thread_id, sequence, event_type, causation_id,
                correlation_id, schema_version, payload_json,
                payload_sha256, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    event.event_id,
                    event.thread_id,
                    event.sequence,
                    event.event_type.value,
                    event.causation_id,
                    event.correlation_id,
                    event.schema_version,
                    json.dumps(
                        event.to_dict()["payload"],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    event.payload_sha256,
                    event.created_at,
                )
                for event in batch
            ],
        )

    @staticmethod
    def _validate_batch(batch: list[LoopEvent]) -> None:
        for event in batch:
            if (
                event.event_type is LoopEventType.RESULT_ACCEPTED
                and event.causation_id is None
            ):
                raise ValueError("ResultAccepted 必须包含 causation_id")

    def commit_tick(
        self,
        *,
        events: Iterable[LoopEvent],
        state: EngineState,
        action: Mapping[str, Any],
    ) -> None:
        """在一个事务内提交事实、状态投影和宿主 Action 快照。"""

        batch = list(events)
        if not batch:
            raise ValueError("单 Tick 至少包含一个事件")
        thread_id = batch[0].thread_id
        if state.thread_id != thread_id or action.get("thread_id") != thread_id:
            raise ValueError("事件、投影与 Action 的 thread_id 必须一致")
        message_id = action.get("message_id")
        if not isinstance(message_id, str) or not message_id:
            raise ValueError("Action 缺少有效 message_id")
        if any(event.thread_id != thread_id for event in batch):
            raise ValueError("单 Tick 事件必须属于同一 thread_id")
        self._validate_batch(batch)

        with self._lock:
            self._ensure_open()
            existing = self._load_stream_unlocked(thread_id)
            replayed = EngineStateProjector().replay([*existing, *batch])
            if replayed.to_dict() != state.to_dict():
                raise ValueError("待提交 EngineState 与事件重放投影不一致")
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._append_in_transaction(batch)
                self._inject_fault("after_events")
                last = batch[-1]
                state_json = json.dumps(
                    state.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
                self._conn.execute(
                    """
                    INSERT INTO engine_state_projections
                        (thread_id, sequence, state_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(thread_id) DO UPDATE SET
                        sequence = excluded.sequence,
                        state_json = excluded.state_json,
                        updated_at = excluded.updated_at
                    """,
                    (thread_id, last.sequence, state_json, last.created_at),
                )
                self._inject_fault("after_projection")
                action_json = json.dumps(
                    dict(action),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
                self._conn.execute(
                    """
                    INSERT INTO action_snapshots
                        (thread_id, message_id, sequence, action_json, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(thread_id) DO UPDATE SET
                        message_id = excluded.message_id,
                        sequence = excluded.sequence,
                        action_json = excluded.action_json,
                        updated_at = excluded.updated_at
                    """,
                    (thread_id, message_id, last.sequence, action_json, last.created_at),
                )
                self._inject_fault("after_action")
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    def _inject_fault(self, point: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(point)

    def append_new(
        self,
        *,
        thread_id: str,
        event_type: LoopEventType | str,
        payload: Mapping[str, Any],
        correlation_id: str,
        causation_id: str | None = None,
    ) -> LoopEvent:
        """在同一临界区分配下一序列并追加一个事件。"""

        with self._lock:
            sequence = self.next_sequence(thread_id)
            event = LoopEvent.create(
                thread_id=thread_id,
                sequence=sequence,
                event_type=event_type,
                payload=payload,
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
            self.append([event])
            return event

    def next_sequence(self, thread_id: str) -> int:
        with self._lock:
            self._ensure_open()
            row = self._conn.execute(
                "SELECT COALESCE(MAX(sequence) + 1, 0) AS next_sequence "
                "FROM loop_events WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            return int(row["next_sequence"])

    def load_stream(self, thread_id: str) -> list[LoopEvent]:
        with self._lock:
            self._ensure_open()
            return self._load_stream_unlocked(thread_id)

    def _load_stream_unlocked(self, thread_id: str) -> list[LoopEvent]:
        rows = self._conn.execute(
            "SELECT * FROM loop_events WHERE thread_id = ? ORDER BY sequence",
            (thread_id,),
        ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def load_projection(self, thread_id: str) -> EngineState | None:
        with self._lock:
            self._ensure_open()
            row = self._conn.execute(
                "SELECT state_json FROM engine_state_projections WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        if row is None:
            return None
        return EngineState.from_dict(json.loads(row["state_json"]))

    def rebuild_projection(self, thread_id: str) -> EngineState:
        """删除或损坏投影后，以事件日志为唯一事实源重建。"""

        with self._lock:
            self._ensure_open()
            stream = self._load_stream_unlocked(thread_id)
            state = EngineStateProjector().replay(stream)
            last = stream[-1]
            state_json = json.dumps(
                state.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    """
                    INSERT INTO engine_state_projections
                        (thread_id, sequence, state_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(thread_id) DO UPDATE SET
                        sequence = excluded.sequence,
                        state_json = excluded.state_json,
                        updated_at = excluded.updated_at
                    """,
                    (thread_id, last.sequence, state_json, last.created_at),
                )
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
            return state

    def load_action_snapshot(self, thread_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._ensure_open()
            row = self._conn.execute(
                "SELECT action_json FROM action_snapshots WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        return json.loads(row["action_json"]) if row else None

    def import_checkpoint(
        self,
        *,
        checkpoint_id: str,
        state: EngineState,
        action: Mapping[str, Any] | None = None,
    ) -> LoopEvent:
        """将一个 v5.6 EngineState 一次性导入为事件流种子，不改写源记录。"""

        if not checkpoint_id:
            raise ValueError("checkpoint_id 不能为空")
        thread_id = state.thread_id
        if action is not None and action.get("thread_id") != thread_id:
            raise ValueError("checkpoint Action thread_id 与状态不一致")
        with self._lock:
            self._ensure_open()
            row = self._conn.execute(
                "SELECT event_id FROM checkpoint_imports WHERE checkpoint_id = ?",
                (checkpoint_id,),
            ).fetchone()
            if row is not None:
                event_row = self._conn.execute(
                    "SELECT * FROM loop_events WHERE event_id = ?",
                    (row["event_id"],),
                ).fetchone()
                if event_row is None:
                    raise RuntimeError("checkpoint 导入标记缺少对应事件")
                return self._row_to_event(event_row)
            if self.next_sequence(thread_id) != 0:
                raise ValueError("已有事件流不能再次导入 checkpoint")

            imported_at = datetime.now(UTC).isoformat()
            event = LoopEvent.create(
                thread_id=thread_id,
                sequence=0,
                event_type=LoopEventType.CHECKPOINT_IMPORTED,
                payload={"checkpoint_id": checkpoint_id, "state": state.to_dict()},
                correlation_id=thread_id,
                created_at=imported_at,
            )
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._append_in_transaction([event])
                state_json = json.dumps(
                    state.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
                self._conn.execute(
                    """
                    INSERT INTO engine_state_projections
                        (thread_id, sequence, state_json, updated_at)
                    VALUES (?, 0, ?, ?)
                    """,
                    (thread_id, state_json, imported_at),
                )
                if action is not None:
                    message_id = action.get("message_id")
                    if not isinstance(message_id, str) or not message_id:
                        raise ValueError("checkpoint Action 缺少 message_id")
                    self._conn.execute(
                        """
                        INSERT INTO action_snapshots
                            (thread_id, message_id, sequence, action_json, updated_at)
                        VALUES (?, ?, 0, ?, ?)
                        """,
                        (
                            thread_id,
                            message_id,
                            json.dumps(
                                dict(action),
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                                default=str,
                            ),
                            imported_at,
                        ),
                    )
                self._conn.execute(
                    """
                    INSERT INTO checkpoint_imports
                        (checkpoint_id, thread_id, event_id, imported_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (checkpoint_id, thread_id, event.event_id, imported_at),
                )
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
            return event

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> LoopEvent:
        return LoopEvent.from_dict(
            {
                "schema_version": row["schema_version"],
                "event_id": row["event_id"],
                "thread_id": row["thread_id"],
                "sequence": row["sequence"],
                "event_type": row["event_type"],
                "causation_id": row["causation_id"],
                "correlation_id": row["correlation_id"],
                "payload": json.loads(row["payload_json"]),
                "payload_sha256": row["payload_sha256"],
                "created_at": row["created_at"],
            }
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.close()

    def __enter__(self) -> SQLiteEventStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


__all__ = ["SQLiteEventStore"]
