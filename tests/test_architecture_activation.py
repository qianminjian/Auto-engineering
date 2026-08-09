"""Phase 80 T409：Architecture 激活实现体脱离兼容 façade。"""

from __future__ import annotations

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.architecture_activation import ArchitectureActivationService
from auto_engineering.loop.events import LoopEventType


def test_activation_materializes_execution_structures(tmp_path) -> None:
    state = EngineState(thread_id="thread-1", requirement="实现核心协议")
    state.batch_plan = [{
        "batch_id": "B1",
        "component": "Core",
        "design_section": "§1",
        "tasks": [{
            "id": "T1",
            "description": "实现协议",
            "file_targets": ["src/core.py"],
        }],
    }]
    emitted: list[tuple[LoopEventType, dict]] = []

    result = ArchitectureActivationService(tmp_path).activate(
        state=state,
        design_doc=None,
        batch_state=None,
        progress_tree=None,
        verification_layers=None,
        emit=lambda event_type, payload: emitted.append((event_type, payload)),
    )

    assert result.batch_state.current_batch_id() == "B1"
    assert result.plan is not None
    assert result.progress_tree is not None
    assert state.architecture_baseline["batch_plan"][0]["batch_id"] == "B1"
    assert emitted[0][0] is LoopEventType.ARCHITECTURE_BASELINE_ACCEPTED
