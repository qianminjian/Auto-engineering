"""v5.8 T323：状态锚点与信息性摘要隔离。"""

from __future__ import annotations

from auto_engineering.loop.context_authority import informational_drift
from auto_engineering.loop.tick_orchestrator import TickOrchestrator


def test_conflicting_summary_reports_drift_without_mutating_projection() -> None:
    projection = {"stage": "developer", "tick": 8, "active_batch_id": "B2"}
    summary = {"stage": "done", "tick": 99, "active_batch_id": "B1"}

    before = dict(projection)
    drift = informational_drift(
        projection=projection,
        informational=summary,
        source="session_summary",
    )

    assert projection == before
    assert {item["field"] for item in drift} == {
        "stage", "tick", "active_batch_id",
    }
    assert all(item["authority"] == "informational" for item in drift)


def test_duplicate_or_irrelevant_summary_does_not_create_false_drift() -> None:
    projection = {"stage": "critic", "tick": 10}

    assert informational_drift(
        projection=projection,
        informational={"stage": "critic", "tick": 10, "notes": ["x", "x"]},
        source="recap",
    ) == []


def test_orchestrator_keeps_stage_when_summary_claims_done(tmp_path) -> None:
    orchestrator = TickOrchestrator(project_root=tmp_path)
    orchestrator.init("实现功能")
    orchestrator._state.session_summary = {
        "stage": "done",
        "tick": 999,
    }

    action = orchestrator.build_action()

    assert action["action"] == "architect"
    assert action["stage"] == "architect"
    drift = action["extensions"]["informational_drift"]
    assert {item["field"] for item in drift} == {"stage", "tick"}
