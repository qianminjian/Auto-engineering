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
