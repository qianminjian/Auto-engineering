"""Gap Scan、Gap Review 与 Research 的纯 StageHandler。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from auto_engineering.loop.domain_events import channels_updated
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.stages.base import (
    LifecycleEffects,
    StageName,
    TransitionContext,
    TransitionDecision,
)


def _report(state: Mapping[str, Any]) -> dict[str, Any]:
    raw = state.get("gap_report_json") or '{"gaps": []}'
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("gap_report_json 必须是 JSON object")
    return deepcopy(parsed)


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


class GapScanHandler:
    stage: StageName = "gap_scan"

    def apply(
        self,
        state: object,
        result: Mapping[str, Any],
        context: TransitionContext,
    ) -> TransitionDecision:
        if not isinstance(state, Mapping):
            raise TypeError("state 必须为 Mapping")
        gaps = _report(state).get("gaps", [])
        target: StageName = "gap_review" if gaps else "architect"
        return TransitionDecision(
            events=(_advanced(source=self.stage, target=target, context=context),),
            next_stage=target,
            lifecycle_effects=LifecycleEffects(
                fuzzy_sections=tuple(
                    gap["design_section_ref"]
                    for gap in gaps
                    if gap.get("design_section_ref")
                ),
            ),
        )


class GapReviewHandler:
    stage: StageName = "gap_review"

    def apply(
        self,
        state: object,
        result: Mapping[str, Any],
        context: TransitionContext,
    ) -> TransitionDecision:
        if not isinstance(state, Mapping):
            raise TypeError("state 必须为 Mapping")
        report = _report(state)
        by_id = {gap["id"]: gap for gap in report.get("gaps", [])}
        archive = deepcopy(dict(state.get("research_archive") or {}))
        pending: list[str] = []
        supplements: list[dict[str, Any]] = []
        submitted = result.get("decision")
        decisions = (
            [submitted]
            if isinstance(submitted, Mapping)
            else list(
                result.get("decisions")
                or state.get("pending_gap_decisions")
                or []
            )
        )
        for decision in decisions:
            gap_id = decision.get("gap_id")
            gap = by_id.get(gap_id)
            if gap is None:
                continue
            resolution = (
                (decision.get("resolution") or "")
                .strip()
                .lower()
                .replace(" ", "")
                .replace("+", "_")
            )
            already_researched = gap_id in archive
            gap["resolution"] = resolution
            gap["user_note"] = decision.get("user_note")
            if resolution == "fill":
                supplements.append(
                    {
                        "gap": deepcopy(gap),
                        "content": decision.get("fill_content", ""),
                        "source": "user",
                        "source_tier": None,
                        "confidence": "high",
                    }
                )
                archive.pop(gap_id, None)
            elif resolution in {"research", "defer_research"}:
                if already_researched:
                    gap["resolution"] = "defer"
                else:
                    pending.append(gap["id"])
        unresolved = [
            gap for gap in report.get("gaps", [])
            if gap.get("resolution") not in {"fill", "defer"}
        ]
        target: StageName = (
            "research" if pending
            else "gap_review" if unresolved
            else "architect"
        )
        patch = {
            "gap_report_json": json.dumps(report, ensure_ascii=False),
            "pending_research_ids": pending,
            "research_archive": archive,
        }
        return TransitionDecision(
            events=(
                channels_updated(
                    LoopEventType.GAP_STATE_UPDATED,
                    patch,
                    thread_id=context.thread_id,
                    sequence=context.event_sequence,
                ),
                *(
                    (_advanced(
                        source=self.stage,
                        target=target,
                        context=context,
                    ),)
                    if target != self.stage else ()
                ),
            ),
            next_stage=target,
            advance_stage=target != self.stage,
            lifecycle_effects=LifecycleEffects(
                supplements=tuple(supplements),
                pause_stages=("architect",) if report.get("has_blocking") else (),
            ),
        )


class ResearchHandler:
    stage: StageName = "research"

    def apply(
        self,
        state: object,
        result: Mapping[str, Any],
        context: TransitionContext,
    ) -> TransitionDecision:
        if not isinstance(state, Mapping):
            raise TypeError("state 必须为 Mapping")
        report = _report(state)
        pending = list(state.get("pending_research_ids") or [])
        archive = deepcopy(dict(state.get("research_archive") or {}))
        supplements: list[dict[str, Any]] = []
        if not pending:
            target: StageName = "architect"
            patch: dict[str, Any] = {}
        else:
            current_id = pending.pop(0)
            by_id = {gap["id"]: gap for gap in report.get("gaps", [])}
            gap = by_id.get(current_id, {})
            archive[current_id] = dict(result)
            search_failed = result.get("search_status", "not_needed") in {
                "unavailable",
                "failed",
            }
            if search_failed:
                gap["resolution"] = "defer_research"
            elif gap.get("resolution") == "research":
                supplements.append(
                    {
                        "gap": deepcopy(gap),
                        "content": result.get("recommended_design", ""),
                        "source": "research_agent",
                        "source_tier": result.get("source_tier"),
                        "confidence": result.get("confidence", "medium"),
                    }
                )
            patch = {
                "gap_report_json": json.dumps(report, ensure_ascii=False),
                "pending_research_ids": pending,
                "research_archive": archive,
            }
            if pending:
                target = "research"
            elif gap.get("resolution") == "research":
                # Research only supplies evidence. The original gap remains
                # unresolved until the user explicitly accepts Fill/Defer in
                # the same Gap Review item.
                target = "gap_review"
            elif any(
                gap_item.get("resolution") == "defer_research"
                and gap_item["id"] in archive
                for gap_item in report.get("gaps", [])
            ):
                target = "gap_review"
            else:
                target = "architect"
        return TransitionDecision(
            events=(
                *(
                    (channels_updated(
                        LoopEventType.GAP_STATE_UPDATED,
                        patch,
                        thread_id=context.thread_id,
                        sequence=context.event_sequence,
                    ),)
                    if patch
                    else ()
                ),
                _advanced(
                    source=self.stage,
                    target=target,
                    context=context,
                ),
            ),
            next_stage=target,
            lifecycle_effects=LifecycleEffects(supplements=tuple(supplements)),
        )


__all__ = ["GapReviewHandler", "GapScanHandler", "ResearchHandler"]
