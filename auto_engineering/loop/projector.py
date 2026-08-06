"""由 append-only LoopEvent 重建 EngineState 投影。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, ClassVar

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.events import LoopEvent, LoopEventType


class ProjectionError(ValueError):
    """事件流不能确定性投影为 EngineState。"""


class EngineStateProjector:
    """无副作用的 EngineState 事件投影器。"""

    _SEED_EVENTS: ClassVar[set[LoopEventType]] = {
        LoopEventType.LOOP_INITIALIZED,
        LoopEventType.CHECKPOINT_IMPORTED,
    }

    def replay(self, events: Iterable[LoopEvent]) -> EngineState:
        stream = list(events)
        if not stream or stream[0].event_type not in self._SEED_EVENTS:
            raise ProjectionError("事件流必须以状态初始化事件开始")
        thread_id = stream[0].thread_id
        for expected_sequence, event in enumerate(stream):
            if event.thread_id != thread_id:
                raise ProjectionError("事件流必须属于同一 thread")
            if event.sequence != expected_sequence:
                raise ProjectionError(
                    f"事件 sequence 必须连续；期望 {expected_sequence}，"
                    f"实际 {event.sequence}"
                )

        seed = stream[0].to_dict()["payload"].get("state")
        if not isinstance(seed, dict):
            raise ProjectionError("初始化事件 payload.state 必须为 object")
        state = EngineState.from_dict(seed)
        if state.thread_id != thread_id:
            raise ProjectionError("初始化状态 thread_id 与事件流不一致")

        for event in stream[1:]:
            payload = event.to_dict()["payload"]
            patch = payload.get("state_patch")
            if patch is not None:
                if not isinstance(patch, Mapping):
                    raise ProjectionError("state_patch 必须为 object")
                state = self._apply_patch(state, patch)
            if event.event_type is LoopEventType.STAGE_ADVANCED:
                target = payload.get("to")
                if not isinstance(target, str):
                    raise ProjectionError("StageAdvanced payload.to 必须为字符串")
                state = self._apply_patch(state, {"current_stage": target})
            if event.event_type is LoopEventType.ARCHITECTURE_BASELINE_ACCEPTED:
                baseline = payload.get("baseline")
                if not isinstance(baseline, Mapping):
                    raise ProjectionError(
                        "ArchitectureBaselineAccepted payload.baseline 必须为 object"
                    )
                state = self._apply_patch(
                    state, {"architecture_baseline": dict(baseline)}
                )
        return state

    @staticmethod
    def _apply_patch(
        state: EngineState,
        patch: Mapping[str, Any],
    ) -> EngineState:
        data = state.to_dict()
        unknown = sorted(set(patch) - set(data))
        if unknown:
            raise ProjectionError(f"state_patch 含未知字段: {', '.join(unknown)}")
        data.update(dict(patch))
        return EngineState.from_dict(data)


__all__ = ["EngineStateProjector", "ProjectionError"]
