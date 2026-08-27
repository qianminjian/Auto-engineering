"""Phase 54 T256：五层验证 Handler 决策矩阵。"""

from __future__ import annotations

from auto_engineering.loop.events import LoopEventType
from auto_engineering.loop.stages.base import TransitionContext
from auto_engineering.loop.stages.verification import (
    ComponentVerifierHandler,
    PlateDeepAuditHandler,
    SystemDeepAuditHandler,
    SystemVerifierHandler,
)
from auto_engineering.loop.tick_orchestrator import TickOrchestrator


def _context(**extensions: object) -> TransitionContext:
    return TransitionContext(
        thread_id="thread-1",
        tick=4,
        event_sequence=9,
        extensions=extensions,
    )


def _changes(decision) -> dict:
    return next(
        event.to_dict()["payload"]["changes"]
        for event in decision.events
        if event.event_type is LoopEventType.VERIFICATION_STATE_UPDATED
    )


def test_component_gap_requests_refine() -> None:
    result = {"missing_count": 1, "coverage_map": [{"item": "x"}]}

    decision = ComponentVerifierHandler().apply({}, result, _context())

    assert decision.refine_source == "component_verifier"
    assert "refine_source" not in decision.action_context
    assert decision.lifecycle_effects.verification_progress["missing"] == 1
    assert "progress_update" not in decision.action_context
    assert _changes(decision)["audit_findings"] == [
        {"item": "x"}
    ]


def test_component_pass_routes_by_remaining_scope() -> None:
    more = ComponentVerifierHandler().apply(
        {},
        {"missing_count": 0, "diverged_count": 0},
        _context(has_more_components=True, verification_layers="full"),
    )
    leaf = ComponentVerifierHandler().apply(
        {},
        {},
        _context(has_more_components=False, verification_layers="leaf"),
    )

    assert more.next_stage == "developer"
    assert any(
        event.event_type is LoopEventType.COMPONENT_COMPLETED
        for event in more.events
    )
    assert leaf.next_stage == "system_deep_audit"


def test_component_pass_persists_coverage_for_event_replay() -> None:
    decision = ComponentVerifierHandler().apply(
        {},
        {
            "missing_count": 0,
            "diverged_count": 0,
            "coverage_map": [{"design_item": "B1-T1", "status": "IMPLEMENTED"}],
        },
        _context(has_more_components=False, verification_layers="leaf"),
    )

    assert _changes(decision)["coverage_map"] == [
        {"design_item": "B1-T1", "status": "IMPLEMENTED"}
    ]


def test_plate_audit_recounts_findings_and_requests_refine() -> None:
    finding = {
        "severity": "P0",
        "dimension": "security",
        "file": "a.py",
        "line": 1,
        "description": "unsafe",
    }
    decision = PlateDeepAuditHandler().apply(
        {},
        {"findings": [finding, finding]},
        _context(p1_threshold=10),
    )

    assert decision.refine_source == "plate_deep_audit"
    assert "refine_source" not in decision.action_context
    assert len(_changes(decision)["audit_findings"]) == 1
    assert decision.audit_counts == (1, 0, 0)
    assert "audit_counts" not in decision.action_context


def test_single_p1_cannot_pass_final_deep_audit() -> None:
    finding = {
        "severity": "P1",
        "dimension": "correctness",
        "file": "app.py",
        "line": 2,
        "description": "race",
    }

    decision = SystemDeepAuditHandler().apply(
        {},
        {"findings": [finding]},
        _context(p1_threshold=10),
    )

    assert decision.terminal is False
    assert decision.refine_source == "system_deep_audit"
    assert "refine_source" not in decision.action_context
    open_finding = _changes(decision)["open_findings"][0]
    assert open_finding["severity"] == "P1"
    assert open_finding["description"] == "race"


