"""Developer 的宿主无关纯 StageHandler。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.stages.base import (
    StageName,
    TransitionContext,
    TransitionDecision,
)


class DeveloperHandler:
    stage: StageName = "developer"

    def apply(
        self,
        state: object,
        result: Mapping[str, Any],
        context: TransitionContext,
    ) -> TransitionDecision:
        if not isinstance(state, Mapping):
            raise TypeError("state 必须为 Mapping")
        blocking = context.extensions.get("blocking_gate_results", ())
        if (
            isinstance(blocking, (list, tuple))
            and blocking
        ):
            return TransitionDecision(
                next_stage="developer",
                action_context={
                    "collect_token_usage": True,
                    "offload_stage": self.stage,
                    "stay_in_stage": True,
                    "feedback": {
                        "reason": "required_gate_failed",
                        "gates": list(blocking),
                    },
                },
            )
        more = bool(
            context.extensions.get("has_more_batches_after_advance")
        )
        target: StageName = "developer" if more else "critic"
        progress = {
            "design_section": context.extensions.get("design_section", ""),
            "completed_task_count": int(
                context.extensions.get("completed_task_count", 0)
            ),
            "next_task": context.extensions.get("next_task"),
        }
        action_context = {
            "collect_token_usage": True,
            "cursor_operation": "advance_batch",
            "completed_batch_id": context.extensions.get(
                "completed_batch_id"
            ),
            "developer_progress": progress,
            "save_checkpoint": more,
            "offload_stage": self.stage,
            "snapshot_developer_output": not more,
            "stay_in_stage": more,
        }
        pre_gate = context.extensions.get("next_pre_gate")
        if more and isinstance(pre_gate, Mapping):
            action_context["pre_gate"] = dict(pre_gate)
        events: tuple[LoopEvent, ...] = ()
        if not more:
            events = (
                LoopEvent.create(
                    thread_id=context.thread_id,
                    sequence=context.event_sequence,
                    event_type=LoopEventType.STAGE_ADVANCED,
                    payload={"from": self.stage, "to": target},
                    correlation_id=context.thread_id,
                ),
            )
        return TransitionDecision(
            events=events,
            next_stage=target,
            action_context=action_context,
        )


__all__ = ["DeveloperHandler"]
