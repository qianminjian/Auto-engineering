"""StageHandler 契约与注册表。"""

from auto_engineering.loop.stages.base import (
    StageHandler,
    StageName,
    TransitionContext,
    TransitionDecision,
)
from auto_engineering.loop.stages.registry import StageHandlerRegistry

__all__ = [
    "StageHandler",
    "StageHandlerRegistry",
    "StageName",
    "TransitionContext",
    "TransitionDecision",
]
