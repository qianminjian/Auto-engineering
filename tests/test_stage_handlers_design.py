"""Phase 54 T257：Architect 与 Critic Handler 决策矩阵。"""

from __future__ import annotations

from auto_engineering.loop.events import LoopEventType
from auto_engineering.loop.stages.base import TransitionContext
from auto_engineering.loop.stages.design import ArchitectHandler, CriticHandler
from auto_engineering.loop.tick_orchestrator import TickOrchestrator


def _context(**extensions: object) -> TransitionContext:
    return TransitionContext(
        thread_id="thread-1",
        tick=5,
        event_sequence=10,
        extensions=extensions,
    )


def _changes(decision) -> dict:
    return next(
        event.to_dict()["payload"]["changes"]
        for event in decision.events
        if event.event_type is LoopEventType.CRITIC_STATE_UPDATED
    )


def test_architect_rejects_empty_batch_plan() -> None:
    decision = ArchitectHandler().apply(
        {"batch_plan": []},
        {},
        _context(),
    )

    assert decision.next_stage is None
    assert decision.action_context["error"]["error_code"] == "EMPTY_BATCH_PLAN"


def test_architect_initializes_plan_before_advancing() -> None:
    decision = ArchitectHandler().apply(
        {"batch_plan": [{"batch_id": "B1", "tasks": []}]},
        {},
        _context(),
    )

    assert decision.next_stage == "developer"
    assert decision.events[0].event_type is (
        LoopEventType.ARCHITECTURE_PLAN_ACTIVATED
    )
    assert decision.lifecycle_effects.offload_stage == "architect"
    assert "offload_stage" not in decision.action_context


def test_critic_rejects_unknown_verdict() -> None:
    decision = CriticHandler().apply({}, {"verdict": "MINOR"}, _context())

    assert decision.next_stage is None
    assert decision.action_context["error"]["error_code"] == "INVALID_VERDICT"


def test_critic_major_stops_at_configured_repair_limit() -> None:
    decision = CriticHandler().apply(
        {"majors_in_a_row": 2, "total_majors": 2, "repair_cycle_count": 5},
        {"verdict": "MAJOR", "findings": [{"severity": "P1", "issue": "fix"}]},
        _context(max_repair_cycles=6, max_stagnation_cycles=3),
    )

    assert decision.terminal is True
    assert decision.terminal_action["verdict"] == "REPAIR_CYCLE_LIMIT"
    assert "terminal_action" not in decision.action_context
    assert _changes(decision)["majors_in_a_row"] == 3


def test_critic_unchanged_finding_stops_as_stagnant() -> None:
    finding = {"severity": "P1", "file": "src/a.ts", "issue": "same"}
    first = CriticHandler().apply(
        {"majors_in_a_row": 0, "total_majors": 0},
        {"verdict": "MAJOR", "findings": [finding]},
        _context(
            allowed_file_targets=["src/a.ts"],
            max_repair_cycles=6,
            max_stagnation_cycles=2,
        ),
    )
    patch = _changes(first)
    second = CriticHandler().apply(
        {"majors_in_a_row": 1, "total_majors": 1, **patch},
        {"verdict": "MAJOR", "findings": [finding]},
        _context(
            allowed_file_targets=["src/a.ts"],
            max_repair_cycles=6,
            max_stagnation_cycles=2,
        ),
    )

    assert second.terminal is True
    assert second.terminal_action["verdict"] == "STAGNANT"
    assert "terminal_action" not in second.action_context


def test_critic_major_rolls_back_batch_and_returns_findings() -> None:
    findings = [{"severity": "P1", "description": "fix"}]
    decision = CriticHandler().apply(
        {"majors_in_a_row": 0, "total_majors": 0},
        {"verdict": "MAJOR", "findings": findings},
        _context(max_majors_in_a_row=3, max_total_majors=4),
    )

    assert decision.next_stage == "developer"
    assert any(
        event.event_type is LoopEventType.WORK_REOPENED
        for event in decision.events
    )
    assert decision.action_context["feedback"] == findings


def test_critic_plan_gap_routes_to_architect_refine() -> None:
    findings = [{
        "severity": "P1",
        "kind": "plan_gap",
        "file": "server/routes/upload.ts",
        "issue": "计划缺少上传路由",
    }]

    decision = CriticHandler().apply(
        {"majors_in_a_row": 0, "total_majors": 0},
        {"verdict": "MAJOR", "findings": findings},
        _context(allowed_file_targets=["src/api/client.ts"]),
    )

    assert decision.next_stage == "architect"
    assert decision.refine_source == "critic"
    assert "refine_source" not in decision.action_context
    assert all(
        event.event_type is not LoopEventType.WORK_REOPENED
        for event in decision.events
    )


