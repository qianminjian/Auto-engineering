"""Architect 与 Critic 的宿主无关纯 StageHandler。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.stages.base import (
    StageName,
    TransitionContext,
    TransitionDecision,
)


def _advanced(
    *,
    source: StageName,
    target: StageName,
    context: TransitionContext,
) -> LoopEvent:
    return LoopEvent.create(
        thread_id=context.thread_id,
        sequence=context.event_sequence,
        event_type=LoopEventType.STAGE_ADVANCED,
        payload={"from": source, "to": target},
        correlation_id=context.thread_id,
    )


def _has_batches(raw: object) -> bool:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return False
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        nested = item.get("batches")
        if nested is None or (
            isinstance(nested, Sequence)
            and not isinstance(nested, (str, bytes))
            and bool(nested)
        ):
            return True
    return False


class ArchitectHandler:
    stage: StageName = "architect"

    def apply(
        self,
        state: object,
        result: Mapping[str, Any],
        context: TransitionContext,
    ) -> TransitionDecision:
        if not isinstance(state, Mapping):
            raise TypeError("state 必须为 Mapping")
        if not _has_batches(state.get("batch_plan")):
            return TransitionDecision(
                action_context={
                    "error": {
                        "error_code": "EMPTY_BATCH_PLAN",
                        "message": "architect 输出 batch_plan 为空",
                    }
                }
            )
        target: StageName = "developer"
        return TransitionDecision(
            events=(_advanced(source=self.stage, target=target, context=context),),
            next_stage=target,
            action_context={
                "initialize_architecture": True,
                "offload_stage": self.stage,
            },
        )


class CriticHandler:
    stage: StageName = "critic"

    def apply(
        self,
        state: object,
        result: Mapping[str, Any],
        context: TransitionContext,
    ) -> TransitionDecision:
        if not isinstance(state, Mapping):
            raise TypeError("state 必须为 Mapping")
        verdict = result.get("verdict", "")
        common: dict[str, Any] = {
            "collect_token_usage": True,
            "offload_stage": self.stage,
            "critic_progress": verdict,
        }
        if verdict not in {"MAJOR", "APPROVE"}:
            common["error"] = {
                "error_code": "INVALID_VERDICT",
                "message": (
                    f"非法 verdict: {verdict!r}, 期望值: MAJOR 或 APPROVE"
                ),
            }
            return TransitionDecision(action_context=common)

        in_a_row = int(state.get("majors_in_a_row", 0))
        total = int(state.get("total_majors", 0))
        if verdict == "APPROVE":
            common["state_patch"] = {
                "majors_in_a_row": 0,
                "total_majors": total,
            }
            target: StageName = (
                "developer"
                if bool(context.extensions.get("has_more_batches"))
                else "component_verifier"
            )
            return TransitionDecision(
                events=(
                    _advanced(source=self.stage, target=target, context=context),
                ),
                next_stage=target,
                action_context=common,
            )

        in_a_row += 1
        total += 1
        common["state_patch"] = {
            "majors_in_a_row": in_a_row,
            "total_majors": total,
        }
        max_in_a_row = int(context.extensions.get("max_majors_in_a_row", 3))
        max_total = int(context.extensions.get("max_total_majors", 4))
        if in_a_row >= max_in_a_row or total >= max_total:
            common["terminal_action"] = {
                "verdict": "HARD_LIMIT",
                "reason": f"MAJOR 超限: 连续{in_a_row}/累计{total}",
            }
            return TransitionDecision(
                terminal=True,
                action_context=common,
            )

        target = "developer"
        common["cursor_operation"] = "rollback_batch"
        common["feedback"] = list(result.get("findings", []))
        return TransitionDecision(
            events=(_advanced(source=self.stage, target=target, context=context),),
            next_stage=target,
            action_context=common,
        )


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
            events=(_advanced(source=self.stage, target=target, context=context),),
            next_stage=target,
        )


__all__ = ["ArchitectHandler", "CriticHandler", "PlanRefineHandler"]
