"""Critic Assurance 结果的纯校验与阶段转移。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from auto_engineering.gates.deep_audit import recount_findings
from auto_engineering.loop.domain_events import channels_updated, transition_event
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.stages.base import (
    LifecycleEffects,
    TransitionContext,
    TransitionDecision,
)


def apply_assurance_bundle(
    *,
    assurance: Mapping[str, Any],
    context: TransitionContext,
    progress_event: LoopEvent,
    critic_changes: Mapping[str, Any],
    lifecycle_effects: LifecycleEffects,
) -> TransitionDecision:
    """重计 Assurance 事实并生成 Critic 的唯一转移决策。"""

    component = assurance.get("component_verification")
    audit = assurance.get("system_audit")
    if not isinstance(component, Mapping) or not isinstance(audit, Mapping):
        return TransitionDecision(action_context={"error": {
            "error_code": "ASSURANCE_BUNDLE_INVALID",
            "message": "assurance bundle 缺少组件覆盖或系统审计分区",
        }})
    coverage = component.get("coverage_map")
    findings = audit.get("findings")
    if not isinstance(coverage, list) or not isinstance(findings, list):
        return TransitionDecision(action_context={"error": {
            "error_code": "ASSURANCE_BUNDLE_INVALID",
            "message": (
                "assurance bundle 的 component_verification.coverage_map 和 "
                "system_audit.findings 必须为数组；system_audit.dimensions 只能是 "
                "固定五个字符串"
            ),
            "violations": [
                path for path, value in (
                    ("component_verification.coverage_map", coverage),
                    ("system_audit.findings", findings),
                )
                if not isinstance(value, list)
            ],
            "suggestion": (
                "请按 expected_format 的 JSON 示例提交；不要把 findings 放入 "
                "system_audit.dimensions 的元素中。"
            ),
        }})
    required_dimensions = {
        "architecture",
        "code_quality",
        "engineering",
        "virtualization",
        "team_design_coverage",
    }
    dimensions = audit.get("dimensions")
    if not isinstance(dimensions, list) or set(dimensions) != required_dimensions:
        return TransitionDecision(action_context={"error": {
            "error_code": "ASSURANCE_DIMENSIONS_INCOMPLETE",
            "message": "Assurance Worker 未完整覆盖固定五维系统审计",
        }})
    expected_component = context.extensions.get("assurance_component")
    actual_component = component.get("component")
    if (
        not isinstance(expected_component, str)
        or not expected_component
        or actual_component != expected_component
    ):
        return TransitionDecision(action_context={"error": {
            "error_code": "ASSURANCE_COMPONENT_IDENTITY_MISMATCH",
            "message": "Assurance 组件身份必须与当前设计组件一致",
        }})
    missing = sum(
        item.get("status") == "MISSING"
        for item in coverage
        if isinstance(item, Mapping)
    )
    diverged = sum(
        item.get("status") == "DIVERGED"
        for item in coverage
        if isinstance(item, Mapping)
    )
    if (
        component.get("missing_count") != missing
        or component.get("diverged_count") != diverged
    ):
        return TransitionDecision(action_context={"error": {
            "error_code": "ASSURANCE_COVERAGE_COUNT_MISMATCH",
            "message": "Assurance 覆盖计数与 coverage_map 不一致",
        }})
    deduped, p0, p1, p2 = recount_findings(findings)
    if (
        audit.get("p0_count") != p0
        or audit.get("p1_count") != p1
        or audit.get("p2_count") != p2
    ):
        return TransitionDecision(action_context={"error": {
            "error_code": "ASSURANCE_AUDIT_COUNT_MISMATCH",
            "message": "Assurance 审计计数与 findings 不一致",
        }})
    common_events = (
        progress_event,
        channels_updated(
            LoopEventType.CRITIC_STATE_UPDATED,
            dict(critic_changes),
            thread_id=context.thread_id,
            sequence=context.event_sequence,
        ),
    )
    if missing or diverged:
        return TransitionDecision(
            events=(*common_events, channels_updated(
                LoopEventType.VERIFICATION_STATE_UPDATED,
                {"coverage_map": coverage, "audit_findings": coverage},
                thread_id=context.thread_id,
                sequence=context.event_sequence,
            )),
            next_stage="architect",
            refine_source="component_verifier",
            lifecycle_effects=lifecycle_effects,
        )
    blocking = [
        item for item in deduped
        if item.get("authority_class", "objective_defect")
        in {"binding_violation", "objective_defect"}
        and str(item.get("severity", "")).upper() in {"P0", "P1"}
    ]
    if blocking or int(audit.get("missing_count", 0)) or int(
        audit.get("diverged_count", 0)
    ):
        return TransitionDecision(
            events=(*common_events, channels_updated(
                LoopEventType.VERIFICATION_STATE_UPDATED,
                {"coverage_map": coverage, "open_findings": blocking},
                thread_id=context.thread_id,
                sequence=context.event_sequence,
            )),
            next_stage="architect",
            refine_source="system_deep_audit",
            audit_counts=(p0, p1, p2),
            lifecycle_effects=lifecycle_effects,
        )
    advisory = [item for item in deduped if item not in blocking]
    component_name = str(component.get("component") or "")
    return TransitionDecision(
        events=(
            *common_events,
            transition_event(
                LoopEventType.COMPONENT_COMPLETED,
                thread_id=context.thread_id,
                sequence=context.event_sequence,
                payload={"component": component_name},
            ),
            channels_updated(
                LoopEventType.VERIFICATION_STATE_UPDATED,
                {
                    "coverage_map": coverage,
                    "audit_findings": advisory,
                    "open_findings": [],
                },
                thread_id=context.thread_id,
                sequence=context.event_sequence,
            ),
        ),
        terminal=True,
        audit_counts=(p0, p1, p2),
        display_progress=True,
        convergence={
            "design_coverage_ok": True,
            "system_deep_audit_ok": True,
        },
        lifecycle_effects=LifecycleEffects(
            collect_token_usage=lifecycle_effects.collect_token_usage,
            offload_stage=lifecycle_effects.offload_stage,
            verification_progress={
                "kind": "component_verifier",
                "missing": 0,
                "diverged": 0,
            },
        ),
    )


__all__ = ["apply_assurance_bundle"]
