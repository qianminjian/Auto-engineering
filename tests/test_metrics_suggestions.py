"""T69c: Ratchet verdict + automated suggestions generator."""
import tempfile
from pathlib import Path

import pytest

from auto_engineering.metrics.collector import AIOrigin, MetricsCollector, set_collector
from auto_engineering.metrics.enrichment import compute_metrics_signals
from auto_engineering.metrics.ratchet import RatchetController
from auto_engineering.metrics.suggestions import generate_suggestions


class TestGenerateSuggestions:
    """generate_suggestions() from signals + diagnoses."""

    def test_empty_when_no_signals(self):
        result = generate_suggestions(signals=[], diagnoses=[])
        assert isinstance(result, list)
        assert len(result) == 0

    def test_returns_suggestions_for_known_signals(self):
        signals = [
            {"name": "critic_major_increasing", "severity": "WARN",
             "metric": "M2_critic_major_rate", "value": 0.8},
        ]
        diagnoses = [
            {"signal_name": "critic_major_increasing", "severity": "WARN",
             "possible_causes": ["architect 计划质量下降"],
             "suggested_actions": ["检查最近 3 个需求的 batch_plan 质量"],
             "needs_human": ["对比 critic findings 与实际代码问题"]},
        ]
        result = generate_suggestions(signals, diagnoses)
        assert len(result) > 0
        for s in result:
            assert "level" in s
            assert "message" in s
            assert s["level"] in ("info", "warn", "error")

    def test_critical_signals_escalate_to_error_level(self):
        signals = [
            {"name": "critic_major_increasing", "severity": "CRITICAL",
             "metric": "M2_critic_major_rate", "value": 0.9},
        ]
        diagnoses = [
            {"signal_name": "critic_major_increasing", "severity": "CRITICAL",
             "possible_causes": ["architect 计划质量下降"],
             "suggested_actions": ["检查最近 3 个需求的 batch_plan 质量"],
             "needs_human": ["对比 critic findings 与实际代码问题"]},
        ]
        result = generate_suggestions(signals, diagnoses)
        assert any(s["level"] == "error" for s in result)

    def test_merges_signals_and_diagnoses_actions(self):
        signals = [
            {"name": "token_efficiency_drop", "severity": "WARN",
             "metric": "M5_token_efficiency", "value": 250000},
        ]
        diagnoses = [
            {"signal_name": "token_efficiency_drop", "severity": "WARN",
             "possible_causes": ["需求复杂度远超预期"],
             "suggested_actions": [
                 "检查需求分类是否正确",
                 "检查 batch 大小设置",
             ],
             "needs_human": ["检查最近一次 prompt registry hash"]},
        ]
        result = generate_suggestions(signals, diagnoses)
        messages = [s["message"] for s in result]
        assert any("需求分类" in m for m in messages)
        assert any("batch" in m for m in messages)


class TestRatchetIntegration:
    """RatchetController.evaluate() wired into signal enrichment flow."""

    def test_collector_with_ratchet_compare(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = MetricsCollector(project_root=Path(tmp))
            set_collector(collector)
            controller = RatchetController(project_root=Path(tmp))

            collector.begin_requirement("thread-1", "abc123")
            origin = AIOrigin(level="led", agent_role="developer",
                            model_name="claude-haiku-4-5", driver_type="agent")
            for i in range(1, 8):
                collector.record_tick_complete(
                    tick_number=i, stage="developer",
                    duration_ms=100, ai_origin=origin,
                )
            collector.end_requirement("APPROVE", total_ticks=7)

            result = compute_metrics_signals(collector)

            before_config = {"M1_loop_efficiency": 3, "M2_critic_major_rate": 0.0}
            after_config = collector.get_latest_summary() or {}
            verdict = controller.evaluate(before_config, after_config)

            assert verdict.action in ("keep", "revert", "stop")
            assert len(verdict.metrics) > 0

    def test_suggestions_from_enrichment_and_ratchet(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = MetricsCollector(project_root=Path(tmp))
            set_collector(collector)
            collector.begin_requirement("thread-1", "abc123")
            origin = AIOrigin(level="led", agent_role="developer",
                            model_name="claude-haiku-4-5", driver_type="agent")
            for i in range(1, 5):
                collector.record_tick_complete(
                    tick_number=i, stage="developer",
                    duration_ms=100, ai_origin=origin,
                )
            collector.end_requirement("APPROVE", total_ticks=5)

            enrichment = compute_metrics_signals(collector)
            suggestions = generate_suggestions(
                enrichment.get("metrics_signals", []),
                enrichment.get("metrics_diagnoses", []),
            )

            assert isinstance(suggestions, list)
