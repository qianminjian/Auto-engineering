"""兼容 plan_refine Stage 的最小恢复处理器。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from auto_engineering.loop.stages.base import StageName, TransitionContext, TransitionDecision
from auto_engineering.loop.stages.design_helpers import advanced


class PlanRefineHandler:
    """恢复落在兼容 `plan_refine` stage 的线程并重返 Architect。"""

    stage: StageName = "plan_refine"

    def apply(
        self,
        state: object,
        result: Mapping[str, Any],
        context: TransitionContext,
    ) -> TransitionDecision:
        if not isinstance(state, Mapping):
            raise TypeError("state 必须为 Mapping")
        target: StageName = "architect"
        return TransitionDecision(
            events=(advanced(source=self.stage, target=target, context=context),),
            next_stage=target,
        )


__all__ = ["PlanRefineHandler"]
