"""v2.0 Loop 子系统 — Channel 系统 + CheckpointEnvelope (v2.0 Checkpoint 数据) + 收敛判定 + Checkpoint 持久化 + 多 Agent 并发.

参考 LangGraph Channel 系统 + design/v2.0-Analysis-Loop.md §4.4/§4.7/§五.

Channel 三种类型语义:
- LastValueChannel[T]:   单写,后续覆盖 (Plan 状态、Review 结论)
- AccumulatingChannel[T]: 多写,append 列表 (Task 完成列表、Gate 结果汇总)
- BarrierChannel:        等待所有 Agent 完成 (asyncio.Event 同步点)

收敛判定 (v2.0 Phase 02):
- 4 级判定 (硬上限/质量门/停滞检测/语义收敛) + 默认继续
- 详见 design/v2.0-Analysis-Loop.md §4.7

Checkpoint 持久化 (v2.0 Phase 02):
- SQLite 持久化 CheckpointEnvelope + history
- Schema 版本号 + 事务保证 + 线程隔离

多 Agent 并发 (v2.0 Phase 03):
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
    Verdict,
)
from auto_engineering.loop.orchestrator import (
    Orchestrator,
    OrchestratorConfig,
)
from auto_engineering.loop.plan import (
    Plan,
    Task,
    TaskDAG,
)
from auto_engineering.loop.round import (
    Round,
    RoundResult,
)
# v2.3 P0-A (BEACON 决策 23): CheckpointEnvelope / Channel 不再从 __init__ 导出
# (消除与 engine.state.LoopState 同名双义). 需显式:
#   from auto_engineering.loop.state import CheckpointEnvelope, Channel, LastValueChannel, ...
# v2.3 P0-A: 原 LoopState (v2.0 Pydantic) 已重命名为 CheckpointEnvelope.

# 字母序排列 (v2.3 P1-III: 缩减到核心 API)
__all__ = [
    "Checkpoint",
    "ConvergenceConfig",
    "ConvergenceJudge",
    "Orchestrator",
    "OrchestratorConfig",
    "Plan",
    "Round",
    "RoundHistory",
    "RoundResult",
    "SQLiteCheckpointStore",
    "Task",
    "TaskDAG",
    "Verdict",
]
