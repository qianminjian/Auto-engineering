"""五层验证阶段的纯路由 Handler。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from auto_engineering.gates.deep_audit import recount_findings
from auto_engineering.loop.domain_events import channels_updated, transition_event
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.stages.base import (
    LifecycleEffects,
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
    changes: Mapping[str, Any],
    context: TransitionContext,
    audit_counts: tuple[int, int, int] | None = None,
    progress_update: Mapping[str, Any] | None = None,
    **action_context: Any,
) -> TransitionDecision:
    return TransitionDecision(
        events=(channels_updated(
            LoopEventType.VERIFICATION_STATE_UPDATED,
            changes,
            thread_id=context.thread_id,
            sequence=context.event_sequence,
        ),),
        refine_source=source,
        audit_counts=audit_counts,
        action_context=action_context,
        lifecycle_effects=LifecycleEffects(
            verification_progress=progress_update,
        ),
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
                context,
                progress_update=progress,
            )
        if context.extensions.get("has_more_components"):
            target: StageName = "developer"
        elif context.extensions.get("verification_layers") == "leaf":
            target = "system_deep_audit"
        else:
            target = "plate_deep_audit"
        return TransitionDecision(
            events=(
                transition_event(
                    LoopEventType.COMPONENT_COMPLETED,
                    thread_id=context.thread_id,
                    sequence=context.event_sequence,
                    payload={
                        "component": context.extensions.get("completed_component")
                    },
                ),
                *_advanced(self.stage, target, context),
            ),
            next_stage=target,
            lifecycle_effects=LifecycleEffects(
                verification_progress=progress,
            ),
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
                context,
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
            events=(
                transition_event(
                    LoopEventType.PLATE_COMPLETED,
                    thread_id=context.thread_id,
                    sequence=context.event_sequence,
                    payload={"plate": context.extensions.get("completed_plate")},
                ),
                channels_updated(
                    LoopEventType.VERIFICATION_STATE_UPDATED,
                    {"open_findings": []},
                    thread_id=context.thread_id,
                    sequence=context.event_sequence,
                ),
                *_advanced(self.stage, target, context),
            ),
            next_stage=target,
            audit_counts=counts,
            display_progress=not context.extensions.get("has_more_plates"),
            lifecycle_effects=LifecycleEffects(
                verification_progress=progress,
            ),
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
            return _refine(self.stage, patch, context)
        target: StageName = "system_deep_audit"
        return TransitionDecision(
            events=(
                channels_updated(
                    LoopEventType.VERIFICATION_STATE_UPDATED,
                    patch,
                    thread_id=context.thread_id,
                    sequence=context.event_sequence,
                ),
                *_advanced(self.stage, target, context),
            ),
            next_stage=target,
            display_progress=True,
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
        blocking = [
            finding for finding in deduped
            if finding.get("authority_class", "objective_defect")
            in {"binding_violation", "objective_defect"}
        ]
        advisory = [finding for finding in deduped if finding not in blocking]
        counts = (p0, p1, p2)
        patch: dict[str, Any] = {}
        if advisory:
            patch["audit_findings"] = advisory
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
            patch["audit_findings"] = blocking
            patch["open_findings"] = blocking
            return _refine(
                self.stage,
                patch,
                context,
                audit_counts=counts,
            )
        patch["open_findings"] = []
        return TransitionDecision(
            events=(channels_updated(
                LoopEventType.VERIFICATION_STATE_UPDATED,
                patch,
                thread_id=context.thread_id,
                sequence=context.event_sequence,
            ),),
            terminal=True,
            audit_counts=counts,
            display_progress=True,
            convergence={
                "design_coverage_ok": True,
                "system_deep_audit_ok": True,
            },
        )


__all__ = [
    "ComponentVerifierHandler",
    "PlateDeepAuditHandler",
    "SystemDeepAuditHandler",
    "SystemVerifierHandler",
]
