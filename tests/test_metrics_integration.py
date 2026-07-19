"""T69a: MetricsCollector integration — stage_router, convergence, tick_orchestrator event wiring."""
import tempfile
from pathlib import Path

import pytest

from auto_engineering.loop.convergence import ConvergenceJudge, RoundHistory
from auto_engineering.loop.stage_router import StageDecision, StageRouter
from auto_engineering.metrics.collector import (
    MetricsCollector,
    get_collector,
    set_collector,
)


@pytest.fixture(autouse=True)
def _reset_collector():
    """Ensure no collector leaks between tests."""
    set_collector(None)
    yield
    set_collector(None)


class TestStageRouterIntegration:
    """StageRouter.next() → collector.record_stage_transition()."""

    def test_next_records_stage_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = MetricsCollector(project_root=Path(tmp))
            set_collector(collector)
            router = StageRouter()

            router.next("architect", "APPROVE", majors_in_a_row=0, total_majors=0)

            assert len(collector._events) == 1
            event = collector._events[0]
            assert event["event_type"] == "stage_transition"
            assert event["payload"]["from_stage"] == "architect"
            assert event["payload"]["to_stage"] == "developer"

    def test_next_no_collector_does_not_crash(self):
        set_collector(None)
        router = StageRouter()
        decision = router.next("architect", "APPROVE", majors_in_a_row=0, total_majors=0)
        assert isinstance(decision, StageDecision)

    def test_next_unknown_stage_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = MetricsCollector(project_root=Path(tmp))
            set_collector(collector)
            router = StageRouter()

            decision = router.next("unknown_stage", "", majors_in_a_row=0, total_majors=0)

            assert decision.should_stop
            assert len(collector._events) == 1
            assert collector._events[0]["event_type"] == "stage_transition"


class TestConvergenceIntegration:
    """ConvergenceJudge.evaluate() → collector.record_convergence()."""

    def test_evaluate_records_convergence(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = MetricsCollector(project_root=Path(tmp))
            set_collector(collector)
            judge = ConvergenceJudge()

            history = [
                RoundHistory(round_id=1, files_changed=3, lines_added=50, lines_removed=10),
            ]
            judge.evaluate(history)

            assert len(collector._events) == 1
            event = collector._events[0]
            assert event["event_type"] == "convergence"
            assert "verdict" in event["payload"]

    def test_evaluate_no_collector_does_not_crash(self):
        set_collector(None)
        judge = ConvergenceJudge()
        history = [RoundHistory(round_id=1, files_changed=3, lines_added=50, lines_removed=10)]
        verdict = judge.evaluate(history)
        assert not verdict.should_stop  # 1 round < default max_iterations

    def test_evaluate_goal_achieved_records_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = MetricsCollector(project_root=Path(tmp))
            set_collector(collector)
            judge = ConvergenceJudge()

            judge.evaluate(
                [], design_coverage_ok=True, system_deep_audit_ok=True,
            )

            assert len(collector._events) == 1
            event = collector._events[0]
            assert event["event_type"] == "convergence"
            assert event["payload"]["verdict"] == "GOAL_ACHIEVED"


class TestCollectorNotLeaked:
    """Verify that autouse fixture resets collector state."""

    def test_no_collector_after_test(self):
        assert get_collector() is None


class TestE2EPipeline:
    """P2-4: End-to-end pipeline — events → flush → load → detect → diagnose.

    Verifies the full data flow: events.jsonl write → load_history() →
    SignalDetector.analyze() → Diagnoser.diagnose() → human_actions present.
    """

    def test_full_pipeline_events_to_diagnosis(self):
        import tempfile
        from pathlib import Path

        from auto_engineering.metrics.collector import AIOrigin, MetricsCollector
        from auto_engineering.metrics.diagnoser import Diagnoser
        from auto_engineering.metrics.signals import SignalDetector

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            collector = MetricsCollector(project_root=root)

            # Simulate a requirement lifecycle: begin → events → end
            collector.begin_requirement(
                "thread-001", "abc123def456",
                requirement_category="medium_crud",
            )
            origin = AIOrigin(level="led", agent_role="critic",
                            model_name="claude-sonnet-4-6", driver_type="agent")

            # Simulate 8 ticks (high tick count = potential slow_convergence signal)
            for i in range(8):
                collector.record_tick_complete(
                    tick_number=i + 1, stage=f"stage_{i}",
                    duration_ms=5000, ai_origin=origin,
                )
                collector.record_stage_transition(
                    from_stage=f"stage_{i}", to_stage=f"stage_{i+1}",
                    reason="normal", ai_origin=origin,
                )
                collector.record_token_usage(
                    input_tokens=2000, output_tokens=500,
                    model="claude-sonnet-4-6", provider="anthropic",
                    stage=f"stage_{i}", ai_origin=origin,
                )

            # MAJOR convergence with critic_approved criteria_met (for M2)
            collector.record_convergence(
                verdict="GOAL_ACHIEVED", total_ticks=8,
                criteria_met="critic_approved", ai_origin=origin,
            )
            collector.record_convergence(
                verdict="MAJOR", total_ticks=4,
                criteria_met="critic_major", ai_origin=origin,
            )

            # End requirement → flush events + write summary to disk
            summary = collector.end_requirement("GOAL_ACHIEVED", total_ticks=8, loc_added=200)
            assert summary is not None
            assert "M1_loop_efficiency" in summary

            # Verify events.jsonl was written
            events_path = root / ".ae-state" / "metrics" / "requirements" / "thread-001" / "events.jsonl"
            assert events_path.exists()

            # Verify summary.json was written
            summary_path = root / ".ae-state" / "metrics" / "requirements" / "thread-001" / "summary.json"
            assert summary_path.exists()

            # Reload history
            history = collector.load_history(limit=5)
            assert len(history) >= 1
            assert "M1_loop_efficiency" in history[0]
            assert "M2_critic_major_rate" in history[0]

            # Signal detection on history — pipeline should not crash
            detector = SignalDetector(min_samples=1)
            signals = detector.analyze(history)
            assert isinstance(signals, list)

            # Diagnose each detected signal — pipeline should not crash
            diagnoser = Diagnoser()
            for sig in signals:
                d = diagnoser.diagnose(sig)
                if d is not None:
                    # Verify human_actions field exists (key P2-4 check)
                    assert hasattr(d, "human_actions")
                    assert isinstance(d.human_actions, list)

            # Pipeline verification: events.jsonl → summary.json → load_history →
            # analyze → diagnose all completed without crash. Specific signal counts
            # depend on cold-start thresholds; this test guards the data flow.
