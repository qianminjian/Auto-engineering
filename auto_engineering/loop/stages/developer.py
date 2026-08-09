"""Developer 的宿主无关纯 StageHandler。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from auto_engineering.loop.domain_events import transition_event
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.stages.base import (
    LifecycleEffects,
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
                lifecycle_effects=LifecycleEffects(
                    collect_token_usage=True,
                    offload_stage=self.stage,
                ),
                next_stage="developer",
                advance_stage=False,
                action_context={
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
        action_context: dict[str, Any] = {}
        pre_gate = context.extensions.get("next_pre_gate")
        if more and isinstance(pre_gate, Mapping):
            action_context["pre_gate"] = dict(pre_gate)
        completed_batch_id = context.extensions.get("completed_batch_id")
        events: tuple[LoopEvent, ...] = (
            transition_event(
                LoopEventType.BATCH_COMPLETED,
                thread_id=context.thread_id,
                sequence=context.event_sequence,
            ),
        )
        if not more:
            events += (
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
            advance_stage=not more,
            action_context=action_context,
            lifecycle_effects=LifecycleEffects(
                collect_token_usage=True,
                completed_batch_id=(
                    completed_batch_id
                    if isinstance(completed_batch_id, str)
                    else None
                ),
                save_checkpoint=more,
                offload_stage=self.stage,
                snapshot_developer_output=not more,
                developer_progress=progress,
            ),
        )


__all__ = ["DeveloperHandler"]
