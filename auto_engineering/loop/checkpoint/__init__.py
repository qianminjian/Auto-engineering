"""v2.0 SQLite Checkpoint 持久化 — 子模块 re-export.

从 loop/checkpoint.py 拆分 (P1-E):
  - checkpoint/envelope.py: Checkpoint + CheckpointMeta + 错误类型
  - checkpoint/store.py: SQLiteCheckpointStore + SCHEMA_VERSION + _normalize_* helpers
  - checkpoint/__init__.py (本文件): re-export 所有公开符号, 保持向后兼容

设计来源: design/v2.0-Analysis-Loop.md §4.4 + §五 Phase 1.2

P1-E 拆分: checkpoint.py 705 行 → checkpoint/store.py(≤400) + checkpoint/envelope.py(≤140).
"""

from __future__ import annotations

from auto_engineering.loop.checkpoint.envelope import (
    Checkpoint,
    CheckpointError,
    CheckpointMeta,
    CheckpointNotFoundError,
    CheckpointSchemaMismatchError,
)
from auto_engineering.loop.checkpoint.store import (
    SCHEMA_VERSION,
    SQLiteCheckpointStore,
)

__all__ = [
    "Checkpoint",
    "CheckpointError",
    "CheckpointMeta",
    "CheckpointNotFoundError",
    "CheckpointSchemaMismatchError",
    "SCHEMA_VERSION",
    "SQLiteCheckpointStore",
]
