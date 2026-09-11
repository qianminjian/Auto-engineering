"""指标信号只能消费当前 EventStore 的派生摘要。"""

from __future__ import annotations

from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.metrics.collector import MetricsCollector
from auto_engineering.metrics.enrichment import compute_metrics_signals


def _make_collector(tmp_path, ticks: int = 0):
    store = SQLiteEventStore(tmp_path / "events.db")
    collector = MetricsCollector(tmp_path, event_store=store)
    collector.begin_requirement("thread-1", "hash-1")
    for tick in range(1, ticks + 1):
        store.append([LoopEvent.create(
            thread_id="thread-1",
            sequence=store.next_sequence("thread-1"),
            event_type=LoopEventType.ACTION_ISSUED,
            payload={"action": {
                "action": "spawn", "message_id": f"action-{tick}",
                "thread_id": "thread-1", "tick": tick,
                "stage": "developer",
            }},
            correlation_id="thread-1",
        )])
    if ticks:
        store.append([LoopEvent.create(
            thread_id="thread-1",
            sequence=store.next_sequence("thread-1"),
            event_type=LoopEventType.LOOP_COMPLETED,
            payload={"verdict": "GOAL_ACHIEVED", "tick": ticks},
            correlation_id="thread-1",
        )])
        collector.end_requirement("GOAL_ACHIEVED", total_ticks=ticks)
    return store, collector


class TestComputeMetricsSignals:
    def test_empty_when_no_data(self, tmp_path) -> None:
        store, collector = _make_collector(tmp_path)
        try:
            assert compute_metrics_signals(collector) == {}
        finally:
            store.close()

    def test_returns_signals_and_diagnoses_when_data_present(self, tmp_path) -> None:
        store, collector = _make_collector(tmp_path, ticks=11)
        try:
            result = compute_metrics_signals(collector)
            assert "metrics_signals" in result
            assert "metrics_diagnoses" in result
        finally:
            store.close()

    def test_signals_have_required_fields(self, tmp_path) -> None:
        store, collector = _make_collector(tmp_path, ticks=1)
        try:
            result = compute_metrics_signals(collector)
            for signal in result.get("metrics_signals", []):
                assert {"name", "severity", "metric"} <= set(signal)
        finally:
            store.close()

    def test_diagnoses_have_required_fields(self, tmp_path) -> None:
        store, collector = _make_collector(tmp_path, ticks=11)
        try:
            result = compute_metrics_signals(collector)
            for diagnosis in result.get("metrics_diagnoses", []):
                assert {
                    "signal_name", "severity", "possible_causes",
                    "suggested_actions", "needs_human", "auto_adjustable",
                } <= set(diagnosis)
        finally:
            store.close()
