"""宿主执行后的 Task 回执数据模型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TaskOutcome:
    """单个 Task 的执行结果。"""

    task_id: str
    status: str  # completed | failed | cancelled
    output: object = None
    error: str | None = None
    duration: float = 0.0
    task_role: str | None = None


__all__ = ["TaskOutcome"]
