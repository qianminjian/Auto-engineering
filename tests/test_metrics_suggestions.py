"""指标建议链路使用 EventStore 派生摘要，不使用本地事件回调。"""

from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.metrics.collector import MetricsCollector
from auto_engineering.metrics.enrichment import compute_metrics_signals
from auto_engineering.metrics.ratchet import RatchetController
from auto_engineering.metrics.suggestions import generate_suggestions


class TestGenerateSuggestions:
    def test_empty_when_no_signals(self):
        assert generate_suggestions(signals=[], diagnoses=[]) == []

    def test_returns_suggestions_for_known_signals(self):
        signals = [{
            "name": "critic_major_increasing", "severity": "WARN",
            "metric": "M2_critic_major_rate", "value": 0.8,
        }]
        diagnoses = [{
            "signal_name": "critic_major_increasing", "severity": "WARN",
            "possible_causes": ["architect 计划质量下降"],
            "suggested_actions": ["检查最近 3 个需求的 batch_plan 质量"],
            "needs_human": ["对比 critic findings 与实际代码问题"],
        }]
        result = generate_suggestions(signals, diagnoses)
        assert result
        assert all(item["level"] in ("info", "warn", "error") for item in result)

    def test_critical_signals_escalate_to_error_level(self):
        signals = [{
            "name": "critic_major_increasing", "severity": "CRITICAL",
            "metric": "M2_critic_major_rate", "value": 0.9,
        }]
        diagnoses = [{
            "signal_name": "critic_major_increasing", "severity": "CRITICAL",
            "possible_causes": ["architect 计划质量下降"],
            "suggested_actions": ["检查最近 3 个需求的 batch_plan 质量"],
            "needs_human": ["对比 critic findings 与实际代码问题"],
        }]
        assert any(
            item["level"] == "error"
            for item in generate_suggestions(signals, diagnoses)
        )

    def test_merges_signals_and_diagnoses_actions(self):
        signals = [{
            "name": "token_efficiency_drop", "severity": "WARN",
            "metric": "M5_token_efficiency", "value": 250000,
        }]
        diagnoses = [{
            "signal_name": "token_efficiency_drop", "severity": "WARN",
            "possible_causes": ["需求复杂度远超预期"],
            "suggested_actions": ["检查需求分类是否正确", "检查 batch 大小设置"],
            "needs_human": ["检查最近一次 prompt registry hash"],
        }]
        messages = [
            item["message"] for item in generate_suggestions(signals, diagnoses)
        ]
        assert any("需求分类" in message for message in messages)
        assert any("batch" in message for message in messages)


def _collector_with_summary(tmp_path):
    store = SQLiteEventStore(tmp_path / "events.db")
    collector = MetricsCollector(tmp_path, event_store=store)
    collector.begin_requirement("thread-1", "hash-1")
    for tick in range(1, 8):
        store.append([LoopEvent.create(
            thread_id="thread-1",
            sequence=store.next_sequence("thread-1"),
            event_type=LoopEventType.ACTION_ISSUED,
            payload={"action": {
                "action": "spawn", "message_id": f"action-{tick}",
                "thread_id": "thread-1", "tick": tick, "stage": "developer",
            }},
            correlation_id="thread-1",
        )])
    store.append([LoopEvent.create(
        thread_id="thread-1", event_type=LoopEventType.LOOP_COMPLETED,
        sequence=store.next_sequence("thread-1"),
        payload={"verdict": "GOAL_ACHIEVED", "tick": 7},
        correlation_id="thread-1",
    )])
    collector.end_requirement("GOAL_ACHIEVED", total_ticks=7)
    return store, collector


class TestRatchetIntegration:
    def test_collector_with_ratchet_compare(self, tmp_path):
        store, collector = _collector_with_summary(tmp_path)
        try:
            result = compute_metrics_signals(collector)
            assert isinstance(result, dict)
            verdict = RatchetController(tmp_path).evaluate(
                {"M1_loop_efficiency": 3, "M2_critic_major_rate": 0.0},
                collector.get_latest_summary() or {},
            )
            assert verdict.action in ("keep", "revert", "stop")
            assert verdict.metrics
        finally:
            store.close()

    def test_suggestions_from_enrichment_and_ratchet(self, tmp_path):
        store, collector = _collector_with_summary(tmp_path)
        try:
            enrichment = compute_metrics_signals(collector)
            suggestions = generate_suggestions(
                enrichment.get("metrics_signals", []),
                enrichment.get("metrics_diagnoses", []),
            )
            assert isinstance(suggestions, list)
        finally:
            store.close()
