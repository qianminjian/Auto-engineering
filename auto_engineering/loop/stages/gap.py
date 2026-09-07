"""Gap Scan、Gap Review 与 Research 的纯 StageHandler。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from auto_engineering.loop.debug_tracer import now_iso
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


def _supplement_projection(
    state: Mapping[str, Any],
    supplements: list[dict[str, Any]],
) -> str | None:
    """编译 Supplement 事实对应的唯一 EngineState channel。"""
    if not supplements:
        return None
    raw = state.get("design_supplements_json") or "{}"
    try:
        current = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        current = {}
    if not isinstance(current, dict):
        current = {}
    for supplement in supplements:
        gap = supplement.get("gap")
        if not isinstance(gap, Mapping):
            continue
        gap_id = gap.get("id")
        if not isinstance(gap_id, str) or not gap_id:
            continue
        current[gap_id] = {
            "gap_id": gap_id,
            "design_section_ref": gap.get("design_section_ref", ""),
            "content": supplement.get("content", ""),
            "source": supplement.get("source", ""),
            "source_tier": supplement.get("source_tier"),
            "confidence": supplement.get("confidence", "medium"),
            "created_at": supplement.get("created_at", ""),
        }
    return json.dumps(current, ensure_ascii=False)


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
        report = {
            "gaps": result.get("gaps", []),
            "scanned_sections": result.get("scanned_sections", 0),
            "has_blocking": result.get("has_blocking", False),
            "design_doc_digest": result.get("design_doc_digest", ""),
            "scan_coverage": result.get("scan_coverage", []),
        }
        gaps = report["gaps"]
        target: StageName = "gap_review" if gaps else "architect"
        return TransitionDecision(
            events=(
                channels_updated(
                    LoopEventType.GAP_STATE_UPDATED,
                    {"gap_report_json": json.dumps(report, ensure_ascii=False)},
                    thread_id=context.thread_id,
                    sequence=context.event_sequence,
                ),
                _advanced(source=self.stage, target=target, context=context),
            ),
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
        recorded = [
            dict(item)
            for item in state.get("pending_gap_decisions", [])
            if isinstance(item, Mapping)
        ]
        decision_policy = state.get("gap_decision_policy")
        normalized_decisions: list[dict[str, Any]] = []
        for raw_decision in decisions:
            if not isinstance(raw_decision, Mapping):
                continue
            decision = dict(raw_decision)
            gap_id = decision.get("gap_id")
            gap = by_id.get(gap_id)
            if gap is None:
                continue
            recommendation = gap.get("recommendation") or {}
            recommended_resolution = recommendation.get("resolution")
            decision["assistant_recommendation"] = recommended_resolution
            decision["recommendation_accepted"] = (
                str(decision.get("resolution", "")).lower()
                == str(recommended_resolution or "").lower()
            )
            decision["evidence_refs"] = list(gap.get("evidence") or [])
            normalized_decisions.append(decision)
            recorded = [
                item for item in recorded if item.get("gap_id") != gap_id
            ]
            recorded.append(decision)
            if decision.get("apply_to_remaining") == "recommendations":
                decision_policy = "remaining_recommendations"
        for decision in normalized_decisions:
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
                        "created_at": now_iso(),
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
        decision_changes: dict[str, Any] = {
            "pending_gap_decisions": recorded,
        }
        if decision_policy == "remaining_recommendations":
            decision_changes["gap_decision_policy"] = decision_policy
        supplement_projection = _supplement_projection(state, supplements)
        if supplement_projection is not None:
            decision_changes["design_supplements_json"] = supplement_projection
        return TransitionDecision(
            events=(
                channels_updated(
                    LoopEventType.SUPPLEMENT_STATE_UPDATED,
                    decision_changes,
                    thread_id=context.thread_id,
                    sequence=context.event_sequence,
                ),
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
                        "created_at": now_iso(),
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
        supplement_projection = _supplement_projection(state, supplements)
        return TransitionDecision(
            events=(
                *(
                    (channels_updated(
                        LoopEventType.SUPPLEMENT_STATE_UPDATED,
                        {"design_supplements_json": supplement_projection},
                        thread_id=context.thread_id,
                        sequence=context.event_sequence,
                    ),)
                    if supplement_projection is not None
                    else ()
                ),
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
