"""Phase 82 T442：设计决策账本与语义变更门禁。"""

from __future__ import annotations

import hashlib
import json

import pytest

from auto_engineering.loop.design_authority import DesignChangeRequest
from auto_engineering.loop.design_decision_ledger import (
    DecisionScope,
    DesignDecision,
    DesignDecisionError,
    DesignDecisionLedger,
)
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.tick_orchestrator import TickOrchestrator
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
            "source_ref": "gap-1",
            "proposed_change_sha256": "a" * 64,
        },
    )

    assert DesignDecisionLedger.project_approved_changes([event]) == {
        "approval-1": {
            "decision_id": "VC-ARCH-001", "status": "approved",
            "causation_id": "gate-action-1",
            "source_ref": "gap-1",
            "proposed_change_sha256": "a" * 64,
        }
    }


def test_legacy_approval_recovers_scope_key_from_issued_gate() -> None:
    change = {
        "source": "research",
        "source_ref": "gap-legacy",
        "requested_authority": "binding",
        "change_summary": "采用服务层",
        "affected_design_refs": ["§4.2", "§4.1"],
    }
    request = DesignChangeRequest.from_dict(change)
    change = {
        **change,
        "request_id": request.request_id,
        "proposed_change_sha256": request.proposed_change_sha256,
    }
    issued = LoopEvent.create(
        thread_id="thread-1", sequence=1,
        event_type=LoopEventType.ACTION_ISSUED,
        correlation_id="thread-1", causation_id="architect-result",
        payload={"action": {
            "action": "gate",
            "gate": {
                "id": f"design_change:{request.request_id}",
                "change": change,
            },
        }},
    )
    approved = LoopEvent.create(
        thread_id="thread-1", sequence=2,
        event_type=LoopEventType.GATE_RESOLVED,
        correlation_id="thread-1", causation_id="approval-result",
        payload={
            "gate_id": f"design_change:{request.request_id}",
            "resolution": "批准变更",
            "approval_id": "approval-legacy",
            "decision_id": request.request_id,
            "status": "approved",
            "source_ref": "gap-legacy",
            "proposed_change_sha256": request.proposed_change_sha256,
        },
    )
    expected_scope = request.authority_scope_key

    projected = DesignDecisionLedger.project_approved_changes([
        issued, approved,
    ])

    assert projected["approval-legacy"]["authority_scope_key"] == expected_scope


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


def test_design_intake_persists_source_bound_partial_ledger(tmp_path) -> None:
    design = tmp_path / "design" / "feature.md"
    design.parent.mkdir()
    design.write_text("# Feature\n\n任意自然语言设计。\n", encoding="utf-8")

    ledger = DesignDecisionLedger.ensure_intake(tmp_path, design)

    persisted = json.loads(
        (tmp_path / ".ae-state" / "design-decision-ledger.json").read_text()
    )
    assert ledger.enforcement_status == "partial"
    assert ledger.source_sha256 == hashlib.sha256(design.read_bytes()).hexdigest()
    assert persisted["semantic_enforcement"] == "partial"
    assert persisted["source_ref"] == "design/feature.md"
    assert persisted["decisions"] == []


def test_design_intake_rejects_ledger_bound_to_other_source(tmp_path) -> None:
    design = tmp_path / "design.md"
    design.write_text("# Current", encoding="utf-8")
    state = tmp_path / ".ae-state"
    state.mkdir()
    (state / "design-decision-ledger.json").write_text(json.dumps({
        "schema_version": "1.0",
        "semantic_enforcement": "partial",
        "source_sha256": "0" * 64,
        "source_ref": "design.md",
        "decisions": [],
    }))

    with pytest.raises(DesignDecisionError, match="DESIGN_LEDGER_SOURCE_MISMATCH"):
        DesignDecisionLedger.ensure_intake(tmp_path, design)


def test_loop_init_creates_design_intake_ledger(tmp_path) -> None:
    design = tmp_path / "design.md"
    design.write_text("## 产品\n### 页面\n必须实现页面。\n", encoding="utf-8")
    orchestrator = TickOrchestrator(tmp_path)

    orchestrator.init("按设计实现", design_doc_path="design.md")

    ledger = DesignDecisionLedger.from_project(tmp_path)
    assert ledger.source_ref == "design.md"
    assert ledger.enforcement_status == "partial"


def test_design_intake_detects_source_drift_on_second_intake(tmp_path) -> None:
    design = tmp_path / "design.md"
    design.write_text("# V1", encoding="utf-8")
    DesignDecisionLedger.ensure_intake(tmp_path, design)
    design.write_text("# V2", encoding="utf-8")

    with pytest.raises(DesignDecisionError, match="DESIGN_LEDGER_SOURCE_MISMATCH"):
        DesignDecisionLedger.ensure_intake(tmp_path, design)


def test_partial_ledger_blocks_research_obligation_without_real_approval() -> None:
    ledger = DesignDecisionLedger(())

    with pytest.raises(
        DesignDecisionError,
        match="DESIGN_CHANGE_APPROVAL_REQUIRED: gap-1",
    ):
        ledger.validate_advisory_promotions(
            obligations=[{"source_ref": "gap-1"}],
            research_archive={"gap-1": {"recommended_design": "增加 BFF"}},
            approved_changes={},
        )

    ledger.validate_advisory_promotions(
        obligations=[{"source_ref": "gap-1"}],
        research_archive={"gap-1": {"recommended_design": "增加 BFF"}},
        approved_changes={
            "approval-1": {
                "status": "approved",
                "source_ref": "gap-1",
                "proposed_change_sha256": "a" * 64,
                "causation_id": "gate-action-1",
            }
        },
    )
