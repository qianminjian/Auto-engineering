"""Phase 54 T253：ActionBuilder 交错调用不得泄漏单次上下文。"""

from __future__ import annotations

import inspect
import json

import pytest

from auto_engineering.config.runtime_config import RuntimeConfig
from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.design_doc import Component, DesignDoc, DesignItem, Plate
from auto_engineering.engine.state import EngineState
from auto_engineering.host.spawn_contract import SpawnPlan
from auto_engineering.loop.action_builder import ActionBuilder
from auto_engineering.loop.effects import EffectExecutor


def _build_action_with_worker_prompt(
    builder: ActionBuilder,
    state: EngineState,
    **kwargs,
) -> tuple[dict, str]:
    plan = builder.build_plan(state, **kwargs)
    executor = EffectExecutor(builder.project_root)
    for intent in plan.effect_intents:
        executor.execute(intent)
    action = plan.payload
    invocation = action["spawn"]["invocations"][0]
    prompt = (builder.project_root / invocation["prompt_ref"]).read_text(
        encoding="utf-8"
    )
    return action, prompt


def test_action_prompt_contracts_have_one_canonical_module() -> None:
    import auto_engineering.loop.action_builder as action_builder
    from auto_engineering.loop import action_prompt_contract

    assert action_builder._SPAWN_INSTRUCTION is action_prompt_contract.SPAWN_INSTRUCTION
    assert action_builder._SPAWN_MULTI_INSTRUCTION is action_prompt_contract.SPAWN_MULTI_INSTRUCTION
    assert action_builder._SPAWN_SINGLE_INSTRUCTION is action_prompt_contract.SPAWN_SINGLE_INSTRUCTION
    assert action_builder._INLINE_INSTRUCTION is action_prompt_contract.INLINE_INSTRUCTION
    assert "Execute exactly {count}" not in inspect.getsource(action_builder)


def test_spawn_contract_prioritizes_recovery_before_worker_tools() -> None:
    from auto_engineering.loop.action_prompt_contract import SPAWN_INSTRUCTION

    assert "Before evaluating action.spawn" in SPAWN_INSTRUCTION
    assert "spawn_permitted=false" in SPAWN_INSTRUCTION
    assert "do not call Agent, Task, TaskOutput" in SPAWN_INSTRUCTION


def test_spawn_contract_routes_business_test_failures_to_worker_failure() -> None:
    from auto_engineering.loop.action_prompt_contract import SPAWN_INSTRUCTION

    assert "test_results.failed" in SPAWN_INSTRUCTION
    assert "test_results.errors" in SPAWN_INSTRUCTION
    assert "record-worker-outcome" in SPAWN_INSTRUCTION
    assert "must not edit the private outcome" in SPAWN_INSTRUCTION


def test_spawn_prompt_contract_distinguishes_missing_and_invalid_private_outcome() -> None:
    from auto_engineering.loop.action_prompt_contract import SPAWN_INSTRUCTION

    assert "if the private artifact is missing, the single" in SPAWN_INSTRUCTION
    assert "if the private artifact exists but is invalid, preserve it" in SPAWN_INSTRUCTION
    assert "missing or lacks a valid worker_id/status/payload/summary envelope" not in SPAWN_INSTRUCTION


def test_spawn_instruction_requires_literal_record_argv_and_no_private_repair() -> None:
    from auto_engineering.loop.action_prompt_contract import SPAWN_INSTRUCTION

    assert "must contain literal argv values" in SPAWN_INSTRUCTION
    assert "never assign AE_INVOCATION_PROJECT_ROOT, ROOT, RUNNER" in SPAWN_INSTRUCTION
    assert "never use $VAR, command substitution or pwd" in SPAWN_INSTRUCTION
    assert "never use cat, tee, redirection or Write" in SPAWN_INSTRUCTION


def test_spawn_instruction_forbids_coordinator_private_directory_probe() -> None:
    from auto_engineering.loop.action_prompt_contract import SPAWN_INSTRUCTION

    assert "must never Read the worker prompt_ref" in SPAWN_INSTRUCTION
    assert "mkdir, list or inspect worker-outcomes" in SPAWN_INSTRUCTION
    assert "Host Runtime pre-creates" in SPAWN_INSTRUCTION
    assert "list or inspect worker-outcomes" in SPAWN_INSTRUCTION
    assert "not permission to switch to another tool" in SPAWN_INSTRUCTION


