"""v5.8 按 thread/session/tick/stage/worker 归因的 Usage Ledger。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class UsageRecord:
    thread_id: str
    session_id: str
    tick: int
    stage: str
    worker: str
    input_units: int | None
    cache_read_units: int | None
    cache_write_units: int | None
    output_units: int | None
    provider: str
    model: str
    usage_source: str
    estimated: bool


class UsageLedger:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usage_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                tick INTEGER NOT NULL,
                stage TEXT NOT NULL,
                worker TEXT NOT NULL,
                input_units INTEGER,
                cache_read_units INTEGER,
                cache_write_units INTEGER,
                output_units INTEGER,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                usage_source TEXT NOT NULL,
                estimated INTEGER NOT NULL
            )
            """
        )
        self._conn.commit()

    def append(self, record: UsageRecord) -> None:
        if not all((
            record.thread_id,
            record.session_id,
            record.stage,
            record.worker,
            record.provider,
            record.model,
            record.usage_source,
        )):
            raise ValueError("UsageRecord 归因字段不得为空")
        self._conn.execute(
            """
            INSERT INTO usage_ledger
            (thread_id, session_id, tick, stage, worker, input_units,
             cache_read_units, cache_write_units, output_units, provider,
             model, usage_source, estimated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.thread_id,
                record.session_id,
                record.tick,
                record.stage,
                record.worker,
                record.input_units,
                record.cache_read_units,
                record.cache_write_units,
                record.output_units,
                record.provider,
                record.model,
                record.usage_source,
                int(record.estimated),
            ),
        )
        self._conn.commit()

    def list_records(self, thread_id: str) -> list[UsageRecord]:
        rows = self._conn.execute(
            "SELECT * FROM usage_ledger WHERE thread_id = ? ORDER BY id",
            (thread_id,),
        ).fetchall()
        return [
            UsageRecord(
                thread_id=row["thread_id"],
                session_id=row["session_id"],
                tick=row["tick"],
                stage=row["stage"],
                worker=row["worker"],
                input_units=row["input_units"],
                cache_read_units=row["cache_read_units"],
                cache_write_units=row["cache_write_units"],
                output_units=row["output_units"],
                provider=row["provider"],
                model=row["model"],
                usage_source=row["usage_source"],
                estimated=bool(row["estimated"]),
            )
            for row in rows
        ]

    def aggregate(self, thread_id: str) -> dict[str, int | float]:
        records = self.list_records(thread_id)

        def total(field: str) -> int:
            return sum(
                value for record in records
                if (value := getattr(record, field)) is not None
            )

        attributed = sum(
            bool(record.session_id and record.stage and record.worker)
            for record in records
        )
        unknown = sum(
            all(value is None for value in (
                record.input_units,
                record.cache_read_units,
                record.cache_write_units,
                record.output_units,
            ))
            for record in records
        )
        return {
            "input_units": total("input_units"),
            "cache_read_units": total("cache_read_units"),
            "cache_write_units": total("cache_write_units"),
            "output_units": total("output_units"),
            "records": len(records),
            "attributed_records": attributed,
            "unknown_records": unknown,
            "attribution_rate": attributed / len(records) if records else 1.0,
        }

    def close(self) -> None:
        self._conn.close()


__all__ = ["UsageLedger", "UsageRecord"]
