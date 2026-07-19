"""T66: Token hook integration — agents/base.py + MetricsCollector."""
import tempfile
from pathlib import Path

import pytest

from auto_engineering.metrics.collector import (
    AIOrigin,
    MetricsCollector,
    get_collector,
    set_collector,
)


@pytest.fixture
def temp_collector():
    with tempfile.TemporaryDirectory() as tmp:
        c = MetricsCollector(Path(tmp))
        set_collector(c)
        yield c
        set_collector(None)


class TestCollectorGlobalAccess:
    """Module-level collector access pattern."""

    def test_set_and_get_collector(self, temp_collector):
        assert get_collector() is temp_collector

    def test_get_collector_returns_none_when_not_set(self):
        set_collector(None)
        assert get_collector() is None


class TestTokenHookInBaseAgent:
    """LLM response → collector.record_token_usage() — F.8.1."""

    def test_record_token_usage_called_after_llm_response(self, temp_collector):
        """Simulate what BaseAgent.execute() does after LLM response returns."""
        collector = temp_collector
        collector.begin_requirement("thread-t66", "hash-t66")

        usage = {"input_tokens": 1500, "output_tokens": 800}

        origin = AIOrigin(level="led", agent_role="developer",
                          model_name="claude-haiku-4-5", driver_type="agent")
        c = get_collector()
        if c is not None:
            c.record_token_usage(
                usage["input_tokens"],
                usage["output_tokens"],
                model="claude-haiku-4-5",
                provider="anthropic",
                stage="developer",
                ai_origin=origin,
            )

        events = collector._events
        token_events = [e for e in events if e["event_type"] == "token_usage"]
        assert len(token_events) == 1
        assert token_events[0]["payload"]["input_tokens"] == 1500
        assert token_events[0]["payload"]["output_tokens"] == 800

    def test_noop_when_collector_not_set(self):
        """When AE_METRICS=0 or not set, collector is None → noop."""
        set_collector(None)
        c = get_collector()
        assert c is None
        # calling record_token_usage on None should be guarded by caller

    def test_multiple_llm_calls_accumulate(self, temp_collector):
        collector = temp_collector
        collector.begin_requirement("thread-t66", "hash-t66")

        for _ in range(3):
            usage = {"input_tokens": 1000, "output_tokens": 500}
            origin = AIOrigin(level="led", agent_role="developer",
                              model_name="m1", driver_type="agent")
            c = get_collector()
            if c is not None:
                c.record_token_usage(
                    usage["input_tokens"], usage["output_tokens"],
                    model="m1", provider="anthropic",
                    stage="developer", ai_origin=origin,
                )

        token_events = [
            e for e in collector._events if e["event_type"] == "token_usage"
        ]
        assert len(token_events) == 3
        total_input = sum(e["payload"]["input_tokens"] for e in token_events)
        total_output = sum(e["payload"]["output_tokens"] for e in token_events)
        assert total_input == 3000
        assert total_output == 1500
