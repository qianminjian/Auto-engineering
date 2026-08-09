"""Architect 与 Critic 的宿主无关纯 StageHandler。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from auto_engineering.loop.domain_events import channels_updated, transition_event
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
            events=(
                transition_event(
                    LoopEventType.ARCHITECTURE_INITIALIZATION_REQUESTED,
                    thread_id=context.thread_id,
                    sequence=context.event_sequence,
                ),
                _advanced(source=self.stage, target=target, context=context),
            ),
            next_stage=target,
            action_context={
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
        findings = list(result.get("findings", []))
        blocking_findings = [
            finding for finding in findings
            if isinstance(finding, Mapping)
            and str(finding.get("severity", "")).upper() in {"P0", "P1"}
        ]
        # Critic 的自然语言 verdict 不是授权边界。只要结构化 findings 中仍有
        # P0/P1，内核就按 MAJOR 处理，防止 “APPROVE + P1” 绕过修复循环。
        effective_verdict = (
            "MAJOR"
            if verdict == "APPROVE" and blocking_findings
            else verdict
        )
        common: dict[str, Any] = {
            "collect_token_usage": True,
            "offload_stage": self.stage,
        }
        progress_event = transition_event(
            LoopEventType.CRITIC_PROGRESS_RECORDED,
            thread_id=context.thread_id,
            sequence=context.event_sequence,
            payload={"verdict": effective_verdict},
        )
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
        if effective_verdict == "APPROVE":
            changes = {
                "majors_in_a_row": 0,
                "total_majors": total,
                "open_findings": [],
                "repair_cycle_count": 0,
                "unchanged_finding_streak": 0,
                "last_finding_fingerprint": "",
                "batch_changed_files": [],
            }
            target: StageName = (
                "developer"
                if bool(context.extensions.get("has_more_batches"))
                else "component_verifier"
            )
            return TransitionDecision(
                events=(
                    progress_event,
                    channels_updated(
                        LoopEventType.CRITIC_STATE_UPDATED,
                        changes,
                        thread_id=context.thread_id,
                        sequence=context.event_sequence,
                    ),
                    _advanced(source=self.stage, target=target, context=context),
                ),
                next_stage=target,
                action_context=common,
            )

        in_a_row += 1
        total += 1
        changes = {
            "majors_in_a_row": in_a_row,
            "total_majors": total,
            "critic_verdict": effective_verdict,
            "open_findings": blocking_findings,
        }
        allowed_raw = context.extensions.get("allowed_file_targets", ())
        allowed = {
            str(path) for path in allowed_raw
        } if isinstance(allowed_raw, (list, tuple, set, frozenset)) else set()
        requires_refine = any(
            isinstance(finding, Mapping)
            and (
                finding.get("kind") in {"plan_gap", "contract_gap"}
                or (
                    bool(allowed)
                    and isinstance(finding.get("file"), str)
                    and bool(finding.get("file"))
                    and finding.get("file") not in allowed
                )
            )
            for finding in blocking_findings
        )
        if requires_refine:
            common["refine_source"] = "critic"
            common["feedback"] = findings
            return TransitionDecision(
                events=(progress_event, channels_updated(
                    LoopEventType.CRITIC_STATE_UPDATED,
                    changes,
                    thread_id=context.thread_id,
                    sequence=context.event_sequence,
                )),
                next_stage="architect",
                action_context=common,
            )
        fingerprint = hashlib.sha256(
            json.dumps(
                blocking_findings,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        previous_fingerprint = str(state.get("last_finding_fingerprint", ""))
        unchanged_streak = (
            int(state.get("unchanged_finding_streak", 0)) + 1
            if fingerprint == previous_fingerprint
            else 1
        )
        repair_cycles = int(state.get("repair_cycle_count", 0)) + 1
        changes.update({
            "repair_cycle_count": repair_cycles,
            "unchanged_finding_streak": unchanged_streak,
            "last_finding_fingerprint": fingerprint,
        })
        max_repairs = int(context.extensions.get("max_repair_cycles", 6))
        max_stagnation = int(context.extensions.get("max_stagnation_cycles", 3))
        if unchanged_streak >= max_stagnation:
            common["terminal_action"] = {
                "verdict": "STAGNANT",
                "reason": f"相同 Finding 无证据增量: {unchanged_streak}",
            }
            return TransitionDecision(
                events=(progress_event, channels_updated(
                    LoopEventType.CRITIC_STATE_UPDATED,
                    changes,
                    thread_id=context.thread_id,
                    sequence=context.event_sequence,
                )),
                terminal=True,
                action_context=common,
            )
        if repair_cycles >= max_repairs:
            common["terminal_action"] = {
                "verdict": "REPAIR_CYCLE_LIMIT",
                "reason": f"局部修复预算耗尽: {repair_cycles}/{max_repairs}",
            }
            return TransitionDecision(
                events=(progress_event, channels_updated(
                    LoopEventType.CRITIC_STATE_UPDATED,
                    changes,
                    thread_id=context.thread_id,
                    sequence=context.event_sequence,
                )),
                terminal=True,
                action_context=common,
            )

        target = "developer"
        common["feedback"] = findings
        return TransitionDecision(
            events=(
                progress_event,
                transition_event(
                    LoopEventType.BATCH_CURSOR_ROLLED_BACK,
                    thread_id=context.thread_id,
                    sequence=context.event_sequence,
                ),
                channels_updated(
                    LoopEventType.CRITIC_STATE_UPDATED,
                    changes,
                    thread_id=context.thread_id,
                    sequence=context.event_sequence,
                ),
                _advanced(source=self.stage, target=target, context=context),
            ),
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
