"""T69b: Signal + Diagnosis injection into action output."""
import tempfile
from pathlib import Path

import pytest

from auto_engineering.metrics.collector import AIOrigin, MetricsCollector, set_collector
from auto_engineering.metrics.enrichment import compute_metrics_signals


class TestComputeMetricsSignals:
    """compute_metrics_signals() — collector data → signals + diagnoses dict."""

    def test_empty_when_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = MetricsCollector(project_root=Path(tmp))
            result = compute_metrics_signals(collector)
            assert result == {}

    def test_returns_signals_and_diagnoses_when_data_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = MetricsCollector(project_root=Path(tmp))
            set_collector(collector)
            collector.begin_requirement("thread-1", "abc123")
            origin = AIOrigin(level="led", agent_role="developer",
                            model_name="claude-haiku-4-5", driver_type="agent")
            for i in range(1, 12):
                collector.record_tick_complete(
                    tick_number=i, stage="developer",
                    duration_ms=100, ai_origin=origin,
                )
            collector.end_requirement("APPROVE", total_ticks=11)

            result = compute_metrics_signals(collector)

            assert "metrics_signals" in result
            assert "metrics_diagnoses" in result

    def test_signals_have_required_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = MetricsCollector(project_root=Path(tmp))
            set_collector(collector)
            collector.begin_requirement("thread-1", "abc123")
            origin = AIOrigin(level="led", agent_role="developer",
                            model_name="claude-haiku-4-5", driver_type="agent")
            collector.record_tick_complete(
                tick_number=1, stage="developer",
                duration_ms=100, ai_origin=origin,
            )
            collector.end_requirement("APPROVE", total_ticks=1)

            result = compute_metrics_signals(collector)

            for s in result.get("metrics_signals", []):
                assert "name" in s
                assert "severity" in s
                assert "metric" in s

    def test_diagnoses_have_required_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = MetricsCollector(project_root=Path(tmp))
            set_collector(collector)
            collector.begin_requirement("thread-1", "abc123")
            origin = AIOrigin(level="led", agent_role="developer",
                            model_name="claude-haiku-4-5", driver_type="agent")
            for i in range(1, 12):
                collector.record_tick_complete(
                    tick_number=i, stage="developer",
                    duration_ms=100, ai_origin=origin,
                )
            collector.end_requirement("APPROVE", total_ticks=11)

            result = compute_metrics_signals(collector)

            for d in result.get("metrics_diagnoses", []):
                assert "signal_name" in d
                assert "severity" in d
                assert "possible_causes" in d
                assert "suggested_actions" in d
                assert "needs_human" in d
                assert "auto_adjustable" in d
