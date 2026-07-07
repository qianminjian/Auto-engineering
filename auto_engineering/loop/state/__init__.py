"""v2.0 Channel 系统 + CheckpointEnvelope (v2.0 Checkpoint 数据结构).

参考 LangGraph Channel 系统(LastValue / Topic / NamedBarrierValue).
简化: 三种类型覆盖 LOOP 子系统的核心语义, 不引入 Pregel 的版本触发机制.

设计来源: design/v2.0-Analysis-Loop.md §4.4 状态管理
v2.0-A 增强: LangGraph 对齐的 copy/checkpoint/from_checkpoint 序列化三件套.
v2.0-D 增强: CheckpointEnvelope 8 字段 + Task 字段补全 + load() 重建 Channel 实例.

CheckpointEnvelope (原名 LoopState, v2.3 P0-A 重命名):
    v2.0 Checkpoint 持久化的数据结构 (Pydantic BaseModel).
    仅供 checkpoint 持久化 / migrate (v2.0->v2.0) 使用.
    运行时 Orchestrator 不使用此类型 (走 engine.state.LoopState v2.0 dataclass).
    详见 BEACON.md 决策 23 (Channel 体系归属: checkpoint 专用).

    重命名原因: 消除 "LoopState" 同名双义 -- engine.state.LoopState (v2.0 dataclass,
    运行时生产代码用) vs loop.state.LoopState (v2.0 Pydantic, checkpoint 专用).
    新名 "CheckpointEnvelope" 明确语义: v2.0 Checkpoint 数据信封.

P1-A 拆分: state.py 702 行 -> state/channels.py + state/checkpoint_envelope.py + state/metrics.py.
"""

from __future__ import annotations

from auto_engineering.loop.checkpoint._serialization import (
    Channel,
)
from auto_engineering.loop.state.checkpoint_envelope import (
    CheckpointEnvelope,
    deserialize_loop_state,
)

__all__ = [
    "Channel",
    "CheckpointEnvelope",
    "deserialize_loop_state",
]
