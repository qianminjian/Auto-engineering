"""Checkpoint 数据记录 — 数据类 + 错误类型.

从 loop/checkpoint.py 拆分 (P1-E: checkpoint → checkpoint/ 子模块).
v5.4 审计 P1-7: 重命名 envelope.py → records.py, 消除与 state/checkpoint_envelope.py 的命名歧义.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

from auto_engineering.loop.convergence import RoundHistory
from auto_engineering.loop.types import LoopStateProtocol

# v2.2-G: 用 Protocol 替代 Any, 打破循环引用并提供类型安全
# - LoopStateProtocol 在 loop/types.py 定义 (不引用 loop/state)
# - TypeVar T bound Protocol 让 Checkpoint/SQLiteCheckpointStore 接受具体类型
# - mypy 看到 state 字段是 LoopStateProtocol (或其子类型), 不是 Any
# - v5.4 P2-2: TypeVar bound 仅 mypy 静态检查, 运行时无强制. EngineState 不实现
#   LoopStateProtocol (缺 round/step/status/channels), 但 save() 入口的
#   _validate_state_serializable() 做 duck-type 兼容性检查.
T = TypeVar("T", bound=LoopStateProtocol)


# ============================================================
# 数据类: Checkpoint 元数据 + 完整记录
# ============================================================


@dataclass
class CheckpointMeta:
    """Checkpoint 元数据 (轻量, 用于 list)."""

    id: str
    round: int
    step: int
    created_at: datetime
    schema_version: int
    parent_id: str | None = None
    tag: str | None = None


@dataclass
class Checkpoint[T]:
    """完整 Checkpoint (含 state + history).

    v2.2-G: 用 Generic[T] bound LoopStateProtocol 替代 Any.
    - 类型安全: mypy 看到 state 字段是 LoopStateProtocol, 访问 .round/.step 不报 Any
    - 打破循环: checkpoint.py 不再 import 具体 LoopState 类, 只用 Protocol 接口
    - 使用: Checkpoint[CheckpointEnvelope](...) — caller 显式指定 T
    """

    id: str
    round: int
    step: int
    state: T  # LoopStateProtocol (caller 决定具体类型, 典型 CheckpointEnvelope)
    history: list[RoundHistory]  # v2.3 Phase M (P2.3): 强类型, 非 list[dict]
    created_at: datetime
    schema_version: int
    parent_id: str | None = None
    tag: str | None = None

    def meta(self) -> CheckpointMeta:
        """提取元数据."""
        return CheckpointMeta(
            id=self.id,
            round=self.round,
            step=self.step,
            created_at=self.created_at,
            schema_version=self.schema_version,
            parent_id=self.parent_id,
            tag=self.tag,
        )


# ============================================================
# Checkpoint Store 异常
# ============================================================


class CheckpointError(Exception):
    """Checkpoint 操作基础异常."""


class CheckpointNotFoundError(CheckpointError):
    """Checkpoint 不存在."""


class CheckpointSchemaMismatchError(CheckpointError):
    """Schema 版本不匹配."""

    def __init__(self, found: int, expected: int) -> None:
        self.found = found
        self.expected = expected
        super().__init__(
            f"Schema version mismatch: found {found}, expected {expected}"
        )
