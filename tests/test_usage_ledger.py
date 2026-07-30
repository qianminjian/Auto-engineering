"""v5.8 T316：逐 Tick Usage Ledger。"""

from __future__ import annotations

from auto_engineering.config.runtime_config import RuntimeConfig
from auto_engineering.engine.state import EngineState
from auto_engineering.loop.tick_orchestrator import TickOrchestrator
from auto_engineering.metrics.usage_ledger import UsageLedger, UsageRecord


def test_usage_ledger_preserves_all_attribution_dimensions(tmp_path) -> None:
    ledger = UsageLedger(tmp_path / "usage.db")
    record = UsageRecord(
        thread_id="thread-1",
        session_id="session-2",
        tick=42,
        stage="developer",
        worker="main",
        input_units=100,
        cache_read_units=300,
        cache_write_units=20,
        output_units=10,
        provider="anthropic",
        model="claude",
        usage_source="claude-transcript",
        estimated=False,
    )

    ledger.append(record)

    assert ledger.list_records("thread-1") == [record]
    totals = ledger.aggregate("thread-1")
    assert totals["input_units"] == 100
    assert totals["cache_read_units"] == 300
    assert totals["cache_write_units"] == 20
    assert totals["output_units"] == 10
    assert totals["measurement_complete"] is False
    assert totals["attributed_records"] == 1
    ledger.close()


def test_unknown_usage_remains_null_not_zero(tmp_path) -> None:
    ledger = UsageLedger(tmp_path / "usage.db")
    ledger.append(UsageRecord(
        thread_id="thread-1",
        session_id="session-1",
        tick=1,
        stage="architect",
        worker="architect",
        input_units=None,
        cache_read_units=None,
        cache_write_units=None,
        output_units=None,
        provider="unknown",
        model="unknown",
        usage_source="unsupported",
        estimated=True,
    ))

    restored = ledger.list_records("thread-1")[0]
    totals = ledger.aggregate("thread-1")

    assert restored.input_units is None
    assert restored.cache_read_units is None
    assert totals["unknown_records"] == 1
    assert totals["attribution_rate"] == 1.0
    ledger.close()


def test_ledger_survives_process_reopen(tmp_path) -> None:
    path = tmp_path / "usage.db"
    first = UsageLedger(path)
    first.append(UsageRecord(
        thread_id="thread-1",
        session_id="session-1",
        tick=1,
        stage="critic",
        worker="critic-0",
        input_units=12,
        cache_read_units=None,
        cache_write_units=None,
        output_units=3,
        provider="openai",
        model="gpt",
        usage_source="host-native",
        estimated=False,
    ))
    first.close()

    second = UsageLedger(path)
    assert len(second.list_records("thread-1")) == 1
    second.close()


def test_tick_usage_is_written_with_session_and_cache_attribution(tmp_path) -> None:
    class Parser:
        @staticmethod
        def collect():
            return {
                "input_tokens": 10,
                "cache_read_tokens": 30,
                "cache_write_tokens": 4,
                "output_tokens": 2,
                "provider": "anthropic",
                "model": "claude",
                "usage_source": "claude-transcript",
            }

    orchestrator = TickOrchestrator(
        project_root=tmp_path,
        runtime_config=RuntimeConfig(environ={
            "AE_TOKEN_TRACKING": "1",
            "AE_METRICS": "1",
        }),
        transcript_parser=Parser(),
    )
    orchestrator._state = EngineState(
        thread_id="thread-1",
        current_stage="developer",
        tick=7,
        execution_session_id="session-2",
    )

    orchestrator._collect_token_usage()

    ledger = UsageLedger(tmp_path / ".ae-state" / "usage-ledger.db")
    record = ledger.list_records("thread-1")[0]
    assert record.session_id == "session-2"
    assert record.cache_read_units == 30
    assert record.cache_write_units == 4
    assert record.core_payload_bytes == 2
    assert orchestrator._state.session_input_units == 10
    ledger.close()
