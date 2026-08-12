"""Phase 82 T442：设计决策账本与语义变更门禁。"""

from __future__ import annotations

import pytest

from auto_engineering.loop.design_decision_ledger import (
    DecisionScope,
    DesignDecision,
    DesignDecisionError,
    DesignDecisionLedger,
)
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.prompts.architect_context import build_architect_research_context


def _ledger() -> DesignDecisionLedger:
    return DesignDecisionLedger((
        DesignDecision(
            decision_id="VC-ARCH-001",
            source_ref="design.md#4.1",
            scope=DecisionScope.CURRENT,
            statement="V1 使用纯前端 SPA",
            classification="binding",
            change_policy="explicit_user_approval",
            prohibited_promotions=("future_bff_to_v1_requirement",),
        ),
        DesignDecision(
            decision_id="VC-FUTURE-001",
            source_ref="design.md#13",
            scope=DecisionScope.FUTURE,
            statement="未来可迁移 BFF",
            classification="advisory",
            change_policy="explicit_user_approval",
        ),
    ))


def test_binding_decision_requires_impact_and_approval_for_change() -> None:
    with pytest.raises(DesignDecisionError, match="DECISION_IMPACT_MISSING"):
        _ledger().validate_impacts([], approved_changes={})

    with pytest.raises(DesignDecisionError, match="DESIGN_CHANGE_NOT_APPROVED"):
        _ledger().validate_impacts([
            {"decision_id": "VC-ARCH-001", "impact": "change"},
        ], approved_changes={})

    with pytest.raises(DesignDecisionError, match="DESIGN_CHANGE_NOT_APPROVED"):
        _ledger().validate_impacts([
            {
                "decision_id": "VC-ARCH-001",
                "impact": "change",
                "approved_change_id": "fake",
            },
        ], approved_changes={})

    _ledger().validate_impacts([
        {"decision_id": "VC-ARCH-001", "impact": "preserve"},
    ], approved_changes={})

    _ledger().validate_impacts([{
        "decision_id": "VC-ARCH-001",
        "impact": "change",
        "approved_change_id": "approval-1",
    }], approved_changes={
        "approval-1": {
            "decision_id": "VC-ARCH-001", "status": "approved",
            "causation_id": "gate-action-1",
        },
    })


def test_approval_projection_only_accepts_core_gate_event() -> None:
    event = LoopEvent.create(
        thread_id="thread-1", sequence=0,
        event_type=LoopEventType.GATE_RESOLVED,
        correlation_id="thread-1", causation_id="gate-action-1",
        payload={
            "gate_id": "design_change:VC-ARCH-001",
            "resolution": "批准变更", "approval_id": "approval-1",
            "decision_id": "VC-ARCH-001", "status": "approved",
        },
    )

    assert DesignDecisionLedger.project_approved_changes([event]) == {
        "approval-1": {
            "decision_id": "VC-ARCH-001", "status": "approved",
            "causation_id": "gate-action-1",
        }
    }


def test_advisory_change_also_requires_approval() -> None:
    ledger = DesignDecisionLedger((_ledger().decisions[1],))
    with pytest.raises(DesignDecisionError, match="DESIGN_CHANGE_NOT_APPROVED"):
        ledger.validate_impacts([
            {"decision_id": "VC-FUTURE-001", "impact": "change"}
        ], approved_changes={})


def test_future_decision_cannot_be_promoted_to_current_gap() -> None:
    with pytest.raises(DesignDecisionError, match="FUTURE_SCOPE_PROMOTION"):
        _ledger().validate_gap({
            "decision_id": "VC-FUTURE-001",
            "scope": "current",
            "blocking": True,
        })


def test_research_context_deduplicates_same_gap_and_content() -> None:
    entries = build_architect_research_context(
        '{"gap-1":{"source":"research_agent","content":"建议 BFF"}}',
        {"gap-1": {"recommended_design": "建议 BFF"}},
    )

    assert len(entries) == 1
    assert entries[0]["sources"] == "research_agent,research_archive"
    assert len(entries[0]["content_sha256"]) == 64


def test_empty_ledger_reports_partial_semantic_enforcement() -> None:
    assert DesignDecisionLedger(()).enforcement_status == "partial"
    assert _ledger().enforcement_status == "full"
