"""v2.0 Loop 子系统 — Channel 系统 + LoopState 容器.

参考 LangGraph Channel 系统 + design/v2.0-Analysis-Loop.md §4.4 状态管理.

Channel 三种类型语义:
- LastValueChannel[T]:   单写,后续覆盖 (Plan 状态、Review 结论)
- AccumulatingChannel[T]: 多写,append 列表 (Task 完成列表、Gate 结果汇总)
- BarrierChannel:        等待所有 Agent 完成 (asyncio.Event 同步点)
"""

from auto_engineering.loop.state import (
    AccumulatingChannel,
    BarrierChannel,
    Channel,
    LastValueChannel,
    LoopState,
)

__all__ = [
    "AccumulatingChannel",
    "BarrierChannel",
    "Channel",
    "LastValueChannel",
    "LoopState",
]