def test_critic_legacy_out_of_scope_finding_is_plan_gap() -> None:
    """旧 Result 没有 kind 时，以文件边界确定性识别计划缺口。"""
    decision = CriticHandler().apply(
        {"majors_in_a_row": 0, "total_majors": 0},
        {
            "verdict": "MAJOR",
            "findings": [{
                "severity": "P1",
                "file": "server/routes/upload.ts",
                "issue": "缺少服务端路由",
            }],
        },
        _context(allowed_file_targets=["src/api/client.ts"]),
    )

    assert decision.next_stage == "architect"
    assert decision.refine_source == "critic"
    assert "refine_source" not in decision.action_context


def test_critic_approve_with_blocking_finding_is_forced_to_repair() -> None:
    """Agent 的 APPROVE 不能覆盖内核对 P0/P1 的确定性阻断。"""
    findings = [{
        "severity": "P1",
        "file": "src/app.ts",
        "line": 12,
        "issue": "reset race",
    }]

    decision = CriticHandler().apply(
        {"majors_in_a_row": 0, "total_majors": 0},
        {"verdict": "APPROVE", "findings": findings},
        _context(max_majors_in_a_row=3, max_total_majors=4),
    )

    assert decision.next_stage == "developer"
    assert any(
        event.event_type is LoopEventType.CRITIC_PROGRESS_RECORDED
        for event in decision.events
    )
    assert any(
        event.event_type is LoopEventType.WORK_REOPENED
        for event in decision.events
    )
    assert decision.action_context["feedback"] == findings
    assert _changes(decision)["majors_in_a_row"] == 1
    assert _changes(decision)["open_findings"] == findings


def test_critic_approve_routes_by_remaining_batches() -> None:
    more = CriticHandler().apply(
        {"majors_in_a_row": 1, "total_majors": 2},
        {"verdict": "APPROVE"},
        _context(has_more_batches=True),
    )
    complete = CriticHandler().apply(
        {"majors_in_a_row": 1, "total_majors": 2},
        {"verdict": "APPROVE"},
        _context(has_more_batches=False),
    )

    assert more.next_stage == "developer"
    assert complete.next_stage == "component_verifier"
    assert _changes(more)["majors_in_a_row"] == 0
    assert _changes(more)["total_majors"] == 2


def test_assurance_bundle_fails_closed_when_audit_dimensions_are_incomplete() -> None:
    decision = CriticHandler().apply(
        {"majors_in_a_row": 0, "total_majors": 0},
        {
            "verdict": "APPROVE",
            "findings": [],
            "assurance_bundle": {
                "component_verification": {
                    "coverage_map": [], "missing_count": 0, "diverged_count": 0,
                },
                "system_audit": {
                    "dimensions": ["architecture"],
                    "findings": [], "p0_count": 0, "p1_count": 0, "p2_count": 0,
                    "missing_count": 0, "diverged_count": 0,
                },
            },
        },
        _context(has_more_batches=False),
    )

    assert decision.terminal is False
    assert decision.action_context["error"]["error_code"] == (
        "ASSURANCE_DIMENSIONS_INCOMPLETE"
    )


def test_assurance_bundle_recounts_findings_instead_of_trusting_worker() -> None:
    decision = CriticHandler().apply(
        {"majors_in_a_row": 0, "total_majors": 0},
        {
            "verdict": "APPROVE",
            "findings": [],
            "assurance_bundle": {
                "component_verification": {
                    "coverage_map": [], "missing_count": 0, "diverged_count": 0,
                },
                "system_audit": {
                    "dimensions": [
                        "architecture", "code_quality", "engineering",
                        "virtualization", "team_design_coverage",
                    ],
                    "findings": [{
                        "severity": "P1", "authority_class": "objective_defect",
                        "description": "缺陷",
                    }],
                    "p0_count": 0, "p1_count": 0, "p2_count": 0,
                    "missing_count": 0, "diverged_count": 0,
                },
            },
        },
        _context(has_more_batches=False),
    )

    assert decision.terminal is False
    assert decision.action_context["error"]["error_code"] == (
        "ASSURANCE_AUDIT_COUNT_MISMATCH"
    )


def test_orchestrator_dispatches_design_stages_via_registry(tmp_path) -> None:
    orchestrator = TickOrchestrator(tmp_path)

    assert orchestrator._stage_handlers.get("architect").stage == "architect"
    assert orchestrator._stage_handlers.get("critic").stage == "critic"
    assert not hasattr(orchestrator, "_after_architect")
    assert not hasattr(orchestrator, "_after_critic")
