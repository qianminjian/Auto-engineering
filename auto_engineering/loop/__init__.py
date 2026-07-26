"""v5.6 Loop 子系统 — Tick 引擎 + 收敛判定 + Checkpoint 持久化.

Channel[T] ABC 体系 (LastValueChannel/AccumulatingChannel/BarrierChannel) —
仅用于 v2.5→v5.6 checkpoint 迁移 (migration.py + checkpoint_envelope.py)。
主循环状态管理走 engine.state.EngineState dataclass, 不经过 Channel。
Channel 类型不导出 (AD2: 内部实现细节)。
- Plan/Task DAG + check_file_isolation (确定性文件隔离检查)
- Round 生命周期 + asyncio.gather 并发调度
- Orchestrator 主循环 (Round Loop + 收敛判定 + 取消支持)

v2.3 P1-III: 缩减导出符号到核心 15 个 (原 16, 移除 LoopState — 详见 BEACON 决策 23).
v2.3 P0-A: CheckpointEnvelope (原 LoopState) 从 v2.0 Pydantic 重命名, 明确"v2.0 Checkpoint 专用"
    — 运行时 Orchestrator / Runtime / Gates 走 engine.state.LoopState (v2.0 dataclass).
    CheckpointEnvelope / Channel / 辅助类型需显式 import `auto_engineering.loop.state`.
    不通过 __init__ 导出 (消除与 engine.state.LoopState 的同名双义).

内部类型通过子模块访问, 不通过 __init__ 导出.
"""

from auto_engineering.loop.checkpoint import (
    Checkpoint,
    SQLiteCheckpointStore,
)
from auto_engineering.loop.convergence import (
    ConvergenceConfig,
    ConvergenceJudge,
    RoundHistory,
)
from auto_engineering.loop.plan import (
    Plan,
    Task,
)

# RoundResult 虚化代码已移除 (V1 ghost code cleanup, 2026-07-25)

# v2.3 P0-A (BEACON 决策 23): CheckpointEnvelope / Channel 不再从 __init__ 导出
# (消除与 engine.state.LoopState 同名双义). 需显式:
#   from auto_engineering.loop.state import CheckpointEnvelope, Channel, LastValueChannel, ...
# v2.3 P0-A: 原 LoopState (v2.0 Pydantic) 已重命名为 CheckpointEnvelope.

# 字母序排列
__all__ = [
    "Checkpoint",
    "ConvergenceConfig",
    "ConvergenceJudge",
    "Plan",
    "RoundHistory",
    "SQLiteCheckpointStore",
    "Task",
]
