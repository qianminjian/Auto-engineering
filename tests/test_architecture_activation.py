"""Phase 80 T409：Architecture 激活实现体脱离兼容 façade。"""

from __future__ import annotations

import pytest

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.design_doc import Component, DesignDoc, Plate
from auto_engineering.engine.progress_tree import ProgressTree
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


def test_activation_builds_baseline_from_projected_candidate(tmp_path) -> None:
    old_batch = {
        "batch_id": "B1",
        "component": "Core",
        "design_section": "§1",
        "tasks": [{
            "id": "B1-T1",
            "description": "实现旧任务",
            "file_targets": ["src/old.py"],
        }],
    }
    new_batch = {
        "batch_id": "B2",
        "component": "Core",
        "design_section": "§2",
        "tasks": [{
            "id": "B2-T1",
            "description": "实现新任务",
            "file_targets": ["src/new.py"],
        }],
    }
    state = EngineState(thread_id="thread-1", requirement="增量修复")
    state.plan_refine_count = 1
    state.batch_plan = [new_batch]
    state.architecture_baseline = {
        "batch_plan": [old_batch],
        "contracts": {"ExistingAPI": {"version": "1"}},
        "obligations": [{
            "id": "O1",
            "source_ref": "§1",
            "implementation_targets": ["B1-T1"],
            "verification_targets": ["V1"],
            "contract_refs": ["ExistingAPI"],
        }],
    }
    state._runtime_ctx["plan_patch_base_revision"] = 1
    state._runtime_ctx["architecture_candidate"] = {
        "plan": "增量修复",
        "batch_plan": [old_batch, new_batch],
        "contracts": {"ExistingAPI": {"version": "1"}},
        "obligations": state.architecture_baseline["obligations"],
    }

    result = ArchitectureActivationService(tmp_path).activate(
        state=state,
        design_doc=None,
        batch_state=None,
        progress_tree=None,
        verification_layers=None,
        emit=lambda _event_type, _payload: None,
    )

    assert [batch["batch_id"] for batch in result.batch_state.batch_plan] == [
        "B1",
        "B2",
    ]
    assert state.architecture_baseline["contracts"] == {
        "ExistingAPI": {"version": "1"},
    }
    assert state.architecture_baseline["obligations"][0]["id"] == "O1"


def test_plan_refine_recomputes_totals_and_preserves_completed_tasks(
    tmp_path,
) -> None:
    doc = DesignDoc(
        plates=[Plate(
            name="页面",
            design_section="§1",
            components=[Component(
                name="VoiceClone",
                design_section="§1.1",
                design_items=[],
            )],
        )],
        supplements={},
    )

    def batch(batch_id: str, count: int) -> dict:
        return {
            "batch_id": batch_id,
            "component": "VoiceClone",
            "design_section": "§1.1",
            "tasks": [
                {"id": f"{batch_id}-T{index}", "description": "实现", "file_targets": ["x.ts"]}
                for index in range(count)
            ],
        }

    old_batches = [batch("B1", 5), batch("B2", 5)]
    added_batches = [batch("B3", 2), batch("B4", 2)]
    batch_state = BatchState.from_design_doc(doc, old_batches)
    batch_state.current_plate_idx = len(batch_state.plates)
    progress = ProgressTree.from_design_doc(doc)
    progress.apply_batch_plan_totals(old_batches)
    component = progress.find_by_design_section("1.1")
    assert component is not None
    component.done_tasks = 10
    progress.recalculate_parents(component.id)
    state = EngineState(thread_id="thread-1", requirement="refine")
    state.plan_refine_count = 1
    state.batch_plan = added_batches
    state._runtime_ctx["plan_patch_base_revision"] = 1

    result = ArchitectureActivationService(tmp_path).activate(
        state=state,
        design_doc=doc,
        batch_state=batch_state,
        progress_tree=progress,
        verification_layers=None,
        emit=lambda _event_type, _payload: None,
    )

    refined = result.progress_tree.find_by_design_section("1.1")
    assert refined is not None
    assert refined.done_tasks == 10
    assert refined.total_tasks == 14
    assert refined.completion_pct == pytest.approx(10 / 14 * 100)
    assert result.batch_state.current_batch_id() == "B3"
