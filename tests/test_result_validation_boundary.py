"""Result 校验层必须只有一个 canonical implementation。"""

from __future__ import annotations

import importlib
import inspect

import auto_engineering.cli.active_action_source as active_action_source
import auto_engineering.loop.result_inbound_policy as result_inbound_policy
import auto_engineering.loop.result_validators as result_validators
import auto_engineering.loop.tick_evidence as tick_evidence
import auto_engineering.loop.tick_orchestrator as tick_orchestrator


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
    assert "_compute_diff_stats_impl(" in source
    assert "self._state.tick_latency_records.append" not in source
    assert callable(tick_evidence.record_tick_latency)
    assert callable(tick_evidence.compute_diff_stats)


def test_dev_loop_reads_active_action_through_one_source_module() -> None:
    dev_loop = importlib.import_module("auto_engineering.cli.dev_loop")
    source = inspect.getsource(dev_loop)

    assert dev_loop._active_thread_impl is active_action_source.active_thread
    assert dev_loop._load_active_action_impl is active_action_source.load_active_action
    assert "checkpoint_action =" not in source
