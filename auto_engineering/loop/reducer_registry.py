"""领域 Reducer 的注册表。"""

from __future__ import annotations

from collections.abc import Callable

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.events import LoopEvent, LoopEventType


class EventChannelViolation(ValueError):
    """事件尝试修改不属于自身的 Projection channel。"""


Reducer = Callable[[EngineState, LoopEvent], EngineState]


class ReducerRegistry:
    """Event Type 到纯 Reducer 的唯一注册表。"""

    def __init__(self) -> None:
        self._reducers: dict[LoopEventType, Reducer] = {}

    def register(self, event_type: LoopEventType, reducer: Reducer) -> None:
        if event_type in self._reducers:
            raise ValueError(f"Reducer 重复注册: {event_type.value}")
        self._reducers[event_type] = reducer

    def reduce(self, state: EngineState, event: LoopEvent) -> EngineState:
        reducer = self._reducers.get(event.event_type)
        if reducer is None:
            raise EventChannelViolation(f"未注册事件 Reducer: {event.event_type.value}")
        return reducer(state, event)


__all__ = ["EventChannelViolation", "Reducer", "ReducerRegistry"]
