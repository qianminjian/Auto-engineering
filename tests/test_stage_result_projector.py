"""Phase 80 T409：Stage Result 投影脱离兼容 façade。"""

from __future__ import annotations

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.stage_result_projector import StageResultProjector


def test_projector_applies_architect_patch_and_developer_evidence() -> None:
    state = EngineState(thread_id="thread-1")
    projector = StageResultProjector()

    projector.apply(state, {
        "stage": "architect",
        "plan": "修复计划",
        "plan_patch": {"base_revision": 2, "add_batches": [{"batch_id": "B3"}]},
        "file_list": ["src/a.py"],
        "contracts": {"API": {"version": "1"}},
        "obligations": [{"id": "O1"}],
    })
    projector.apply(state, {
        "stage": "developer",
        "files_changed": ["src/a.py", "src/a.py"],
        "commit_hash": "abc123",
        "test_results": {"passed": 1},
        "red_evidence": [{"test": "fails first"}],
    })

    assert state.batch_plan[0]["batch_id"] == "B3"
    assert state._runtime_ctx["plan_patch_base_revision"] == 2
    assert state.batch_changed_files == ["src/a.py"]
    assert state.commit_hash == "abc123"
