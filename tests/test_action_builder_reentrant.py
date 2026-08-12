"""Phase 54 T253：ActionBuilder 交错调用不得泄漏单次上下文。"""

from __future__ import annotations

import json

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.design_doc import Component, DesignDoc, Plate
from auto_engineering.engine.state import EngineState
from auto_engineering.loop.action_builder import ActionBuilder


def _state(thread_id: str, refine_source: str) -> EngineState:
    return EngineState(
        thread_id=thread_id,
        current_stage="architect",
        requirement=f"requirement-{thread_id}",
        refine_request_json=json.dumps({"source": refine_source}),
    )


def test_interleaved_build_keeps_outer_context(tmp_path, monkeypatch) -> None:
    builder = ActionBuilder(tmp_path)
    outer = _state("outer", "outer-source")
    inner = _state("inner", "inner-source")
    original = ActionBuilder._build_action_architect
    nested = False

    def interleave(invocation: ActionBuilder, base: dict) -> dict:
        nonlocal nested
        if not nested:
            nested = True
            inner_action = builder.build_action(inner)
            assert inner_action["thread_id"] == "inner"
        return original(invocation, base)

    monkeypatch.setattr(ActionBuilder, "_build_action_architect", interleave)

    outer_action = builder.build_action(outer)

    assert outer_action["thread_id"] == "outer"
    assert outer_action["requirement"] == "requirement-outer"
    assert outer_action["feedback"]["refine_request"]["source"] == "outer-source"


def test_sequential_optional_dependencies_do_not_leak(tmp_path) -> None:
    builder = ActionBuilder(tmp_path)
    first = EngineState(thread_id="first", current_stage="critic")
    first.files_changed = ["first.py"]
    second = EngineState(thread_id="second", current_stage="critic")

    first_action = builder.build_action(
        first,
        dev_snapshot={"files_changed": ["snapshot.py"]},
    )
    second_action = builder.build_action(second)

    assert '"snapshot.py"' in first_action["subagent_prompt"]
    assert '"snapshot.py"' not in second_action["subagent_prompt"]
    assert '"files_changed": []' in second_action["subagent_prompt"]
    assert "context" not in first_action
    assert "context" not in second_action


def test_architect_action_exposes_valid_machine_routing_keys(tmp_path) -> None:
    design_doc = DesignDoc(
        path="design/spec.md",
        supplements={},
        plates=[Plate(
            name="核心",
            design_section="§1",
            components=[
                Component(name="类型系统", design_section="§1.1"),
                Component(name="工具模块", design_section="§1.2"),
            ],
        )],
    )

    action = ActionBuilder(tmp_path).build_action(
        EngineState(thread_id="routing", current_stage="architect"),
        design_doc=design_doc,
    )

    assert action["valid_plate_keys"] == ["类型系统", "工具模块"]
    expected = action["expected_format"]["batch_plan"]
    assert "batch_title" in expected
    assert "plate_keys" in expected
    assert "component" not in expected


def test_component_verifier_receives_all_batch_plate_keys(tmp_path) -> None:
    design_doc = DesignDoc(
        path="design/spec.md",
        supplements={},
        plates=[Plate(
            name="核心",
            design_section="§1",
            components=[
                Component(name="类型系统", design_section="§1.1"),
                Component(name="工具模块", design_section="§1.2"),
            ],
        )],
    )
    batch_state = BatchState.from_design_doc(design_doc, [{
        "batch_id": "B1",
        "batch_title": "基础能力",
        "plate_keys": ["类型系统", "工具模块"],
        "design_sections": ["§1.1", "§1.2"],
        "tasks": [{"id": "T1", "file_targets": ["src/base.py"]}],
    }])

    action = ActionBuilder(tmp_path).build_action(
        EngineState(thread_id="verify", current_stage="component_verifier"),
        design_doc=design_doc,
        batch_state=batch_state,
    )

    assert action["plate_keys"] == ["类型系统", "工具模块"]


def test_refine_action_exposes_core_owned_repair_contract(tmp_path) -> None:
    state = EngineState(
        thread_id="repair",
        current_stage="architect",
        plan_refine_count=2,
        refine_request_json=json.dumps({"source": "critic", "gaps": []}),
        architecture_baseline={
            "revision": 2,
            "obligations": [{"id": "O1", "source_ref": "gap-1"}],
        },
    )

    action = ActionBuilder(tmp_path).build_action(state)

    contract = action["repair_contract"]
    assert contract["active_revision"] == 2
    assert contract["inherited_obligations"] == [
        {"id": "O1", "source_ref": "gap-1"}
    ]
    assert "base_revision" not in action["expected_format"]["plan_patch"]
    assert contract["task_template"]["kind"] == "implementation|test|contract_test"