def test_stage_action_compilation_has_one_canonical_module() -> None:
    import auto_engineering.loop.action_builder as action_builder
    from auto_engineering.loop import stage_action_compiler

    assert action_builder._build_stage_action_impl is stage_action_compiler.build_stage_action
    assert "def _build_stage_action(" in inspect.getsource(action_builder.ActionBuilder)
    assert "return _build_stage_action_impl(" in inspect.getsource(action_builder.ActionBuilder)


def test_gap_scan_summary_has_one_canonical_projection_helper() -> None:
    import auto_engineering.loop.action_builder as action_builder
    from auto_engineering.loop import action_context_projection

    assert action_builder._gap_scan_summary_impl is action_context_projection.gap_scan_summary
    assert "return _gap_scan_summary_impl(self)" in inspect.getsource(action_builder.ActionBuilder)


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

    first_action, first_prompt = _build_action_with_worker_prompt(
        builder,
        first,
        dev_snapshot={"files_changed": ["snapshot.py"]},
    )
    second_action, second_prompt = _build_action_with_worker_prompt(builder, second)

    assert '"snapshot.py"' in first_prompt
    assert '"snapshot.py"' not in second_prompt
    assert '"files_changed": []' in second_prompt
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

    action, prompt = _build_action_with_worker_prompt(
        ActionBuilder(tmp_path),
        EngineState(
            thread_id="routing",
            current_stage="architect",
            design_doc_digest="sha256:" + "1" * 64,
        ),
        design_doc=design_doc,
    )

    assert action["valid_plate_keys"] == ["类型系统", "工具模块"]
    assert '"valid_plate_keys": [' in prompt
    assert '"类型系统"' in prompt
    assert '"工具模块"' in prompt
    assert '"engineering_sections"' in prompt
    assert prompt.count('"section_id"') == 2
    assert "Host Collector will merge them into the shared" in action["instruction"]
    assert "Never reuse files from another Action" in action["instruction"]
    assert '"outcomes"' in action["instruction"]
    assert "isolation_evidence" in action["instruction"]
    assert "actual_model='unreported'" in action["instruction"]
    assert "actual isolation evidence" in action["instruction"]
    assert "host_execution.operations.finalize.argv" in action["instruction"]
    assert "OVERWRITE" not in action["instruction"]
    assert '"spawn_proof_token":"' not in action["instruction"]
    expected = action["expected_format"]["batch_plan"]
    assert "batch_title" in expected
    assert "plate_keys" in expected
    assert "component" not in expected


def test_architect_action_exposes_plate_key_for_flat_design_doc(tmp_path) -> None:
    """只有 H2 板块的设计也必须拥有可执行的非空路由域。"""
    design_doc = DesignDoc(
        path="design/flat.md",
        supplements={},
        plates=[Plate(name="Greeting API", design_section="§C1")],
    )

    action, _ = _build_action_with_worker_prompt(
        ActionBuilder(tmp_path),
        EngineState(
            thread_id="flat-routing",
            current_stage="architect",
            design_doc_digest="sha256:" + "1" * 64,
        ),
        design_doc=design_doc,
    )

    assert action["valid_plate_keys"] == ["Greeting API"]


def test_architect_action_exposes_copyable_canonical_design_item_refs(tmp_path) -> None:
    design_doc = DesignDoc(
        path="design/canonical.md",
        supplements={},
        plates=[Plate(
            name="Core",
            design_section="§A1",
            components=[Component(
                name="Counter",
                design_section="§A1.1",
                design_items=[
                    DesignItem("A1.1-1", "§A1.1", "Function", ["claim"], "item"),
                    DesignItem("A1.1-2", "§A1.1", "Verification", ["tests"], "item"),
                ],
            )],
        )],
    )

    action, prompt = _build_action_with_worker_prompt(
        ActionBuilder(tmp_path),
        EngineState(
            thread_id="canonical-refs",
            current_stage="architect",
            design_doc_digest="sha256:" + "1" * 64,
        ),
        design_doc=design_doc,
    )

    assert '"A1.1-1"' in prompt
    assert "canonical_design_item_refs" in prompt
    assert "禁止用章节号、标题或自造 slug 替代" in action["expected_format"]["batch_plan"]


def test_parsed_flat_design_doc_keeps_plate_routing_key(tmp_path) -> None:
    design_path = tmp_path / "design" / "flat.md"
    design_path.parent.mkdir()
    design_path.write_text(
        "# Greeting API\n\n## §C1 Greeting API\n\n"
        "Return the documented greeting.\n",
        encoding="utf-8",
    )
    design_doc = DesignDoc.parse(design_path)

    action, _ = _build_action_with_worker_prompt(
        ActionBuilder(tmp_path),
        EngineState(
            thread_id="parsed-flat-routing",
            current_stage="architect",
            design_doc_digest="sha256:" + "1" * 64,
        ),
        design_doc=design_doc,
    )

    assert action["valid_plate_keys"] == ["Greeting API"]


