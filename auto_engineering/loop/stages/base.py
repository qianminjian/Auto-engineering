"""StageHandler 的宿主无关纯转换契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from auto_engineering.loop.events import LoopEvent

StageName = Literal[
    "gap_scan",
    "gap_review",
    "research",
    "architect",
    "developer",
    "critic",
    "component_verifier",
    "plate_deep_audit",
    "system_verifier",
    "system_deep_audit",
    "plan_refine",
]


@dataclass(frozen=True, slots=True)
class TransitionContext:
    """一次 Stage 转换所需的内核上下文。"""

    thread_id: str
    tick: int
    event_sequence: int = 0
    extensions: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TransitionDecision:
    """Handler 的唯一输出；不执行持久化或其他副作用。"""

    events: tuple[LoopEvent, ...] = ()
    next_stage: StageName | None = None
    gate: Mapping[str, Any] | None = None
    terminal: bool = False
    action_context: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class StageHandler(Protocol):
    """单一 Stage 的确定性转换实现。"""

    stage: StageName

    def apply(
        self,
        state: object,
        result: Mapping[str, Any],
        context: TransitionContext,
    ) -> TransitionDecision: ...


__all__ = [
    "StageHandler",
    "StageName",
    "TransitionContext",
    "TransitionDecision",
]
