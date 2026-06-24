"""Loop 引擎 — Layer 1 (LoopEngine) + Layer 2 (StageGraph) + 共享类型.

借鉴 LangGraph pregel/_loop.py + graph/state.py.
Phase 1 提供: 核心循环 + Checkpoint 持久化 + Stage 调度.
Phase 2+ 在此基础上加 Runtime + Guardrail 中间件.
"""

from .checkpoint import Checkpoint, CheckpointStore
from .graph import (
    ConditionSpec,
    Stage,
    StageGraph,
    build_dev_loop_graph,
)
from .loop import (
    LoopDrained,
    LoopEngine,
    LoopInterrupted,
    LoopResult,
    StageResult,
)
from .messages import Send
from .state import LoopState

__all__ = [
    # 核心引擎
    "LoopEngine",
    "LoopResult",
    "StageResult",
    "LoopInterrupted",
    "LoopDrained",
    # 状态
    "LoopState",
    # Checkpoint
    "Checkpoint",
    "CheckpointStore",
    # Stage 图
    "Stage",
    "StageGraph",
    "ConditionSpec",
    "build_dev_loop_graph",
    # 多 Agent 预留
    "Send",
]
