"""Phase 83 T466：指标必须来自 EventStore 重放事实。"""

from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.metrics.event_projection import project_event_metrics
from auto_engineering.metrics.usage_ledger import UsageRecord


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
