"""T65: MetricsCollector + AIOrigin — TDD tests."""
import json
import tempfile
from pathlib import Path

import pytest

from auto_engineering.metrics.collector import AIOrigin, MetricsCollector


class TestAIOrigin:
    """AI traceability marker — F.2.1."""

    def test_creates_with_required_fields(self):
        origin = AIOrigin(
            level="led",
            agent_role="architect",
            model_name="claude-sonnet-4-6",
            model_version="v1",
            driver_type="agent",
        )
        assert origin.level == "led"
        assert origin.agent_role == "architect"
        assert origin.model_name == "claude-sonnet-4-6"
        assert origin.driver_type == "agent"

    def test_default_level_is_led(self):
        origin = AIOrigin(
            agent_role="developer",
            model_name="claude-haiku-4-5",
            driver_type="agent",
        )
        assert origin.level == "led"


class TestMetricsCollectorInit:
    """MetricsCollector initialization — F.3."""

    def test_creates_metrics_directory_on_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            collector = MetricsCollector(project_root)
            metrics_dir = project_root / ".ae-state" / "metrics"
            assert metrics_dir.exists()
            assert metrics_dir.is_dir()
            assert collector._metrics_dir == metrics_dir

    def test_creates_in_nonexistent_ae_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            ae_state = project_root / ".ae-state"
            assert not ae_state.exists()
            collector = MetricsCollector(project_root)
            assert ae_state.exists()


