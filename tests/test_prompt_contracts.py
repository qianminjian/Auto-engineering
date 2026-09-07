"""Phase 60 T280：Prompt Contract 注册与静态一致性。"""

from __future__ import annotations

from auto_engineering.config.constants import _SPAWN_CONFIG
from auto_engineering.loop.actions import result_contract_warnings
from auto_engineering.prompts.contracts import (
    ExecutionMode,
    default_prompt_contracts,
    validate_contract_registry,
)
from auto_engineering.prompts.registry import default_registry


def test_every_executable_stage_has_one_prompt_contract() -> None:
    contracts = default_prompt_contracts()

    assert set(contracts) == {
        "gap_scan",
        "research",
        "architect",
        "developer",
        "critic",
        "component_verifier",
        "plate_deep_audit",
        "system_verifier",
        "system_deep_audit",
    }


def test_contract_execution_modes_match_spawn_configuration() -> None:
    contracts = default_prompt_contracts()

    for stage, contract in contracts.items():
        spawn = _SPAWN_CONFIG.get(stage)
        if spawn is None:
            assert contract.execution_mode is ExecutionMode.INLINE
            assert contract.worker_roles == ()
        elif spawn["count"] == 1:
            assert contract.execution_mode is ExecutionMode.SINGLE_WORKER
            assert len(contract.worker_roles) == 1
        else:
            assert contract.execution_mode is ExecutionMode.MULTI_WORKER
            assert len(contract.worker_roles) == spawn["count"]


def test_default_contract_registry_is_statically_consistent() -> None:
    assert validate_contract_registry(default_prompt_contracts()) == []


def test_contracts_declare_context_needed_by_known_loss_paths() -> None:
    contracts = default_prompt_contracts()

    assert "project_profile_summary" in contracts["gap_scan"].required_context
    assert "host_design_sections" in contracts["gap_scan"].required_context
    assert {"requirement", "design_doc_path", "project_profile_summary"} <= set(
        contracts["architect"].required_context
    )
    assert {"requirement", "feedback", "tasks", "project_profile_summary"} <= set(
        contracts["developer"].required_context
    )
    assert "project_profile_summary" in (
        contracts["component_verifier"].required_context
    )
    assert "project_profile_summary" in contracts["system_verifier"].required_context
    assert {"plate", "components"} <= set(
        contracts["plate_deep_audit"].required_context
    )
    assert {"coverage_map"} <= set(
        contracts["system_deep_audit"].required_context
    )


def test_gap_scan_prompt_excludes_resolved_project_mechanics_from_user_gates() -> None:
    prompt = default_registry().get("gap_scan")

    assert "project_profile_summary" in prompt
    assert "已确定的工程事实" in prompt
    assert "不得升级为用户设计缺口" in prompt


def test_gap_scan_prompt_separates_design_ambiguity_from_implementation_work() -> None:
    prompt = default_registry().get("gap_scan")

    assert "代码尚未实现不是设计缺口" in prompt
    assert "只判定设计文档是否足以实现" in prompt
    assert "实现缺口必须留给 Architect/Developer" in prompt
    assert "“未来改进”不得提升为当前版本阻断项" in prompt
    assert "不得把未来改进章节" in prompt
    assert "作为当前 gap 的 `design_section_ref` 或证据" in prompt


def test_architect_prompt_binds_catalog_refs_to_components_and_tests() -> None:
    prompt = default_registry().get("architect")

    assert "design_item_refs" in prompt
    assert "plate_keys" in prompt
    assert "不能放入任意组件 batch" in prompt
    assert "每条 obligation 必须同时提供非空的" in prompt
    assert "只能指向 `kind=test|contract_test` 的 task" in prompt


def test_architect_prompt_requires_canonical_design_section_refs() -> None:
    prompt = default_registry().get("architect")

    assert "action.host_design_sections[].section_ref" in prompt
    assert "禁止填写板块标题、组件标题、章节标题全文" in prompt
    assert "不能输出" in prompt


def test_verifier_prompts_only_offer_result_schema_status_values() -> None:
    for stage in ("component_verifier", "system_verifier"):
        prompt = default_registry().get(stage)
        assert "UNCLEAR" not in prompt
        assert "IMPLEMENTED" in prompt
        assert "MISSING" in prompt
        assert "DIVERGED" in prompt


def test_consumed_optional_fields_emit_compatibility_warnings() -> None:
    warnings = result_contract_warnings(
        {"stage": "critic", "verdict": "APPROVE", "findings": []},
        "critic",
    )

    assert warnings == [{
        "code": "RESULT_OPTIONAL_FIELD_MISSING",
        "stage": "critic",
        "field": "critic_feedback",
    }]
