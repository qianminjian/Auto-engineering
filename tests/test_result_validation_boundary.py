"""Result 校验层必须只有一个 canonical implementation。"""

from __future__ import annotations

import importlib
import inspect

import pytest

import auto_engineering.cli.active_action_source as active_action_source
import auto_engineering.loop.result_inbound_policy as result_inbound_policy
import auto_engineering.loop.result_validators as result_validators
import auto_engineering.loop.tick_evidence as tick_evidence
import auto_engineering.loop.tick_orchestrator as tick_orchestrator
from auto_engineering.host.execution_assembler_result import ResultFinalizationMixin
from auto_engineering.host.result_contract import ResultContractService
from auto_engineering.host.worker_evidence import (
    HostEvidenceValidationError,
    NativeWorkerOutcome,
    _native_business_artifact,
)


def test_tick_orchestrator_delegates_result_validation_to_canonical_module() -> None:
    source = inspect.getsource(tick_orchestrator.TickOrchestrator)

    assert "def _validate_gap_analysis" in source
    assert "return _validate_gap_analysis_impl(self, result)" in source
    assert "def _validate_component_verifier_scope" in source
    assert "return _validate_component_verifier_scope_impl(self, result)" in source
    assert "def _validate_gap_review_decisions" in source
    assert "return _validate_gap_review_decisions_impl(self, result)" in source
    assert "expected_by_id =" not in source
    assert callable(result_validators.validate_gap_analysis)


def test_tick_orchestrator_delegates_inbound_pii_policy_to_canonical_module() -> None:
    source = inspect.getsource(tick_orchestrator.TickOrchestrator)

    assert "return _apply_inbound_pii_policy_impl(self, result)" in source
    assert "PII_BLOCKED_INBOUND" not in source
    assert callable(result_inbound_policy.apply_inbound_pii_policy)


def test_tick_orchestrator_delegates_observability_helpers() -> None:
    source = inspect.getsource(tick_orchestrator.TickOrchestrator)

    assert "_record_tick_latency_impl(" in source
    assert "_compute_diff_stats_impl(" not in source
    assert "self._state.tick_latency_records.append" not in source
    assert callable(tick_evidence.record_tick_latency)
    assert callable(tick_evidence.compute_diff_stats)


def test_dev_loop_reads_active_action_through_one_source_module() -> None:
    dev_loop = importlib.import_module("auto_engineering.cli.dev_loop")
    source = inspect.getsource(dev_loop)

    assert dev_loop._active_thread_impl is active_action_source.active_thread
    assert dev_loop._load_active_action_impl is active_action_source.load_active_action
    assert "checkpoint_action =" not in source


def _developer_action_with_scope() -> dict:
    return {
        "stage": "developer",
        "extensions": {
            "execution_scope": {
                "schema_version": "1.0",
                "mode": "developer_batch",
                "batch_id": "B1",
                "task_ids": ["B1-T1", "B1-T2"],
                "file_targets": ["auto_engineering/a.py"],
            },
        },
        "result_contract": {
            "schema_version": "1.0",
            "required": ["batch_id", "files_changed", "test_results"],
            "properties": {
                "batch_id": {"type": "string"},
                "task_ids": {"type": "array"},
                "files_changed": {"type": "array"},
                "test_results": {"type": "object"},
            },
            "additionalProperties": False,
        },
    }


def test_developer_result_must_match_every_task_in_active_batch() -> None:
    action = _developer_action_with_scope()

    with pytest.raises(
        HostEvidenceValidationError,
        match="DEVELOPER_TASK_IDS_SCOPE_MISMATCH",
    ):
        ResultContractService.normalize_business_payload(
            action=action,
            coordinator_payload={
                "batch_id": "B1",
                "task_ids": ["B1-T1"],
                "files_changed": [],
                "test_results": {"passed": 1},
            },
        )


def test_developer_scope_is_backfilled_even_without_legacy_result_contract() -> None:
    action = _developer_action_with_scope()
    action.pop("result_contract")

    normalized = ResultContractService.normalize_business_payload(
        action=action,
        coordinator_payload={"files_changed": [], "test_results": {"passed": 1}},
    )

    assert normalized["batch_id"] == "B1"
    assert normalized["task_ids"] == ["B1-T1", "B1-T2"]


def test_worker_business_artifact_has_only_the_four_private_contract_fields() -> None:
    artifact = _native_business_artifact(
        {"files_changed": [], "test_results": {"passed": 1}},
        worker_id="developer-0",
        status="completed",
    )

    assert set(artifact) == {"worker_id", "status", "payload", "summary"}
    assert not {
        "native_result", "generation", "fencing", "native_worker_handle",
    }.intersection(artifact)


def test_coordinator_payload_rejects_host_metadata_without_result_contract() -> None:
    with pytest.raises(
        HostEvidenceValidationError,
        match="COORDINATOR_HOST_FIELD_FORBIDDEN:native_result",
    ):
        ResultContractService.normalize_business_payload(
            action={"stage": "developer"},
            coordinator_payload={
                "task_ids": ["B1-T1"],
                "native_result": {"content": []},
            },
        )


def test_coordinator_payload_preserves_nested_worker_payload_without_host_facts() -> None:
    action = _developer_action_with_scope()
    payload = {
        "batch_id": "B1",
        "task_ids": ["B1-T1", "B1-T2"],
        "files_changed": [],
        "test_results": {"passed": 1},
        "worker_payload": {"nested": {"value": "kept"}},
    }
    action["result_contract"]["properties"]["worker_payload"] = {
        "type": "object",
    }

    normalized = ResultContractService.normalize_business_payload(
        action=action,
        coordinator_payload=payload,
    )

    assert normalized["worker_payload"] == {"nested": {"value": "kept"}}
    assert "native_worker_handle" not in normalized
    assert "execution_generation" not in normalized
    assert "fencing_token" not in normalized


def test_coordinator_scope_fields_remain_allowed_after_scope_backfill() -> None:
    action = _developer_action_with_scope()
    action["result_contract"]["properties"].pop("task_ids")

    normalized = ResultContractService.normalize_business_payload(
        action=action,
        coordinator_payload={
            "batch_id": "B1",
            "files_changed": [],
            "test_results": {"passed": 1},
        },
    )

    assert ResultContractService.coordinator_payload_violations(
        action,
        normalized,
    ) == []


def test_architect_candidate_cannot_drop_worker_batch_or_task() -> None:
    full_plan = [
        {
            "batch_id": "B1",
            "tasks": [{"id": "B1-T1", "description": "实现 B1"}],
        },
        {
            "batch_id": "B2",
            "tasks": [{"id": "B2-T1", "description": "实现 B2"}],
        },
    ]
    outcome = NativeWorkerOutcome(
        worker_id="architect-0",
        native_worker_handle="native-1",
        status="completed",
        payload={"batch_plan": full_plan},
        summary="完整计划",
        actual_model="test-model",
    )

    violations = ResultFinalizationMixin._architect_coverage_violations(
        action={"stage": "architect"},
        outcomes=[outcome],
        coordinator_payload={"batch_plan": [full_plan[0]]},
    )

    assert "ARCHITECT_RESULT_COVERAGE_LOSS" in violations
    assert "ARCHITECT_RESULT_MISSING_BATCHES:B2" in violations
    assert "ARCHITECT_RESULT_MISSING_TASKS:B2-T1" in violations
