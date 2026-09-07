"""SQLiteEventStore 的数据库结构初始化。"""

from __future__ import annotations

import sqlite3


def ensure_schema(conn: sqlite3.Connection) -> None:
    """创建 EventStore 所需表和索引；已有数据库保持向后兼容。"""

    conn.executescript(
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
        CREATE TABLE IF NOT EXISTS protocol_result_replays (
            thread_id TEXT NOT NULL,
            causation_id TEXT NOT NULL,
            result_hash TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(thread_id, causation_id)
        );
        CREATE TABLE IF NOT EXISTS effect_receipts (
            thread_id TEXT NOT NULL,
            action_message_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
            created_at TEXT NOT NULL,
            PRIMARY KEY(thread_id, action_message_id, relative_path)
        );
        CREATE TABLE IF NOT EXISTS checkpoint_imports (
            checkpoint_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL UNIQUE,
            event_id TEXT NOT NULL UNIQUE,
            imported_at TEXT NOT NULL
        );
        """
    )


__all__ = ["ensure_schema"]
