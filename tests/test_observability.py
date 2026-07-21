"""Observability smoke tests — setup_tracing + AuditLogger.

P1-13: observability 模块零测试覆盖，补充 smoke tests。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from auto_engineering.observability.audit_log import AuditLogger
from auto_engineering.observability.tracing import setup_tracing


class TestSetupTracing:
    """Smoke tests for setup_tracing()."""

    def test_no_endpoint_returns_tracer(self):
        """Without OTLP endpoint, returns a tracer-like object (NoOp)."""
        tracer = setup_tracing(service_name="test-ae")
        assert hasattr(tracer, "start_as_current_span")
        assert callable(tracer.start_as_current_span)

    @patch("opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter")
    @patch("opentelemetry.sdk.trace.TracerProvider")
    @patch("opentelemetry.sdk.trace.export.BatchSpanProcessor")
    @patch("opentelemetry.sdk.resources.Resource")
    def test_with_endpoint_initializes_sdk(
        self, mock_resource, mock_bsp, mock_provider, mock_exporter
    ):
        """With OTLP endpoint, initializes the full SDK pipeline."""
        tracer = setup_tracing(
            service_name="test-ae",
            otlp_endpoint="http://localhost:4317",
        )
        assert hasattr(tracer, "start_as_current_span")
        mock_resource.create.assert_any_call(
            attributes={"service.name": "test-ae"}
        )
        mock_provider.assert_called_once()
        mock_exporter.assert_called_once_with(endpoint="http://localhost:4317")


class TestAuditLogger:
    """Smoke tests for AuditLogger."""

    def test_log_call_writes_jsonl(self, tmp_path: Path):
        """log_call appends a JSON line to llm-calls.jsonl."""
        log_dir = tmp_path / "logs"
        logger = AuditLogger(log_dir)

        logger.log_call(
            stage="architect",
            provider="anthropic",
            model="claude-sonnet-4-6",
            request_messages=[{"role": "user", "content": "hello"}],
            request_tools=None,
            response={"content": "hi", "model": "claude-sonnet-4-6"},
            timestamp="2026-07-21T00:00:00",
            duration_ms=150,
            tokens_prompt=10,
            tokens_completion=5,
        )

        log_path = log_dir / "llm-calls.jsonl"
        assert log_path.exists()
        with open(log_path) as f:
            entry = json.loads(f.readline())
        assert entry["stage"] == "architect"
        assert entry["provider"] == "anthropic"
        assert entry["model"] == "claude-sonnet-4-6"
        assert entry["tokens"]["prompt"] == 10
        assert entry["tokens"]["completion"] == 5
        assert entry["tokens"]["total"] == 15
        assert entry["duration_ms"] == 150

    def test_log_event_writes_jsonl(self, tmp_path: Path):
        """log_event appends a JSON line with event metadata."""
        log_dir = tmp_path / "logs"
        logger = AuditLogger(log_dir)

        logger.log_event(
            event="gate_run",
            stage="developer",
            tick=3,
            gate_name="safety",
            passed=True,
        )

        log_path = log_dir / "llm-calls.jsonl"
        assert log_path.exists()
        with open(log_path) as f:
            entry = json.loads(f.readline())
        assert entry["event"] == "gate_run"
        assert entry["stage"] == "developer"
        assert entry["tick"] == 3
        assert entry["gate_name"] == "safety"
        assert entry["passed"] is True

    def test_log_call_appends_to_existing(self, tmp_path: Path):
        """Multiple log_call calls append lines, not overwrite."""
        log_dir = tmp_path / "logs"
        logger = AuditLogger(log_dir)

        for i in range(3):
            logger.log_call(
                stage=f"stage_{i}",
                provider="test",
                model="test",
                request_messages=[],
                request_tools=None,
                response={},
            )

        with open(log_dir / "llm-calls.jsonl") as f:
            lines = f.readlines()
        assert len(lines) == 3

    def test_log_dir_created_if_missing(self, tmp_path: Path):
        """AuditLogger creates the log directory if it doesn't exist."""
        log_dir = tmp_path / "nonexistent" / "logs"
        assert not log_dir.exists()
        AuditLogger(log_dir)
        assert log_dir.exists()