class TestRequirementLifecycle:
    """Requirement-scoped lifecycle — begin → events → end → summary."""

    @pytest.fixture
    def collector(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield MetricsCollector(Path(tmp))

    def test_begin_requirement_starts_new_scope(self, collector):
        collector.begin_requirement("thread-1", "abc123")
        assert collector._current_thread_id == "thread-1"
        assert len(collector._events) == 1
        assert collector._events[0]["event_type"] == "requirement_start"

    def test_begin_requirement_with_category_sets_category(self, collector):
        collector.begin_requirement("thread-1", "abc123",
                                    requirement_category="medium_crud")
        assert collector._current_category == "medium_crud"

    def test_begin_requirement_writes_category_metadata(self, collector):
        collector.begin_requirement("thread-1", "abc123",
                                    requirement_category="simple_function")
        collector.end_requirement("GOAL_ACHIEVED", total_ticks=3)
        meta_path = collector._metrics_dir / "requirements" / "thread-1" / "metadata.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["category"] == "simple_function"

    def test_begin_requirement_no_category_no_metadata(self, collector):
        collector.begin_requirement("thread-1", "abc123")
        collector.end_requirement("GOAL_ACHIEVED", total_ticks=3)
        meta_path = collector._metrics_dir / "requirements" / "thread-1" / "metadata.json"
        assert not meta_path.exists()

    def test_end_requirement_produces_summary(self, collector):
        collector.begin_requirement("thread-1", "abc123")
        summary = collector.end_requirement("GOAL_ACHIEVED", total_ticks=5)
        assert "M1_loop_efficiency" in summary
        assert "M2_critic_major_rate" in summary
        assert "M3_verification_trigger_rate" in summary
        assert "M4_plan_refine_count" in summary
        assert "M5_token_efficiency" in summary

    def test_end_requirement_writes_summary_json(self, collector):
        collector.begin_requirement("thread-1", "abc123")
        collector.end_requirement("GOAL_ACHIEVED", total_ticks=3)
        summary_path = (
            collector._metrics_dir / "requirements" / "thread-1" / "summary.json"
        )
        assert summary_path.exists()
        data = json.loads(summary_path.read_text())
        assert data["M1_loop_efficiency"] == 0

    def test_begin_requirement_flush_previous_if_unended(self, collector):
        collector.begin_requirement("thread-1", "abc123")
        collector.record_tick_complete(
            1, "architect", 1000,
            ai_origin=AIOrigin(level="led", agent_role="architect",
                               model_name="m1", driver_type="agent"),
        )
        collector.begin_requirement("thread-2", "def456")
        # thread-1 的 events.jsonl 应该已经被 flush
        events_path = (
            collector._metrics_dir / "requirements" / "thread-1" / "events.jsonl"
        )
        assert events_path.exists()


class TestEventRecording:
    """5 event types: tick_complete / token_usage / stage_transition /
    convergence / gate_result — F.2.2."""

    @pytest.fixture
    def collector(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = MetricsCollector(Path(tmp))
            c.begin_requirement("thread-1", "abc123")
            yield c

    def test_record_tick_complete(self, collector):
        origin = AIOrigin(level="led", agent_role="architect",
                          model_name="claude-sonnet-4-6", driver_type="agent")
        collector.record_tick_complete(
            1, "architect", 1500, origin,
            {"safety": "passed"}, {"g1": "pass"},
        )
        assert len(collector._events) == 2  # requirement_start + tick_complete
        evt = collector._events[-1]
        assert evt["event_type"] == "tick_complete"
        assert evt["payload"]["tick_number"] == 1
        assert evt["payload"]["stage"] == "architect"
        assert evt["ai_origin"]["agent_role"] == "architect"

    def test_record_tick_complete_with_verdict(self, collector):
        origin = AIOrigin(level="led", agent_role="critic",
                          model_name="claude-sonnet-4-6", driver_type="agent")
        collector.record_tick_complete(
            2, "critic", 800, origin,
            {}, {}, verdict="MAJOR",
        )
        assert collector._events[-1]["payload"]["verdict"] == "MAJOR"

    def test_record_token_usage(self, collector):
        origin = AIOrigin(level="led", agent_role="developer",
                          model_name="claude-haiku-4-5", driver_type="agent")
        collector.record_token_usage(
            1500, 800, model="claude-haiku-4-5",
            provider="anthropic", stage="developer",
            ai_origin=origin,
        )
        evt = collector._events[-1]
        assert evt["event_type"] == "token_usage"
        assert evt["payload"]["input_tokens"] == 1500
        assert evt["payload"]["output_tokens"] == 800

    def test_record_stage_transition(self, collector):
        origin = AIOrigin(level="led", agent_role="architect",
                          model_name="claude-sonnet-4-6", driver_type="agent")
        collector.record_stage_transition(
            "architect", "developer", "batch_plan_ready", origin)
        evt = collector._events[-1]
        assert evt["event_type"] == "stage_transition"
        assert evt["payload"]["from_stage"] == "architect"
        assert evt["payload"]["to_stage"] == "developer"

    def test_record_convergence(self, collector):
        origin = AIOrigin(level="led", agent_role="critic",
                          model_name="claude-sonnet-4-6", driver_type="agent")
        collector.record_convergence("APPROVE", 5, "critic_approved", origin)
        evt = collector._events[-1]
        assert evt["event_type"] == "convergence"
        assert evt["payload"]["verdict"] == "APPROVE"
        assert evt["payload"]["total_ticks"] == 5

    def test_record_gate_result(self, collector):
        origin = AIOrigin(level="led", agent_role="developer",
                          model_name="claude-haiku-4-5", driver_type="agent")
        collector.record_gate_result("safety", True, 120, 0, origin)
        evt = collector._events[-1]
        assert evt["event_type"] == "gate_result"
        assert evt["payload"]["gate_name"] == "safety"
        assert evt["payload"]["passed"] is True


class TestM5EfficiencyComputation:
    """M5 token efficiency with loc_added — F.3 _compute_summary."""

    @pytest.fixture
    def collector(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = MetricsCollector(Path(tmp))
            c.begin_requirement("thread-1", "abc123")
            return c

    def test_m5_efficiency_zero_when_loc_added_is_zero(self, collector):
        origin = AIOrigin(level="led", agent_role="developer",
                          model_name="m1", driver_type="agent")
        collector.record_token_usage(
            5000, 2000, model="m1", provider="anthropic",
            stage="developer", ai_origin=origin,
        )
        summary = collector.end_requirement("GOAL_ACHIEVED", total_ticks=3)
        assert summary["M5_token_efficiency"]["efficiency_ratio"] == 0.0

    def test_m5_efficiency_ratio_with_loc_added(self, collector):
        origin = AIOrigin(level="led", agent_role="developer",
                          model_name="m1", driver_type="agent")
        collector.record_token_usage(
            5000, 5000, model="m1", provider="anthropic",
            stage="developer", ai_origin=origin,
        )  # 10K tokens
        summary = collector.end_requirement("GOAL_ACHIEVED", total_ticks=3, loc_added=200)
        # 200 lines / (10000/1000) = 200 / 10 = 20.0
        assert summary["M5_token_efficiency"]["efficiency_ratio"] == 20.0
        assert summary["M5_token_efficiency"]["loc_added"] == 200

    def test_m5_zero_tokens_efficiency_is_zero(self, collector):
        summary = collector.end_requirement("GOAL_ACHIEVED", total_ticks=1, loc_added=100)
        assert summary["M5_token_efficiency"]["efficiency_ratio"] == 0.0
        assert summary["M5_token_efficiency"]["total_tokens"] == 0


class TestFlushBehavior:
    """_flush_events + _write_summary — F.3."""

    def test_flush_uses_overwrite_not_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = MetricsCollector(Path(tmp))
            c.begin_requirement("thread-1", "abc123")
            origin = AIOrigin(level="led", agent_role="architect",
                              model_name="m1", driver_type="agent")
            c.record_token_usage(
                100, 50, model="m1", provider="anthropic",
                stage="architect", ai_origin=origin,
            )
            c._flush()
            events_path = (
                c._metrics_dir / "requirements" / "thread-1" / "events.jsonl"
            )
            content1 = events_path.read_text()

            # second flush — same events, no change → overwrite with same content
            c._flush()
            content2 = events_path.read_text()
            # overwrite mode: file size shouldn't grow (no append doubling)
            assert len(content2) == len(content1)

    def test_flush_events_writes_only_events_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = MetricsCollector(Path(tmp))
            c.begin_requirement("thread-1", "abc123")
            origin = AIOrigin(level="led", agent_role="architect",
                             model_name="m1", driver_type="agent")
            c.record_token_usage(
                100, 50, model="m1", provider="anthropic",
                stage="architect", ai_origin=origin,
            )
            c._flush_events()
            events_path = c._metrics_dir / "requirements" / "thread-1" / "events.jsonl"
            assert events_path.exists()
            # _flush_events alone should NOT write summary.json
            summary_path = c._metrics_dir / "requirements" / "thread-1" / "summary.json"
            assert not summary_path.exists()

    def test_write_summary_computes_and_writes_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = MetricsCollector(Path(tmp))
            c.begin_requirement("thread-1", "abc123")
            c._write_summary()
            summary_path = c._metrics_dir / "requirements" / "thread-1" / "summary.json"
            assert summary_path.exists()
            data = json.loads(summary_path.read_text())
            assert "M1_loop_efficiency" in data

    def test_begin_requirement_flush_previous_events_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = MetricsCollector(Path(tmp))
            c.begin_requirement("thread-1", "abc123")
            origin = AIOrigin(level="led", agent_role="architect",
                             model_name="m1", driver_type="agent")
            c.record_token_usage(
                100, 50, model="m1", provider="anthropic",
                stage="architect", ai_origin=origin,
            )
            c.begin_requirement("thread-2", "def456")
            # thread-1 events.jsonl should exist (flushed by begin_requirement)
            events_path = c._metrics_dir / "requirements" / "thread-1" / "events.jsonl"
            assert events_path.exists()
            # thread-1 should NOT have summary.json (begin_requirement doesn't compute summary)
            summary_path = c._metrics_dir / "requirements" / "thread-1" / "summary.json"
            assert not summary_path.exists()


class TestBaselineManagement:
    """Baseline management: _median, _percentile, compare_periods — F.3."""

    def test_median_odd_length(self):
        result = MetricsCollector._median([1.0, 3.0, 2.0])
        assert result == 2.0

    def test_median_even_length(self):
        result = MetricsCollector._median([1.0, 2.0, 3.0, 4.0])
        assert result == 2.5

    def test_median_single_value(self):
        assert MetricsCollector._median([5.0]) == 5.0

    def test_percentile_p95(self):
        values = list(range(1, 101))  # 1..100
        result = MetricsCollector._percentile(values, 95)
        assert 94 <= result <= 96

    def test_percentile_p50_equals_median(self):
        import random
        values = [random.uniform(0, 100) for _ in range(50)]
        p50 = MetricsCollector._percentile(values, 50)
        median = MetricsCollector._median(values)
        assert abs(p50 - median) < 1.0  # close but not always equal for even length

    def test_compare_periods_returns_before_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = MetricsCollector(Path(tmp))
            baselines_dir = c._metrics_dir / "baselines"
            baselines_dir.mkdir(parents=True, exist_ok=True)
            before = {"M1_loop_efficiency": 5.0, "M2_critic_major_rate": 0.2}
            after = {"M1_loop_efficiency": 3.0, "M2_critic_major_rate": 0.1}
            (baselines_dir / "v1.0.0.json").write_text(json.dumps(before))
            (baselines_dir / "v2.0.0.json").write_text(json.dumps(after))

            result = c.compare_periods("v1.0.0", "v2.0.0")
            assert result is not None
            assert result["before"]["M1_loop_efficiency"] == 5.0
            assert result["after"]["M1_loop_efficiency"] == 3.0

    def test_compare_periods_missing_tag_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = MetricsCollector(Path(tmp))
            result = c.compare_periods("nonexistent", "also_nonexistent")
            assert result is None

    def test_baseline_constants_defined(self):
        assert MetricsCollector.BASELINE_MIN_SAMPLES == 10
        assert MetricsCollector.BASELINE_FULL_STATS == 30


class TestCategorizedBaselines:
    """update_baseline() by_category baselines (F.2.3)."""

    def test_categorized_baselines_written_for_known_categories(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = MetricsCollector(Path(tmp))
            # Create 10 requirements with different categories
            for i in range(5):
                tid = f"thread-simple-{i}"
                c.begin_requirement(tid, f"hash{i}",
                                    requirement_category="simple_function")
                c.end_requirement("GOAL_ACHIEVED", total_ticks=3)
            for i in range(5):
                tid = f"thread-medium-{i}"
                c.begin_requirement(tid, f"hash{i}",
                                    requirement_category="medium_crud")
                c.end_requirement("GOAL_ACHIEVED", total_ticks=5)

            baseline = c.update_baseline()
            assert baseline is not None

            by_cat_dir = c._metrics_dir / "baselines" / "by_category"
            assert by_cat_dir.exists()
            simple_path = by_cat_dir / "simple_function.json"
            medium_path = by_cat_dir / "medium_crud.json"
            assert simple_path.exists()
            assert medium_path.exists()
            # complex_multi_module should NOT be written (no samples)
            complex_path = by_cat_dir / "complex_multi_module.json"
            assert not complex_path.exists()

    def test_categorized_baseline_has_correct_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = MetricsCollector(Path(tmp))
            for i in range(10):
                tid = f"thread-{i}"
                c.begin_requirement(tid, f"hash{i}",
                                    requirement_category="simple_function")
                c.end_requirement("GOAL_ACHIEVED", total_ticks=3)

            baseline = c.update_baseline()
            cat_path = c._metrics_dir / "baselines" / "by_category" / "simple_function.json"
            cat_data = json.loads(cat_path.read_text())
            assert "sample_size" in cat_data
            assert "full_stats_ready" in cat_data
            assert "M1" in cat_data
            assert "M2" in cat_data
            assert cat_data["sample_size"] == 10

    def test_unknown_category_not_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = MetricsCollector(Path(tmp))
            for i in range(10):
                tid = f"thread-{i}"
                c.begin_requirement(tid, f"hash{i}",
                                    requirement_category="unknown_type")
                c.end_requirement("GOAL_ACHIEVED", total_ticks=3)

            c.update_baseline()
            by_cat_dir = c._metrics_dir / "baselines" / "by_category"
            assert not (by_cat_dir / "unknown_type.json").exists()


class TestComputeLocAdded:
    """_compute_loc_added static method — F.3."""

    def test_returns_zero_for_no_commits(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = MetricsCollector._compute_loc_added(Path(tmp))
            assert result == 0


class TestRecordTickSnapshot:
    """record_tick_snapshot — per-tick snapshots (F.2.3)."""

    def test_writes_snapshot_to_ticks_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = MetricsCollector(Path(tmp))
            collector.begin_requirement("thread-1", "abc123")
            collector.record_tick_snapshot(
                tick_number=1, stage_in="developer",
                action={"action": "continue", "stage": "critic"},
                state_snapshot={"current_stage": "developer"},
                guardrail_results={"safety": "passed"},
                gate_results={"lint": "passed"},
                timing_ms={"t_total": 150.0},
            )
            ticks_dir = collector._metrics_dir / "requirements" / "thread-1" / "ticks"
            assert ticks_dir.exists()
            tick_file = ticks_dir / "tick-0001.json"
            assert tick_file.exists()
            data = json.loads(tick_file.read_text())
            assert data["tick"] == 1
            assert data["stage_in"] == "developer"
            assert data["action"]["action"] == "continue"

    def test_multiple_ticks_increment_properly(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = MetricsCollector(Path(tmp))
            collector.begin_requirement("thread-1", "abc123")
            for i in range(1, 4):
                collector.record_tick_snapshot(
                    tick_number=i, stage_in="developer",
                    action={}, state_snapshot={},
                    guardrail_results={}, gate_results={},
                    timing_ms={},
                )
            ticks_dir = collector._metrics_dir / "requirements" / "thread-1" / "ticks"
            assert (ticks_dir / "tick-0001.json").exists()
            assert (ticks_dir / "tick-0002.json").exists()
            assert (ticks_dir / "tick-0003.json").exists()