def test_architect_prompt_carries_persisted_gap_decisions(tmp_path) -> None:
    """Architect/REPAIR 必须看到已批准的 Gap 决策，不能只重读原设计文档。"""
    state = EngineState(
        thread_id="gap-decisions",
        current_stage="architect",
        refine_request_json=json.dumps({"source": "component_verifier"}),
        pending_gap_decisions=[{
            "gap_id": "GAP-1",
            "resolution": "fill",
            "fill_content": "CloneParams 必须包含 voiceId 与 sampleUrl",
            "decision_source": "user",
            "assistant_recommendation": "Research",
            "recommendation_accepted": False,
            "evidence_refs": ["§5.2"],
        }],
    )

    _action, prompt = _build_action_with_worker_prompt(ActionBuilder(tmp_path), state)

    assert '"gap_decisions"' in prompt
    assert "CloneParams 必须包含 voiceId 与 sampleUrl" in prompt


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


def test_critic_assurance_format_is_copyable_and_names_nested_findings(
    tmp_path,
) -> None:
    design_doc = DesignDoc(
        path="design/spec.md",
        supplements={},
        plates=[Plate(
            name="Core",
            design_section="§1",
            components=[Component(name="Counter", design_section="§1.1")],
        )],
    )
    batch_state = BatchState.from_design_doc(design_doc, [{
        "batch_id": "B1",
        "batch_title": "Counter",
        "plate_keys": ["Counter"],
        "design_sections": ["§1.1"],
        "tasks": [{"id": "T1", "file_targets": ["src/counter.py"]}],
    }])
    batch_state.advance_batch()
    action = ActionBuilder(tmp_path).build_action(
        EngineState(thread_id="critic-assurance-contract", current_stage="critic"),
        design_doc=design_doc,
        batch_state=batch_state,
    )

    assurance_format = action["expected_format"]["assurance_bundle"]

    assert '"component_verification":{"component"' in assurance_format
    assert '"system_audit":{"dimensions"' in assurance_format
    assert '"findings":[]' in assurance_format
    assert "system_audit.findings" in assurance_format

    contract = action["result_contract"]
    assert contract["properties"]["findings"] == {"type": "array"}
    assert contract["properties"]["strengths"] == {"type": "array"}
    assert contract["additionalProperties"] is False


def test_research_action_contract_matches_nullable_search_error(
    tmp_path,
) -> None:
    """Action 生成的机器合同必须与 Research Result 的可选 null 语义一致。"""
    import json

    state = EngineState(
        thread_id="research-contract",
        current_stage="research",
        requirement="核对外部 API 研究结论",
        gap_report_json=json.dumps({
            "gaps": [{"id": "G1", "design_section_ref": "§1"}],
        }),
        pending_research_ids=["G1"],
    )
    action = ActionBuilder(tmp_path).build_action(state)

    assert action["result_contract"]["properties"]["search_error"] == {
        "type": ["string", "null"],
    }


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

    action, prompt = _build_action_with_worker_prompt(
        ActionBuilder(tmp_path),
        EngineState(
            thread_id="verify",
            current_stage="component_verifier",
            design_doc_digest="sha256:" + "2" * 64,
        ),
        design_doc=design_doc,
        batch_state=batch_state,
    )

    assert action["plate_keys"] == ["类型系统", "工具模块"]
    assert '"engineering_sections"' in prompt
    assert prompt.count('"section_id"') == 2


def test_component_verifier_is_scoped_to_current_batch_design_items(tmp_path) -> None:
    design_doc = DesignDoc(
        path="design/spec.md",
        supplements={},
        plates=[Plate(
            name="核心",
            design_section="§1",
            components=[Component(
                name="类型系统",
                design_section="§1.1",
                design_items=[
                    DesignItem("§1.1-1", "§1.1", "类型声明", ["字段约束"], "heading"),
                    DesignItem("§1.1-2", "§1.1", "运行时校验", ["拒绝非法值"], "heading"),
                ],
            )],
        )],
    )
    batch_state = BatchState.from_design_doc(design_doc, [{
        "batch_id": "B1",
        "component": "类型系统",
        "design_sections": ["§1.1"],
        "design_item_refs": ["§1.1-1"],
        "tasks": [{"id": "T1", "file_targets": ["src/base.py"]}],
    }])

    action, prompt = _build_action_with_worker_prompt(
        ActionBuilder(tmp_path),
        EngineState(
            thread_id="verify-scope",
            current_stage="component_verifier",
            design_doc_digest="sha256:" + "3" * 64,
        ),
        design_doc=design_doc,
        batch_state=batch_state,
    )

    assert action["verification_scope"]["design_item_ids"] == ["§1.1-1"]
    assert '"design_item": "§1.1-1"' in prompt
    assert '"design_item": "§1.1-2"' not in prompt


