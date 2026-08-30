"""Phase 54 T255：Gap/Research Handler v5.6 轨迹等价。"""

from __future__ import annotations

import json

from auto_engineering.loop.events import LoopEventType
from auto_engineering.loop.stages.base import TransitionContext
from auto_engineering.loop.stages.gap import (
    GapReviewHandler,
    GapScanHandler,
    ResearchHandler,
)
from auto_engineering.loop.tick_orchestrator import TickOrchestrator


def _context() -> TransitionContext:
    return TransitionContext(thread_id="thread-1", tick=3, event_sequence=7)


def _changes(decision) -> dict:
    event = next(
        item
        for item in decision.events
        if item.event_type is LoopEventType.GAP_STATE_UPDATED
    )
    return event.to_dict()["payload"]["changes"]


def test_gap_scan_routes_by_gap_presence_and_emits_stage_advance() -> None:
    state = {
        "gap_report_json": json.dumps(
            {"gaps": [{"id": "G1", "design_section_ref": "§1"}]}
        )
    }

    decision = GapScanHandler().apply(state, {}, _context())

    assert decision.next_stage == "gap_review"
    assert decision.events[0].event_type is LoopEventType.STAGE_ADVANCED
    assert decision.events[0].sequence == 7
    assert decision.events[0].to_dict()["payload"]["to"] == "gap_review"
    assert decision.lifecycle_effects.fuzzy_sections == ("§1",)
    assert "fuzzy_sections" not in decision.action_context


def test_gap_scan_without_gaps_routes_to_architect() -> None:
    state = {"gap_report_json": json.dumps({"gaps": []})}

    assert GapScanHandler().apply(state, {}, _context()).next_stage == "architect"


def test_gap_review_normalizes_resolution_and_queues_research() -> None:
    report = {
        "gaps": [{"id": "G1", "grade": "module"}],
        "has_blocking": True,
    }
    state = {
        "gap_report_json": json.dumps(report),
        "pending_gap_decisions": [
            {"gap_id": "G1", "resolution": "Defer+Research", "user_note": "查资料"}
        ],
        "research_archive": {},
    }

    decision = GapReviewHandler().apply(state, {}, _context())
    patch = _changes(decision)

    assert decision.next_stage == "research"
    assert patch["pending_research_ids"] == ["G1"]
    assert json.loads(patch["gap_report_json"])["gaps"][0]["resolution"] == (
        "defer_research"
    )
    assert decision.lifecycle_effects.pause_stages == ("architect",)
    assert "pause_stages" not in decision.action_context


def test_gap_review_fill_requests_supplement_without_mutating_input() -> None:
    report = {"gaps": [{"id": "G1", "design_section_ref": "§1"}]}
    state = {
        "gap_report_json": json.dumps(report),
        "pending_gap_decisions": [
            {
                "gap_id": "G1",
                "resolution": "Fill",
                "fill_content": "明确设计",
            }
        ],
        "research_archive": {"G1": {"findings": "old"}},
    }

    decision = GapReviewHandler().apply(state, {}, _context())

    assert decision.next_stage == "architect"
    assert decision.lifecycle_effects.supplements[0]["content"] == "明确设计"
    assert "supplements" not in decision.action_context
    assert _changes(decision)["research_archive"] == {}
    assert json.loads(state["gap_report_json"]) == report


def test_research_success_injects_supplement_and_advances() -> None:
    report = {"gaps": [{"id": "G1", "resolution": "research"}]}
    state = {
        "gap_report_json": json.dumps(report),
        "pending_research_ids": ["G1"],
        "research_archive": {},
    }
    result = {
        "recommended_design": "采用明确协议",
        "source_tier": "tier0",
        "confidence": "high",
        "search_status": "used",
    }

    decision = ResearchHandler().apply(state, result, _context())

    assert decision.next_stage == "gap_review"
    assert decision.lifecycle_effects.supplements[0]["source"] == "research_agent"
    assert "supplements" not in decision.action_context
    assert _changes(decision)["pending_research_ids"] == []


def test_research_success_returns_to_same_gap_for_user_review() -> None:
    """Research 结论必须先回到原 Gap Review，不能绕过用户决策。"""
    report = {
        "gaps": [
            {"id": "G1", "resolution": "research"},
            {"id": "G2", "resolution": ""},
        ]
    }
    state = {
        "gap_report_json": json.dumps(report),
        "pending_research_ids": ["G1"],
        "research_archive": {},
    }

    decision = ResearchHandler().apply(
        state,
        {
            "recommended_design": "采用明确协议",
            "source_tier": "tier0",
            "confidence": "high",
            "search_status": "used",
        },
        _context(),
    )

    assert decision.next_stage == "gap_review"
    assert json.loads(_changes(decision)["gap_report_json"])["gaps"][0][
        "resolution"
    ] == "research"


def test_research_failure_returns_to_review_with_evidence() -> None:
    report = {"gaps": [{"id": "G1", "resolution": "research"}]}
    result = {"search_status": "unavailable", "search_error": "no web"}
    state = {
        "gap_report_json": json.dumps(report),
        "pending_research_ids": ["G1"],
        "research_archive": {},
    }

    decision = ResearchHandler().apply(state, result, _context())
    patch = _changes(decision)

    assert decision.next_stage == "gap_review"
    assert patch["research_archive"]["G1"] == result
    assert json.loads(patch["gap_report_json"])["gaps"][0]["resolution"] == (
        "defer_research"
    )


def test_orchestrator_dispatches_gap_stages_through_registry(
    tmp_path,
    monkeypatch,
) -> None:
    orchestrator = TickOrchestrator(tmp_path)
    orchestrator.init("迁移 Gap Handler")
    orchestrator._state.current_stage = "gap_scan"
    orchestrator._state.gap_report_json = json.dumps({"gaps": []})
    monkeypatch.setattr(
        orchestrator,
        "build_action",
        lambda **kwargs: {"stage": orchestrator._state.current_stage},
    )

    action = orchestrator._after_tick({})

    assert action["stage"] == "architect"
    assert orchestrator._stage_handlers.get("gap_scan").stage == "gap_scan"
    assert not hasattr(orchestrator, "_after_gap_scan")
    assert not hasattr(orchestrator, "_after_gap_review")
    assert not hasattr(orchestrator, "_after_research")
