"""v2.0 Loop 子系统 — Channel 系统 + LoopState + 收敛判定 + Checkpoint + 多 Agent 并发.

参考 LangGraph Channel 系统 + design/v2.0-Analysis-Loop.md §4.4/§4.7/§五.

Channel 三种类型语义:
- LastValueChannel[T]:   单写,后续覆盖 (Plan 状态、Review 结论)
- AccumulatingChannel[T]: 多写,append 列表 (Task 完成列表、Gate 结果汇总)
- BarrierChannel:        等待所有 Agent 完成 (asyncio.Event 同步点)

收敛判定 (v2.0 Phase 02):
- 4 级判定 (硬上限/质量门/停滞检测/语义收敛) + 默认继续
- 详见 design/v2.0-Analysis-Loop.md §4.7

Checkpoint 持久化 (v2.0 Phase 02):
- SQLite 持久化 LoopState + history
- Schema 版本号 + 事务保证 + 线程隔离

多 Agent 并发 (v2.0 Phase 03):
- Plan/Task DAG + check_file_isolation (确定性文件隔离检查)
- Round 生命周期 + asyncio.gather 并发调度
- Orchestrator 主循环 (Round Loop + 收敛判定 + 取消支持)
"""

from auto_engineering.loop.checkpoint import (
    SCHEMA_VERSION,
    Checkpoint,
    CheckpointError,
    CheckpointMeta,
    CheckpointNotFoundError,
    CheckpointSchemaMismatchError,
    SQLiteCheckpointStore,
)
from auto_engineering.loop.convergence import (
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_STAGNATION_DIFF_RATIO,
    DEFAULT_STAGNATION_THRESHOLD,
    LEVEL_CONTINUE,
    LEVEL_HARD_LIMIT,
    LEVEL_QUALITY,
    LEVEL_SEMANTIC,
    LEVEL_STAGNANT,
    ConvergenceConfig,
    ConvergenceJudge,
    RoundHistory,
    Verdict,
    detect_stagnation,
    diff_ratio,
)
from auto_engineering.loop.orchestrator import (
    Orchestrator,
    OrchestratorConfig,
)
from auto_engineering.loop.plan import (
    ConflictError,
    Plan,
    Task,
    TaskDAG,
    TaskStatus,
    check_file_isolation,
    topological_sort,
)
from auto_engineering.loop.round import (
    Round,
    RoundResult,
    TaskExecutor,
    TaskOutcome,
    run_round,
)
from auto_engineering.loop.state import (
    AccumulatingChannel,
    BarrierChannel,
    Channel,
    LastValueChannel,
    LoopState,
)

# 字母序排列 (ruff RUF022)
__all__ = [
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_STAGNATION_DIFF_RATIO",
    "DEFAULT_STAGNATION_THRESHOLD",
    "LEVEL_CONTINUE",
    "LEVEL_HARD_LIMIT",
    "LEVEL_QUALITY",
    "LEVEL_SEMANTIC",
    "LEVEL_STAGNANT",
    "SCHEMA_VERSION",
    "AccumulatingChannel",
    "BarrierChannel",
    "Channel",
    "Checkpoint",
    "CheckpointError",
    "CheckpointMeta",
    "CheckpointNotFoundError",
    "CheckpointSchemaMismatchError",
    "ConflictError",
    "ConvergenceConfig",
    "ConvergenceJudge",
    "LastValueChannel",
    "LoopState",
    "Orchestrator",
    "OrchestratorConfig",
    "Plan",
    "Round",
    "RoundHistory",
    "RoundResult",
    "SQLiteCheckpointStore",
    "Task",
    "TaskDAG",
    "TaskExecutor",
    "TaskOutcome",
    "TaskStatus",
    "Verdict",
    "check_file_isolation",
    "detect_stagnation",
    "diff_ratio",
    "run_round",
    "topological_sort",
]