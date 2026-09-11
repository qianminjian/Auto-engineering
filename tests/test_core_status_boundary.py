"""方案 A A004：CLI 通过 Core 的只读状态边界获取状态。"""

from __future__ import annotations

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.tick_orchestrator import TickOrchestrator


def test_status_snapshot_projects_state_without_exposing_orchestrator_internals(
    tmp_path,
) -> None:
    orchestrator = TickOrchestrator(project_root=tmp_path)
    orchestrator._state = EngineState(
        thread_id="thread-1",
        current_stage="architect",
        requirement="实现确定性治理",
    )
    orchestrator._active_action = {
        "action": "architect",
        "stage": "architect",
        "message_id": "action-1",
    }

    snapshot = orchestrator.status_snapshot()

    assert snapshot["thread_id"] == "thread-1"
    assert snapshot["current_stage"] == "architect"
    assert snapshot["active_action"]["message_id"] == "action-1"
    snapshot["active_action"]["message_id"] = "changed"
    assert orchestrator._active_action["message_id"] == "action-1"


def test_build_action_does_not_reread_static_ledger_each_tick(tmp_path, monkeypatch) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='ledger-boundary'\n", encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    orchestrator = TickOrchestrator(project_root=tmp_path)
    orchestrator.init("实现确定性治理")

    def fail_if_reread(_root):
        raise AssertionError("静态设计账本不应在每个 build_action 中重读")

    monkeypatch.setattr(
        "auto_engineering.loop.tick_orchestrator.DesignDecisionLedger.from_project",
        fail_if_reread,
    )

    action = orchestrator.build_action()

    assert action["stage"] == "architect"
