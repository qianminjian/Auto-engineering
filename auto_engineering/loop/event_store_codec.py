"""EventStore 的持久化编解码边界。"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from auto_engineering.loop.events import LoopEvent


def dumps(value: Any, *, default_str: bool = False) -> str:
    """使用 EventStore 统一的确定性 JSON 编码。"""

    kwargs: dict[str, Any] = {
        "ensure_ascii": False,
        "sort_keys": True,
        "separators": (",", ":"),
    }
    if default_str:
        kwargs["default"] = str
    return json.dumps(value, **kwargs)


def loads(value: str) -> Any:
    """解析 EventStore 中的 JSON 文本。"""

    return json.loads(value)


def event_from_row(row: sqlite3.Row) -> LoopEvent:
    """将 SQLite 事件行恢复为领域事件。"""

    return LoopEvent.from_dict(
        {
            "schema_version": row["schema_version"],
            "event_id": row["event_id"],
            "thread_id": row["thread_id"],
            "sequence": row["sequence"],
            "event_type": row["event_type"],
            "causation_id": row["causation_id"],
            "correlation_id": row["correlation_id"],
            "payload": loads(row["payload_json"]),
            "payload_sha256": row["payload_sha256"],
            "created_at": row["created_at"],
        }
    )


__all__ = ["dumps", "event_from_row", "loads"]
