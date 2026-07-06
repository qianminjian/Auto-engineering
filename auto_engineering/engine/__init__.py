"""engine/state — EngineState + LoopState 供 Loop-Engine 使用.

EngineState 是 18-field Channel-based 共享状态 (v5.0 §B1.1),
在 architect/developer/critic 三阶段 Agent 循环中传递.
"""

from .state import EngineState, LoopState

__all__ = ["EngineState", "LoopState"]
