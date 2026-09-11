"""EventStore UsageRecorded 事实的只读值对象。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UsageRecord:
    """单条用量事实的投影，不负责数据库读写。"""

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
    core_payload_bytes: int | None = None
    inline_unique_bytes: int | None = None
    duplicate_block_bytes: int | None = None
    host_context_window_units: int | None = None
    estimator_version: str = ""
    action_message_id: str | None = None


__all__ = ["UsageRecord"]
