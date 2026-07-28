"""Phase 54 T256：五层验证 Handler 决策矩阵。"""

from __future__ import annotations

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


def test_component_gap_requests_refine() -> None:
    result = {"missing_count": 1, "coverage_map": [{"item": "x"}]}

    decision = ComponentVerifierHandler().apply({}, result, _context())

    assert decision.action_context["refine_source"] == "component_verifier"
    assert decision.action_context["state_patch"]["audit_findings"] == [
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
    assert more.action_context["cursor_operation"] == "advance_component"
    assert leaf.next_stage == "system_deep_audit"


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

    assert decision.action_context["refine_source"] == "plate_deep_audit"
    assert len(decision.action_context["state_patch"]["audit_findings"]) == 1
    assert decision.action_context["audit_counts"] == (1, 0, 0)


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
    assert more.action_context["cursor_operation"] == "advance_plate"
    assert cropped.next_stage == "system_deep_audit"


def test_system_verifier_refines_or_advances_to_deep_audit() -> None:
    failed = SystemVerifierHandler().apply(
        {},
        {"missing_count": 2, "full_coverage_map": [{"item": "x"}]},
        _context(),
    )
    passed = SystemVerifierHandler().apply({}, {}, _context())

    assert failed.action_context["refine_source"] == "system_verifier"
    assert passed.next_stage == "system_deep_audit"
    assert passed.action_context["display_progress"] is True


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
        decision.action_context["state_patch"]["critic_feedback"]
    )
    assert decision.terminal is True
    assert decision.action_context["convergence"] == {
        "design_coverage_ok": True,
        "system_deep_audit_ok": True,
    }


def test_system_deep_audit_coverage_gap_requests_refine() -> None:
    decision = SystemDeepAuditHandler().apply(
        {},
        {"missing_count": 1},
        _context(p1_threshold=10),
    )

    assert decision.action_context["refine_source"] == "system_deep_audit"


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
