"""Checkpoint 数据记录 — 数据类 + 错误类型.

从 loop/checkpoint.py 拆分 (P1-E: checkpoint → checkpoint/ 子模块).
v5.4 审计 P1-7: 重命名 envelope.py → records.py, 消除与 state/checkpoint_envelope.py 的命名歧义.
v5.6 审计 P1-7 (2026-07-21): RoundHistory 定义迁移至此, 消除 checkpoint→loop 依赖倒置.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from auto_engineering.gates.base import GateVerdict

# v5.5 P1-8: TypeVar 移除 LoopStateProtocol bound (Protocol 形同虚设, 项目不使用 mypy).
# Checkpoint.state 的实际类型由 caller 决定, 运行时通过 _validate_state_serializable() 做 duck-type 检查.
T = TypeVar("T")


# ============================================================
# RoundHistory — 单轮历史记录 (2026-07-21 P1-7 从 convergence.py 迁移)
# ============================================================


@dataclass
class RoundHistory:
    """单轮历史记录.

    用于停滞检测算法: 计算与上一轮的 diff 变化率.

    Attributes:
        round_id: 轮次 ID (1-indexed)
        files_changed: 本轮修改的文件数
        lines_added: 本轮新增行数
        lines_removed: 本轮删除行数
        gate_results: 保留完整 GateVerdict 对象 dict[gate_name, GateVerdict].
        semantic_satisfied: LLM 语义评估是否通过
        tasks_run: 本轮实际跑的 task IDs
        task_outcomes: 本轮每个 task 的最终状态
        channel_versions: Channel 版本追踪
    """

    round_id: int
    stage: str = ""
    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    gate_results: dict[str, GateVerdict] = field(default_factory=dict)
    guardrail_result: str | None = None
    semantic_satisfied: bool | None = None
    tasks_run: list[str] = field(default_factory=list)
    task_outcomes: dict[str, str] = field(default_factory=dict)
    channel_versions: dict[str, int] = field(default_factory=dict)


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

    v2.2-G: 用 Generic[T] 替代 Any, v5.5 P1-8 移除 Protocol bound.
    - 使用: Checkpoint[CheckpointEnvelope](...) — caller 显式指定 T
    """

    id: str
    round: int
    step: int
    state: T  # caller 决定具体类型, 典型 CheckpointEnvelope
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
