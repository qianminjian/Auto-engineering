"""Engine 子系统 — 共享状态 + 批量编排 + 进度追踪 + 验证层.

EngineState: v5.6 tick 循环共享状态 (dataclass, A3 写所有权白名单),
在 architect/developer/critic 等 stage 间传递, 经 checkpoint 跨进程持久化。
(2026-07-26 审计修复 P2-11: 原 docstring 误写为 state.py 的 v5.0 描述)
"""

from .state import EngineState, LoopState

__all__ = ["EngineState", "LoopState"]
