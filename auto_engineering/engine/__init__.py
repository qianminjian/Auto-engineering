"""engine/ — v2.0 体系已移除 (v2.4 P0-FINAL).

保留 engine/state.py (EngineState + LoopState alias) 供 v2.0 runtime 用.
v2.0 主路径在 loop/ 和 runtime/ 中.
"""

from .state import EngineState, LoopState

__all__ = ["EngineState", "LoopState"]
