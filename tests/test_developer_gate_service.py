"""Phase 80 T409：Developer Gate 执行与分派脱离 façade。"""

from __future__ import annotations

from unittest.mock import Mock

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.developer_gate_service import (
    DeveloperGateService,
    StageGateDispatcher,
)


def test_dispatcher_runs_developer_or_forced_refresh() -> None:
    run = Mock()
    dispatcher = StageGateDispatcher()

    dispatcher.dispatch("critic", run)
    dispatcher.dispatch("developer", run)
    dispatcher.dispatch("developer", run, force=True)
    dispatcher.dispatch("critic", run, force=True)

    assert run.call_count == 2


def test_gate_service_updates_state_and_returns_duration() -> None:
    state = EngineState(thread_id="thread-1")
    state.current_stage = "developer"
    state.tick = 3
    state.files_changed = ["src/core.py"]
    runner = Mock()
    runner.run.return_value = ({"test": {"passed": True}}, 12.5)

    duration = DeveloperGateService(runner).run(
        state=state,
        batch_state=None,
        developer_snapshot=None,
    )

    assert duration == 12.5
    assert state.gate_results["test"]["passed"] is True
    runner.run.assert_called_once_with(
        ["src/core.py"],
        stage="developer",
        tick=3,
        contracts={},
    )


def test_gate_service_adds_task_aware_core_evidence() -> None:
    state = EngineState(thread_id="thread-1")
    state.current_stage = "developer"
    state.test_results = {"passed": 9, "failed": 0}
    runner = Mock()
    runner.run.return_value = (
        {"test": {"status": "fail", "passed": False, "message": "tests failed"}},
        1.0,
    )
    batch_state = Mock()
    batch_state.completed_batch_ids.return_value = set()
    batch_state.is_component_complete.return_value = False
    batch_state.current_batch_id.return_value = "B1"
    batch_state.current_batch.return_value = {
        "batch_id": "B1",
        "tasks": [{"id": "B1-T1", "kind": "implementation"}],
    }

    DeveloperGateService(runner).run(
        state=state,
        batch_state=batch_state,
        developer_snapshot=None,
    )

    assert state.gate_results["task_evidence"]["status"] == "fail"
    assert state.gate_results["task_evidence"]["reason_code"] == (
        "authoritative_test_required"
    )


def test_gate_service_persists_task_evidence_from_core_snapshot() -> None:
    state = EngineState(thread_id="thread-1")
    state.current_stage = "developer"
    runner = Mock()
    runner.run.return_value = (
        {
            "test": {
                "status": "pass",
                "passed": True,
                "selected_files": ["src/core.py"],
                "files_snapshot_sha": "sha256-value",
                "ran_at": "2026-08-10T00:00:00Z",
            }
        },
        1.0,
    )
    batch_state = Mock()
    batch_state.completed_batch_ids.return_value = set()
    batch_state.is_component_complete.return_value = False
    batch_state.current_batch_id.return_value = "B1"
    batch_state.current_batch.return_value = {
        "batch_id": "B1",
        "tasks": [
            {
                "id": "B1-T1",
                "kind": "implementation",
                "file_targets": ["src/core.py"],
            }
        ],
    }

    DeveloperGateService(runner).run(
        state=state,
        batch_state=batch_state,
        developer_snapshot=None,
    )

    assert state.task_verification_evidence["B1-T1"] == {
        "task_id": "B1-T1",
        "gate_passed": True,
        "evidence_kind": "core_test",
        "selected_files": ["src/core.py"],
        "files_snapshot_sha": "sha256-value",
        "ran_at": "2026-08-10T00:00:00Z",
    }
