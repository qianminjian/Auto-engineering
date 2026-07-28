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

    assert {"requirement", "design_doc_path"} <= set(
        contracts["architect"].required_context
    )
    assert {"requirement", "feedback", "tasks"} <= set(
        contracts["developer"].required_context
    )
    assert {"plate", "components"} <= set(
        contracts["plate_deep_audit"].required_context
    )
    assert {"coverage_map"} <= set(
        contracts["system_deep_audit"].required_context
    )


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
