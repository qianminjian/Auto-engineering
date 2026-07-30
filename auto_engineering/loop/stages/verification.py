"""五层验证阶段的纯路由 Handler。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from auto_engineering.gates.deep_audit import recount_findings
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.stages.base import (
    StageName,
    TransitionContext,
    TransitionDecision,
)


def _advanced(
    source: StageName,
    target: StageName,
    context: TransitionContext,
) -> tuple[LoopEvent, ...]:
    return (
        LoopEvent.create(
            thread_id=context.thread_id,
            sequence=context.event_sequence,
            event_type=LoopEventType.STAGE_ADVANCED,
            payload={"from": source, "to": target},
            correlation_id=context.thread_id,
        ),
    )


def _refine(
    source: StageName,
    state_patch: Mapping[str, Any],
    **action_context: Any,
) -> TransitionDecision:
    return TransitionDecision(
        action_context={
            "state_patch": dict(state_patch),
            "refine_source": source,
            **action_context,
        }
    )


class ComponentVerifierHandler:
    stage: StageName = "component_verifier"

    def apply(
        self,
        state: object,
        result: Mapping[str, Any],
        context: TransitionContext,
    ) -> TransitionDecision:
        missing = int(result.get("missing_count", 0))
        diverged = int(result.get("diverged_count", 0))
        progress = {"kind": self.stage, "missing": missing, "diverged": diverged}
        if missing or diverged:
            return _refine(
                self.stage,
                {"audit_findings": list(result.get("coverage_map", []))},
                progress_update=progress,
            )
        if context.extensions.get("has_more_components"):
            target: StageName = "developer"
        elif context.extensions.get("verification_layers") == "leaf":
            target = "system_deep_audit"
        else:
            target = "plate_deep_audit"
        return TransitionDecision(
            events=_advanced(self.stage, target, context),
            next_stage=target,
            action_context={
                "cursor_operation": "advance_component",
                "progress_update": progress,
            },
        )


class PlateDeepAuditHandler:
    stage: StageName = "plate_deep_audit"

    def apply(
        self,
        state: object,
        result: Mapping[str, Any],
        context: TransitionContext,
    ) -> TransitionDecision:
        deduped, p0, p1, p2 = recount_findings(result.get("findings", []))
        threshold = int(context.extensions.get("p1_threshold", 10))
        counts = (p0, p1, p2)
        progress = {"kind": self.stage, "counts": counts, "threshold": threshold}
        if p0 or p1:
            return _refine(
                self.stage,
                {"audit_findings": deduped, "open_findings": deduped},
                audit_counts=counts,
                progress_update=progress,
            )
        if context.extensions.get("has_more_plates"):
            target: StageName = "developer"
        elif context.extensions.get("verification_layers") == "plate":
            target = "system_deep_audit"
        else:
            target = "system_verifier"
        return TransitionDecision(
            events=_advanced(self.stage, target, context),
            next_stage=target,
            action_context={
                "state_patch": {"open_findings": []},
                "cursor_operation": "advance_plate",
                "audit_counts": counts,
                "progress_update": progress,
                "display_progress": not context.extensions.get("has_more_plates"),
            },
        )


class SystemVerifierHandler:
    stage: StageName = "system_verifier"

    def apply(
        self,
        state: object,
        result: Mapping[str, Any],
        context: TransitionContext,
    ) -> TransitionDecision:
        coverage = list(result.get("full_coverage_map", []))
        patch = {"coverage_map": coverage}
        if int(result.get("missing_count", 0)) or int(
            result.get("diverged_count", 0)
        ):
            patch["audit_findings"] = coverage
            return _refine(self.stage, patch)
        target: StageName = "system_deep_audit"
        return TransitionDecision(
            events=_advanced(self.stage, target, context),
            next_stage=target,
            action_context={"state_patch": patch, "display_progress": True},
        )


class SystemDeepAuditHandler:
    stage: StageName = "system_deep_audit"

    def apply(
        self,
        state: object,
        result: Mapping[str, Any],
        context: TransitionContext,
    ) -> TransitionDecision:
        if not isinstance(state, Mapping):
            raise TypeError("state 必须为 Mapping")
        deduped, p0, p1, p2 = recount_findings(result.get("findings", []))
        counts = (p0, p1, p2)
        patch: dict[str, Any] = {}
        if result.get("design_docs_stale"):
            patch["critic_feedback"] = (
                (state.get("critic_feedback") or "")
                + "\n[Design Doc Sync] "
                + str(result.get("design_doc_suggestions", ""))
            )
        if (
            p0
            or p1
            or int(result.get("missing_count", 0))
            or int(result.get("diverged_count", 0))
        ):
            patch["audit_findings"] = deduped
            patch["open_findings"] = deduped
            return _refine(
                self.stage,
                patch,
                audit_counts=counts,
            )
        patch["open_findings"] = []
        return TransitionDecision(
            terminal=True,
            action_context={
                "state_patch": patch,
                "audit_counts": counts,
                "display_progress": True,
                "convergence": {
                    "design_coverage_ok": True,
                    "system_deep_audit_ok": True,
                },
            },
        )


__all__ = [
    "ComponentVerifierHandler",
    "PlateDeepAuditHandler",
    "SystemDeepAuditHandler",
    "SystemVerifierHandler",
]
