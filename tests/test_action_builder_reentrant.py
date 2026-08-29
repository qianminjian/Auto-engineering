"""Phase 54 T253：ActionBuilder 交错调用不得泄漏单次上下文。"""

from __future__ import annotations

import json

import pytest

from auto_engineering.config.runtime_config import RuntimeConfig
from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.design_doc import Component, DesignDoc, Plate
from auto_engineering.engine.state import EngineState
from auto_engineering.host.spawn_contract import SpawnPlan
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
        EngineState(
            thread_id="routing",
            current_stage="architect",
            design_doc_digest="sha256:" + "1" * 64,
        ),
        design_doc=design_doc,
    )

    assert action["valid_plate_keys"] == ["类型系统", "工具模块"]
    assert '"valid_plate_keys": [' in action["subagent_prompt"]
    assert '"类型系统"' in action["subagent_prompt"]
    assert '"工具模块"' in action["subagent_prompt"]
    assert '"engineering_sections"' in action["subagent_prompt"]
    assert action["subagent_prompt"].count('"section_id"') == 2
    assert "action.host_execution.work_files.outcomes" in action["instruction"]
    assert "Never reuse files from another Action" in action["instruction"]
    assert '"outcomes"' in action["instruction"]
    assert "isolation_evidence" in action["instruction"]
    assert "actual_model='unreported'" in action["instruction"]
    assert "expected_isolation_evidence" in action["instruction"]
    assert "host_execution.operations.finalize.argv" in action["instruction"]
    assert "OVERWRITE" not in action["instruction"]
    assert '"spawn_proof_token":"' not in action["instruction"]
    expected = action["expected_format"]["batch_plan"]
    assert "batch_title" in expected
    assert "plate_keys" in expected
    assert "component" not in expected


def test_action_binds_internal_commands_to_immutable_project_root(tmp_path) -> None:
    project_root = tmp_path.resolve()

    action = ActionBuilder(project_root).build_action(
        EngineState(thread_id="root-bound", current_stage="architect"),
    )

    assert action["project_root"] == str(project_root)
    assert str(project_root) in action["instruction"]

    developer = ActionBuilder(project_root).build_action(
        EngineState(thread_id="root-bound-dev", current_stage="developer"),
    )
    assert str(project_root) in developer["instruction"]
    assert "working directory" in developer["instruction"]


def test_developer_action_uses_one_isolated_worker(tmp_path) -> None:
    action = ActionBuilder(tmp_path).build_action(
        EngineState(thread_id="developer-worker", current_stage="developer"),
    )

    plan = SpawnPlan.from_action(action)

    assert len(plan.invocations) == 1
    invocation = plan.invocations[0]
    assert invocation.role == "developer"
    assert invocation.isolation == "fresh_context"
    assert invocation.capabilities == {
        "may_drive_loop": False,
        "may_spawn_workers": False,
    }
    assert "Execute exactly 1 native worker" in action["instruction"]
    assert "Do the work for stage 'developer'" not in action["instruction"]


def test_action_feature_status_uses_injected_project_config(tmp_path) -> None:
    config = RuntimeConfig.from_environ({
        "AE_METRICS": "1",
        "AE_AUDIT_LOG": "1",
        "AE_PII_ENABLED": "1",
    })

    action = ActionBuilder(tmp_path, runtime_config=config).build_action(
        EngineState(thread_id="configured", current_stage="architect"),
    )

    assert action["feature_status"] == {
        "AE_AUDIT_LOG": True,
        "AE_METRICS": True,
        "AE_PII_ENABLED": True,
    }


def test_coordinator_expected_format_excludes_core_owned_identity(tmp_path) -> None:
    action = ActionBuilder(tmp_path).build_action(
        EngineState(thread_id="developer", current_stage="developer"),
    )

    assert "stage" not in action["expected_format"]
    assert "spawned" not in action["expected_format"]


def test_prompt_registry_failure_is_explicit_and_does_not_fallback_to_raw_file(
    tmp_path, monkeypatch
) -> None:
    from auto_engineering.loop import action_builder as module

    class BrokenRegistry:
        def get(self, _stage: str) -> str:
            raise ValueError("fragment drift")

    monkeypatch.setattr(module, "default_registry", lambda: BrokenRegistry())
    builder = ActionBuilder(tmp_path)

    with pytest.raises(RuntimeError, match="PROMPT_REGISTRY_UNAVAILABLE"):
        builder._load_prompt("architect")


def test_critic_action_exposes_machine_readable_business_result_contract(
    tmp_path,
) -> None:
    action = ActionBuilder(tmp_path).build_action(
        EngineState(thread_id="critic-contract", current_stage="critic"),
    )

    contract = action["result_contract"]
    assert contract["schema_version"] == "1.0"
    assert contract["required"] == ["verdict", "findings"]
    assert contract["properties"]["verdict"] == {"type": "string"}
    assert contract["properties"]["findings"] == {"type": "array"}
    assert contract["properties"]["strengths"] == {"type": "array"}
    assert contract["additionalProperties"] is False


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
        EngineState(
            thread_id="verify",
            current_stage="component_verifier",
            design_doc_digest="sha256:" + "2" * 64,
        ),
        design_doc=design_doc,
        batch_state=batch_state,
    )

    assert action["plate_keys"] == ["类型系统", "工具模块"]
    assert '"engineering_sections"' in action["subagent_prompt"]
    assert action["subagent_prompt"].count('"section_id"') == 2


def test_refine_action_exposes_core_owned_repair_contract(tmp_path) -> None:
    state = EngineState(
        thread_id="repair",
        current_stage="architect",
        plan_refine_count=2,
        refine_request_json=json.dumps({
            "source": "critic",
            "gaps": [{"source_ref": "F-001"}, {"source_ref": "F-002"}],
        }),
        architecture_baseline={
            "revision": 2,
            "obligations": [{"id": "O1", "source_ref": "gap-1"}],
            "batch_plan": [
                {"batch_id": "B1", "tasks": []},
                {"batch_id": "B2", "tasks": []},
                {"batch_id": "B3", "tasks": []},
            ],
        },
        batch_plan=[
            {"batch_id": "B1", "tasks": []},
            {"batch_id": "B2", "tasks": []},
            {"batch_id": "B3", "tasks": []},
        ],
    )

    action = ActionBuilder(tmp_path).build_action(state)

    contract = action["repair_contract"]
    assert contract["active_revision"] == 2
    assert contract["inherited_obligations"] == [
        {"id": "O1", "source_ref": "gap-1"}
    ]
    assert "base_revision" not in action["expected_format"]["plan_patch"]
    assert contract["task_template"]["kind"] == "implementation|test|contract_test"
    assert contract["required_source_refs"] == ["F-001", "F-002"]
    assert "逐项映射" in action["subagent_prompt"]
    assert action["batch_id_policy"] == {
        "reserved_batch_ids": ["B1", "B2", "B3"],
        "next_numeric_id": 4,
        "allocation_rule": "从 B4 起连续分配，禁止复用 reserved_batch_ids",
    }
    assert '"next_numeric_id": 4' in action["subagent_prompt"]
    assert "batch_id_policy" in action["expected_format"]["plan_patch"]


def test_architect_action_declares_design_authority_policy(tmp_path) -> None:
    action = ActionBuilder(tmp_path).build_action(
        EngineState(thread_id="authority", current_stage="architect")
    )

    policy = action["design_authority"]
    assert policy["binding_sources"] == ["explicit_design", "approved_change"]
    assert policy["advisory_sources"] == ["research", "agent_assumption"]
    assert policy["change_policy"] == "user_gate_required"