def test_aggregate_coverage_count_becomes_structured_refine_evidence() -> None:
    decision = SystemDeepAuditHandler().apply(
        {},
        {
            "findings": [],
            "missing_count": 2,
            "diverged_count": 1,
        },
        _context(),
    )

    findings = _changes(decision)["audit_findings"]
    assert decision.refine_source == "system_deep_audit"
    assert len(findings) == 1
    assert findings[0]["severity"] == "P1"
    assert findings[0]["dimension"] == "design_coverage"
    assert "missing=2" in findings[0]["description"]
    assert "diverged=1" in findings[0]["description"]


def test_out_of_scope_p1_is_audited_but_does_not_trigger_refine() -> None:
    finding = {
        "severity": "P1",
        "dimension": "virtualization",
        "file": "src/library.py",
        "line": 1,
        "description": "独立库函数没有运行时调用方",
        "authority_class": "out_of_scope",
    }

    decision = SystemDeepAuditHandler().apply(
        {},
        {"findings": [finding]},
        _context(p1_threshold=0),
    )

    assert decision.terminal is True
    assert decision.refine_source is None
    assert decision.audit_counts == (0, 0, 0)
    assert _changes(decision)["audit_findings"][0]["authority_class"] == "out_of_scope"


def test_plate_pass_routes_to_next_plate_or_cropped_layer() -> None:
    more = PlateDeepAuditHandler().apply(
        {},
        {},
        _context(has_more_plates=True, verification_layers="full", p1_threshold=10),
    )
    cropped = PlateDeepAuditHandler().apply(
        {},
        {},
        _context(has_more_plates=False, verification_layers="plate", p1_threshold=10),
    )

    assert more.next_stage == "developer"
    assert any(
        event.event_type is LoopEventType.PLATE_COMPLETED
        for event in more.events
    )
    assert cropped.next_stage == "system_deep_audit"


def test_system_verifier_refines_or_advances_to_deep_audit() -> None:
    failed = SystemVerifierHandler().apply(
        {},
        {"missing_count": 2, "full_coverage_map": [{"item": "x"}]},
        _context(),
    )
    passed = SystemVerifierHandler().apply({}, {}, _context())

    assert failed.refine_source == "system_verifier"
    assert "refine_source" not in failed.action_context
    assert passed.next_stage == "system_deep_audit"
    assert passed.display_progress is True
    assert "display_progress" not in passed.action_context


def test_system_deep_audit_preserves_stale_design_feedback() -> None:
    decision = SystemDeepAuditHandler().apply(
        {"critic_feedback": "existing"},
        {
            "design_docs_stale": True,
            "design_doc_suggestions": "同步接口章节",
        },
        _context(p1_threshold=10),
    )

    assert "同步接口章节" in (
        _changes(decision)["critic_feedback"]
    )
    assert decision.terminal is True
    assert decision.convergence == {
        "design_coverage_ok": True,
        "system_deep_audit_ok": True,
    }
    assert "convergence" not in decision.action_context


def test_system_deep_audit_coverage_gap_requests_refine() -> None:
    decision = SystemDeepAuditHandler().apply(
        {},
        {"missing_count": 1},
        _context(p1_threshold=10),
    )

    assert decision.refine_source == "system_deep_audit"
    assert "refine_source" not in decision.action_context


def test_orchestrator_dispatches_verification_stages_via_registry(
    tmp_path,
    monkeypatch,
) -> None:
    orchestrator = TickOrchestrator(tmp_path)
    orchestrator.init("迁移验证 Handler")
    orchestrator._state.current_stage = "system_verifier"
    monkeypatch.setattr(
        orchestrator,
        "build_action",
        lambda **kwargs: {"stage": orchestrator._state.current_stage},
    )
    monkeypatch.setattr(orchestrator, "_display_progress", lambda: None)

    action = orchestrator._after_tick(
        {"missing_count": 0, "diverged_count": 0, "full_coverage_map": []}
    )

    assert action["stage"] == "system_deep_audit"
    assert orchestrator._stage_handlers.get("system_verifier").stage == (
        "system_verifier"
    )
    for old_name in (
        "_after_component_verifier",
        "_after_plate_deep_audit",
        "_after_system_verifier",
        "_after_system_deep_audit",
    ):
        assert not hasattr(orchestrator, old_name)
