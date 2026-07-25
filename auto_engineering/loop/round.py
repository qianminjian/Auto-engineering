"""v2.0 — TaskOutcome backward compat re-export.

TaskOutcome 已迁移至 engine/models.py (P2-2, 2026-07-21).
通过 plan.py 重新导出. 向后兼容: 保留 from round import TaskOutcome.

RoundResult 虚化代码已移除 (V1 ghost code cleanup, 2026-07-25).
"""

from __future__ import annotations

from auto_engineering.loop.plan import TaskOutcome  # backward compat re-export

__all__ = [
    "TaskOutcome",
]
