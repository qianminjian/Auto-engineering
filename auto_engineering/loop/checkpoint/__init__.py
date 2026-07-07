"""v2.0 SQLite Checkpoint 持久化 — 子模块 re-export.

从 loop/checkpoint.py 拆分 (P1-E):
  - checkpoint/records.py: Checkpoint + CheckpointMeta + 错误类型
  - checkpoint/_connection.py: SQLite 连接管理 (":memory:" vs file 模式 + lock)
  - checkpoint/_serialization.py: 状态 JSON 互转 + 嵌套 dataclass 归一化
  - checkpoint/store.py: SQLiteCheckpointStore 业务方法
  - checkpoint/manager.py: CheckpointManager 协作策略 (v5.4 审计 P0-1)
  - checkpoint/__init__.py (本文件): re-export 所有公开符号, 保持向后兼容

设计来源: design/v2.0-Analysis-Loop.md §4.4 + §五 v2.0

P1-E 拆分: checkpoint.py 705 行 → checkpoint/store.py(≤400) + checkpoint/records.py(≤140).
v2.5 P1-D 二次拆分: store.py 609 行 → store.py(290) + _connection.py(76) + _serialization.py(92),
符合 engineering-practices.md §3.1 动态语言 300 行上限.
"""

from __future__ import annotations

from auto_engineering.loop.checkpoint.records import (
    Checkpoint,
    CheckpointError,
    CheckpointMeta,
    CheckpointNotFoundError,
    CheckpointSchemaMismatchError,
)
from auto_engineering.loop.checkpoint.manager import CheckpointManager
from auto_engineering.loop.checkpoint.store import (
    DB_SCHEMA_VERSION,
    SQLiteCheckpointStore,
)

__all__ = [
    "Checkpoint",
    "CheckpointError",
    "CheckpointManager",
    "CheckpointMeta",
    "CheckpointNotFoundError",
    "CheckpointSchemaMismatchError",
    "DB_SCHEMA_VERSION",
    "SQLiteCheckpointStore",
]
