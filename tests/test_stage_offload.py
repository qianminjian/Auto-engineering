"""Phase 80 T409：Stage offload 实现体脱离兼容 façade。"""

from __future__ import annotations

from auto_engineering.context.offloading import ContextOffloader
from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.state import EngineState
from auto_engineering.loop.stage_offload import StageOffloadService


def test_developer_offload_contains_batch_and_test_evidence(tmp_path) -> None:
    state = EngineState(thread_id="thread-1")
    state.tick = 8
    state.round = 3
    state.files_changed = ["src/core.py"]
    state.test_results = {"passed": 2, "failed": 1, "errors": 0}
    state.gate_results = {"test": {"passed": False}}
    batch_state = BatchState.from_batch_plan([
        {
            "batch_id": "B1",
            "component": "Core",
            "design_section": "§1",
            "tasks": [],
        }
    ])
    offloader = ContextOffloader(tmp_path / "offload")
    service = StageOffloadService(offloader=offloader)

    cached = service.offload(
        "developer",
        state=state,
        batch_state=batch_state,
        cached_summary=None,
    )

    artifact = offloader.load_summary("developer")
    assert cached is None
    assert artifact is not None
    assert "2/3 tests passed" in artifact.summary
    assert artifact.files_changed == ["src/core.py"]
    assert artifact.gate_results["test"]["passed"] is False
