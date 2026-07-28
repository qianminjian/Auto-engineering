"""StageHandler 唯一注册与 fail-closed 查询。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast, get_args

from auto_engineering.loop.stages.base import StageHandler, StageName

_KNOWN_STAGES = frozenset(get_args(StageName))


class StageHandlerRegistryError(LookupError):
    """StageHandler 注册表错误。"""


class DuplicateStageHandlerError(StageHandlerRegistryError):
    """同一 Stage 注册了多个 Handler。"""


class MissingStageHandlerError(StageHandlerRegistryError):
    """合法 Stage 尚未注册 Handler。"""


class StageHandlerRegistry:
    """每个 Stage 最多且查询时恰好一个 Handler。"""

    def __init__(self, handlers: Iterable[StageHandler] = ()) -> None:
        self._handlers: dict[StageName, StageHandler] = {}
        for handler in handlers:
            self.register(handler)

    @property
    def stages(self) -> frozenset[StageName]:
        return frozenset(self._handlers)

    def register(self, handler: StageHandler) -> None:
        stage = handler.stage
        if stage not in _KNOWN_STAGES:
            raise ValueError(f"未知 stage: {stage!r}")
        if stage in self._handlers:
            raise DuplicateStageHandlerError(
                f"stage {stage!r} 已存在 Handler"
            )
        self._handlers[stage] = handler

    def get(self, stage: StageName) -> StageHandler:
        if stage not in _KNOWN_STAGES:
            raise ValueError(f"未知 stage: {stage!r}")
        normalized = cast(StageName, stage)
        try:
            return self._handlers[normalized]
        except KeyError:
            raise MissingStageHandlerError(
                f"stage {stage!r} 缺少 Handler"
            ) from None


__all__ = [
    "DuplicateStageHandlerError",
    "MissingStageHandlerError",
    "StageHandlerRegistry",
    "StageHandlerRegistryError",
]
