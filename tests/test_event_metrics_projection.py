"""Phase 83 T466：指标必须来自 EventStore 重放事实。"""

from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.metrics.collector import MetricsCollector
from auto_engineering.metrics.event_projection import project_event_metrics
from auto_engineering.metrics.usage import UsageRecord


def _event(sequence: int, event_type: LoopEventType, changes: dict) -> LoopEvent:
    return LoopEvent.create(
        thread_id="thread-1",
        sequence=sequence,
        event_type=event_type,
        payload={"changes": changes},
        correlation_id="thread-1",
    )


def test_replay_projects_major_and_refine_counts_instead_of_zero() -> None:
    events = [
        _event(1, LoopEventType.CRITIC_STATE_UPDATED, {"total_majors": 1}),
        _event(2, LoopEventType.PLAN_STATE_UPDATED, {"plan_refine_count": 1}),
        _event(3, LoopEventType.CRITIC_STATE_UPDATED, {"total_majors": 2}),
        _event(4, LoopEventType.PLAN_STATE_UPDATED, {"plan_refine_count": 2}),
    ]

    summary = project_event_metrics(events)

    assert summary["total_majors"] == 2
    assert summary["plan_refine_count"] == 2


def test_unknown_usage_is_explicitly_measurement_incomplete() -> None:
    record = UsageRecord(
        thread_id="thread-1", session_id="session-1", tick=1,
        stage="architect", worker="architect-0", input_units=None,
        cache_read_units=None, cache_write_units=None, output_units=None,
        provider="codex", model="unknown", usage_source="unsupported",
        estimated=False,
    )

    summary = project_event_metrics([], [record])

    assert summary["measurement_incomplete"] is True
    assert summary["usage"]["unknown_records"] == 1


def test_usage_recorded_event_is_the_only_runtime_usage_input(tmp_path) -> None:
    event = LoopEvent.create(
        thread_id="thread-1",
        sequence=0,
        event_type=LoopEventType.USAGE_RECORDED,
        payload={
            "usage": {
                "session_id": "session-1",
                "tick": 1,
                "stage": "developer",
                "worker": "main",
                "input_units": 10,
                "cache_read_units": 2,
                "cache_write_units": 1,
                "output_units": 5,
                "provider": "test",
                "model": "test-model",
                "usage_source": "test",
                "estimated": False,
            }
        },
        correlation_id="thread-1",
    )
    with SQLiteEventStore(tmp_path / "events.db") as store:
        store.append([event])
        summary = project_event_metrics(store.load_stream("thread-1"))
        assert summary["usage"] == {
            "input_units": 10,
            "cache_read_units": 2,
            "cache_write_units": 1,
            "output_units": 5,
            "records": 1,
            "unknown_records": 0,
        }


def test_event_store_backed_collector_has_no_local_metric_buffer(tmp_path) -> None:
    event = LoopEvent.create(
        thread_id="thread-1",
        sequence=0,
        event_type=LoopEventType.USAGE_RECORDED,
        payload={"usage": {"input_units": 7, "output_units": 3}},
        correlation_id="thread-1",
    )
    with SQLiteEventStore(tmp_path / "events.db") as store:
        store.append([event])
        collector = MetricsCollector(tmp_path, event_store=store)
        collector.begin_requirement("thread-1", "hash")
        summary = collector._compute_summary()
        assert summary["M5_token_efficiency"]["total_input_tokens"] == 7
        assert summary["M5_token_efficiency"]["total_output_tokens"] == 3