def test_component_verifier_scope_moves_with_batch_cursor(tmp_path) -> None:
    component = Component(
        name="类型系统",
        design_section="§1.1",
        design_items=[
            DesignItem("§1.1-1", "§1.1", "类型声明", [], "heading"),
            DesignItem("§1.1-2", "§1.1", "运行时校验", [], "heading"),
        ],
    )
    design_doc = DesignDoc(
        path="design/spec.md", supplements={},
        plates=[Plate(name="核心", design_section="§1", components=[component])],
    )
    batch_state = BatchState.from_design_doc(design_doc, [
        {"batch_id": "B1", "component": "类型系统", "design_item_refs": ["§1.1-1"],
         "tasks": [{"id": "T1", "file_targets": ["src/base.py"]}]},
        {"batch_id": "B2", "component": "类型系统", "design_item_refs": ["§1.1-2"],
         "tasks": [{"id": "T2", "file_targets": ["src/base.py"]}]},
    ])
    state = EngineState(
        thread_id="verify-cursor", current_stage="component_verifier",
        design_doc_digest="sha256:" + "4" * 64,
    )
    builder = ActionBuilder(tmp_path)

    first = builder.build_action(state, design_doc=design_doc, batch_state=batch_state)
    batch_state.current_batch_idx = 1
    second = builder.build_action(state, design_doc=design_doc, batch_state=batch_state)

    assert first["verification_scope"]["design_item_ids"] == ["§1.1-1"]
    assert second["verification_scope"]["design_item_ids"] == ["§1.1-2"]


def test_component_verifier_fails_closed_for_legacy_multi_batch_scope(tmp_path) -> None:
    component = Component(
        name="类型系统", design_section="§1.1",
        design_items=[DesignItem("§1.1-1", "§1.1", "类型声明", [], "heading")],
    )
    design_doc = DesignDoc(
        path="design/spec.md", supplements={},
        plates=[Plate(name="核心", design_section="§1", components=[component])],
    )
    batch_state = BatchState.from_design_doc(design_doc, [
        {"batch_id": "B1", "component": "类型系统", "tasks": []},
        {"batch_id": "B2", "component": "类型系统", "tasks": []},
    ])

    action = ActionBuilder(tmp_path).build_action(
        EngineState(
            thread_id="legacy-scope", current_stage="component_verifier",
            design_doc_digest="sha256:" + "5" * 64,
        ),
        design_doc=design_doc,
        batch_state=batch_state,
    )

    assert action["action"] == "error"
    assert action["error_code"] == "VERIFICATION_SCOPE_UNDECLARED"


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

    action, prompt = _build_action_with_worker_prompt(ActionBuilder(tmp_path), state)

    contract = action["repair_contract"]
    assert contract["active_revision"] == 2
    assert contract["inherited_obligations"] == [
        {"id": "O1", "source_ref": "gap-1"}
    ]
    assert "base_revision" not in action["expected_format"]["plan_patch"]
    assert contract["task_template"]["kind"] == "implementation|test|contract_test"
    assert contract["required_source_refs"] == ["F-001", "F-002"]
    assert "逐项映射" in prompt
    assert action["batch_id_policy"] == {
        "reserved_batch_ids": ["B1", "B2", "B3"],
        "next_numeric_id": 4,
        "allocation_rule": "从 B4 起连续分配，禁止复用 reserved_batch_ids",
    }
    assert '"next_numeric_id": 4' in prompt
    assert "batch_id_policy" in action["expected_format"]["plan_patch"]


def test_architect_action_declares_design_authority_policy(tmp_path) -> None:
    action = ActionBuilder(tmp_path).build_action(
        EngineState(thread_id="authority", current_stage="architect")
    )

    policy = action["design_authority"]
    assert policy["binding_sources"] == ["explicit_design", "approved_change"]
    assert policy["advisory_sources"] == ["research", "agent_assumption"]
    assert policy["change_policy"] == "user_gate_required"
