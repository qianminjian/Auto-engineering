"""MetricsCollector 只允许从 canonical EventStore 投影派生摘要。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.metrics.collector import AIOrigin, MetricsCollector


def _append(store: SQLiteEventStore, thread_id: str, event_type: LoopEventType,
            payload: dict) -> None:
    store.append([LoopEvent.create(
        thread_id=thread_id,
        sequence=store.next_sequence(thread_id),
        event_type=event_type,
        payload=payload,
        correlation_id=thread_id,
    )])


def _action(stage: str, tick: int, thread_id: str = "thread-1") -> dict:
    return {
        "action": "spawn",
        "message_id": f"action-{thread_id}-{tick}",
        "thread_id": thread_id,
        "tick": tick,
        "stage": stage,
    }


@pytest.fixture
def event_store(tmp_path: Path):
    with SQLiteEventStore(tmp_path / "events.db") as store:
        yield store


@pytest.fixture
def collector(tmp_path: Path, event_store: SQLiteEventStore) -> MetricsCollector:
    result = MetricsCollector(tmp_path, event_store=event_store)
    result.begin_requirement("thread-1", "hash-1")
    return result


class TestAIOrigin:
    def test_to_dict_preserves_origin_fields(self) -> None:
        origin = AIOrigin(
            level="led", agent_role="architect", model_name="model-1",
            model_version="v1", driver_type="agent",
        )
        assert origin.to_dict() == {
            "level": "led", "agent_role": "architect",
            "model_name": "model-1", "model_version": "v1",
            "driver_type": "agent",
        }

    def test_default_level_is_led(self) -> None:
        assert AIOrigin().level == "led"


class TestEventStoreOnlyCollector:
    def test_constructor_requires_canonical_event_store(self, tmp_path: Path) -> None:
        with pytest.raises(TypeError):
            MetricsCollector(tmp_path)  # type: ignore[call-arg]

    def test_begin_requirement_sets_scope_without_local_events(
        self, collector: MetricsCollector,
    ) -> None:
        collector.begin_requirement("thread-2", "hash-2", "simple_function")
        assert collector._current_thread_id == "thread-2"
        assert collector._current_category == "simple_function"
        assert not hasattr(collector, "_events")

    def test_event_recording_api_is_removed(self) -> None:
        for name in (
            "record_tick_complete", "record_token_usage",
            "record_stage_transition", "record_convergence",
            "record_gate_result", "record_pii_event", "record_tick_snapshot",
        ):
            assert not hasattr(MetricsCollector, name), name

    def test_summary_replays_current_thread_only(
        self, collector: MetricsCollector, event_store: SQLiteEventStore,
    ) -> None:
        for tick in range(1, 4):
            _append(event_store, "thread-1", LoopEventType.ACTION_ISSUED,
                    {"action": _action("developer", tick)})
        _append(event_store, "thread-1", LoopEventType.USAGE_RECORDED, {
            "usage": {
                "session_id": "session-1", "tick": 1, "stage": "developer",
                "worker": "main", "input_units": 100,
                "cache_read_units": 0, "cache_write_units": 0,
                "output_units": 50, "provider": "test", "model": "model",
                "usage_source": "test", "estimated": False,
            }
        })
        _append(event_store, "thread-1", LoopEventType.LOOP_COMPLETED,
                {"verdict": "GOAL_ACHIEVED", "tick": 3})
        _append(event_store, "thread-2", LoopEventType.ACTION_ISSUED,
                {"action": _action("critic", 1, "thread-2")})

        summary = collector.end_requirement("GOAL_ACHIEVED", total_ticks=3,
                                             loc_added=200)
        assert summary["M1_loop_efficiency"] == 3
        assert summary["M5_token_efficiency"]["total_tokens"] == 150
        assert summary["M5_token_efficiency"]["efficiency_ratio"] == 1333.33

    def test_resume_returns_temporary_projection(self, collector, event_store) -> None:
        _append(event_store, "thread-1", LoopEventType.USAGE_RECORDED, {
            "usage": {"input_units": 7, "output_units": 3}
        })
        projected = collector.resume_from_event_store("thread-1")
        assert projected[0]["event_type"] == "token_usage"
        assert not hasattr(collector, "_events")

    def test_summary_is_derived_persistence_only(self, collector, event_store) -> None:
        _append(event_store, "thread-1", LoopEventType.ACTION_ISSUED,
                {"action": _action("architect", 1)})
        collector._write_summary()
        summary_path = (
            collector._metrics_dir / "requirements" / "thread-1" / "summary.json"
        )
        assert summary_path.exists()
        assert "M1_loop_efficiency" in json.loads(summary_path.read_text())
        assert not list(collector._metrics_dir.rglob("events.jsonl"))


class TestBaselineManagement:
    def test_aggregator_projects_all_current_event_metrics(self) -> None:
        from auto_engineering.metrics._aggregator import _MetricsAggregator

        events = [
            {"event_type": "tick_complete", "payload": {"stage": "critic", "verdict": "MAJOR"}},
            {"event_type": "tick_complete", "payload": {"stage": "component_verifier"}},
            {"event_type": "tick_complete", "payload": {"stage": "plate_deep_audit"}},
            {"event_type": "tick_complete", "payload": {"stage": "system_verifier"}},
            {"event_type": "tick_complete", "payload": {"stage": "system_deep_audit"}},
            {"event_type": "critic_verdict", "payload": {"verdict": "MAJOR"}},
            {"event_type": "convergence", "payload": {"criteria_met": "plan_refine"}},
            {"event_type": "token_usage", "payload": {"input_tokens": 100, "output_tokens": 50}},
            {"event_type": "PII_ID", "payload": {"tick": 2}},
        ]

        summary = _MetricsAggregator().compute_summary(events, loc_added=200)

        assert summary["M1_loop_efficiency"] == 5
        assert summary["M2_critic_major_rate"] == 1.0
        assert summary["M3_verification_trigger_rate"]["system_deep_audit"] == 1
        assert summary["M4_plan_refine_count"] == 1
        assert summary["M5_token_efficiency"]["total_tokens"] == 150
        assert summary["pii_events"]["by_type"] == {"PII_ID": 1}

    def test_median_and_percentile(self) -> None:
        assert MetricsCollector._median([1.0, 3.0, 2.0]) == 2.0
        assert MetricsCollector._median([1.0, 2.0, 3.0, 4.0]) == 2.5
        assert 94 <= MetricsCollector._percentile(list(range(1, 101)), 95) <= 96

    def test_compare_periods(self, collector: MetricsCollector) -> None:
        root = collector._metrics_dir / "baselines"
        root.mkdir(parents=True)
        (root / "v1.json").write_text(json.dumps({"M1": 5}))
        (root / "v2.json").write_text(json.dumps({"M1": 3}))
        result = collector.compare_periods("v1", "v2")
        assert result == {"before": {"M1": 5}, "after": {"M1": 3}}
        assert collector.compare_periods("missing", "also-missing") is None

    def test_aggregator_handles_empty_and_invalid_baseline_inputs(
        self, tmp_path: Path,
    ) -> None:
        from auto_engineering.metrics._aggregator import _MetricsAggregator

        aggregator = _MetricsAggregator()
        assert aggregator.compute_summary([])["M5_token_efficiency"]["measurement_incomplete"]
        assert aggregator.load_baseline(tmp_path) is None
        assert aggregator.update_baseline(tmp_path) is None

        baselines = tmp_path / "baselines"
        baselines.mkdir()
        (baselines / "summary.json").write_text("[]", encoding="utf-8")
        assert aggregator.load_baseline(tmp_path) is None
        (baselines / "before.json").write_text("[]", encoding="utf-8")
        (baselines / "after.json").write_text("{}", encoding="utf-8")
        assert aggregator.compare_periods(tmp_path, "before", "after") is None
        assert aggregator._get_tag_timestamp("tag-that-does-not-exist") is None
        assert aggregator._median([]) == 0.0
        assert aggregator._percentile([], 95) == 0.0

        requirements = tmp_path / "requirements"
        requirements.mkdir()
        (requirements / "missing-summary").mkdir()
        invalid = requirements / "invalid"
        invalid.mkdir()
        (invalid / "summary.json").write_text("[]", encoding="utf-8")
        assert aggregator.update_baseline(tmp_path) is None

    def test_aggregator_covers_valid_baseline_and_git_timestamp_edges(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from auto_engineering.metrics import _aggregator
        from auto_engineering.metrics._aggregator import _MetricsAggregator

        aggregator = _MetricsAggregator()
        baseline_dir = tmp_path / "baselines"
        baseline_dir.mkdir()
        (baseline_dir / "summary.json").write_text(
            json.dumps({"sample_size": 1}), encoding="utf-8"
        )
        assert aggregator.load_baseline(tmp_path) == {"sample_size": 1}

        monkeypatch.setattr(
            _aggregator.subprocess,
            "run",
            lambda *args, **kwargs: type(
                "Completed", (), {"returncode": 0, "stdout": "1700000000\n"}
            )(),
        )
        assert aggregator._get_tag_timestamp("v1") == 1700000000.0
        monkeypatch.setattr(
            _aggregator.subprocess,
            "run",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("git unavailable")),
        )
        assert aggregator._get_tag_timestamp("v1") is None
        assert aggregator._percentile([7.0], 95) == 7.0

    def test_categorized_baselines_are_derived_from_summaries(
        self, collector: MetricsCollector,
    ) -> None:
        requirements = collector._metrics_dir / "requirements"
        for index in range(10):
            path = requirements / f"thread-{index}"
            path.mkdir(parents=True)
            (path / "summary.json").write_text(json.dumps({
                "M1_loop_efficiency": 3,
                "M2_critic_major_rate": 0,
            }))
            (path / "metadata.json").write_text(json.dumps({
                "category": "simple_function",
            }))
        assert collector.update_baseline() is not None
        result = collector._metrics_dir / "baselines" / "by_category" / "simple_function.json"
        assert json.loads(result.read_text())["sample_size"] == 10

    def test_driver_mode_is_agent_only(self, collector: MetricsCollector) -> None:
        assert collector._driver_mode == "agent"
        with pytest.raises(ValueError):
            collector.set_driver_mode("standalone")
        with pytest.raises(ValueError):
            collector.set_driver_mode("invalid")
