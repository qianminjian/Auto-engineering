"""MetricsCollector integration and end-to-end telemetry pipeline."""
import tempfile
from pathlib import Path

import pytest

from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.events import LoopEvent, LoopEventType
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


class TestCollectorNotLeaked:
    """Verify that autouse fixture resets collector state."""

    def test_no_collector_after_test(self):
        assert get_collector() is None


class TestE2EPipeline:
    """P2-4: EventStore projection → summary → diagnosis.

    Verifies the derived data flow: metric projection → summary.json →
    SignalDetector.analyze() → Diagnoser.diagnose() → human_actions present.
    """

    def test_full_pipeline_events_to_diagnosis(self):

        from auto_engineering.metrics.diagnoser import Diagnoser
        from auto_engineering.metrics.signals import SignalDetector

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with SQLiteEventStore(root / "events.db") as store:
                collector = MetricsCollector(project_root=root, event_store=store)

                # Simulate a requirement lifecycle through canonical facts.
                collector.begin_requirement(
                    "thread-001", "abc123def456",
                    requirement_category="medium_crud",
                )

                for i in range(8):
                    store.append([LoopEvent.create(
                        thread_id="thread-001",
                        sequence=store.next_sequence("thread-001"),
                        event_type=LoopEventType.ACTION_ISSUED,
                        payload={"action": {
                            "action": "spawn", "message_id": f"a-{i}",
                            "thread_id": "thread-001", "tick": i + 1,
                            "stage": f"stage_{i}",
                        }},
                        correlation_id="thread-001",
                    )])
                    store.append([LoopEvent.create(
                        thread_id="thread-001",
                        sequence=store.next_sequence("thread-001"),
                        event_type=LoopEventType.USAGE_RECORDED,
                        payload={"usage": {
                            "input_units": 2000, "output_units": 500,
                            "stage": f"stage_{i}", "worker": "main",
                            "session_id": "session-1", "provider": "test",
                            "model": "test-model", "usage_source": "test",
                            "estimated": False,
                        }},
                        correlation_id="thread-001",
                    )])

                store.append([LoopEvent.create(
                    thread_id="thread-001",
                    sequence=store.next_sequence("thread-001"),
                    event_type=LoopEventType.LOOP_COMPLETED,
                    payload={"verdict": "GOAL_ACHIEVED", "tick": 8},
                    correlation_id="thread-001",
                )])

                # End requirement → write only the derived summary to disk
                summary = collector.end_requirement("GOAL_ACHIEVED", total_ticks=8, loc_added=200)
                assert summary is not None
                assert "M1_loop_efficiency" in summary

                # A parallel metric event log must never be written.
                events_path = root / ".ae-state" / "metrics" / "requirements" / "thread-001" / "events.jsonl"
                assert not events_path.exists()

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
                        assert hasattr(d, "human_actions")
                        assert isinstance(d.human_actions, list)

            # Pipeline verification: projection → summary.json → load_history →
            # analyze → diagnose all completed without crash. Specific signal counts
            # depend on cold-start thresholds; this test guards the data flow.
