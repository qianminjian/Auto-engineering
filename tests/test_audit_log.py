"""Tests for auto_engineering.observability.audit_log — structured audit log (T61)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from auto_engineering.observability.audit_log import AuditLogger


class TestAuditLogger:
    """AuditLogger — JSONL structured LLM call audit log."""

    @pytest.fixture
    def log_dir(self) -> Path:
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_creates_log_file_on_first_call(self, log_dir: Path) -> None:
        """First log_call() creates the JSONL file and directory."""
        logger = AuditLogger(log_dir / "audit")
        logger.log_call(
            stage="architect",
            provider="anthropic",
            model="claude-sonnet-4-6",
            request_messages=[{"role": "user", "content": "Hello"}],
            request_tools=None,
            response={"content": "Hi", "model": "claude-sonnet-4-6"},
        )
        log_path = log_dir / "audit" / "llm-calls.jsonl"
        assert log_path.exists()

    def test_log_call_writes_jsonl_entry(self, log_dir: Path) -> None:
        """Each log_call() writes one JSON line to the file."""
        logger = AuditLogger(log_dir / "audit")
        logger.log_call(
            stage="developer",
            provider="anthropic",
            model="claude-sonnet-4-6",
            request_messages=[{"role": "user", "content": "Write code"}],
            request_tools=None,
            response={"content": "```python\nprint(1)\n```"},
            timestamp="2026-07-19T10:00:00",
            duration_ms=1234,
            tokens_prompt=100,
            tokens_completion=50,
        )
        log_path = log_dir / "audit" / "llm-calls.jsonl"
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["stage"] == "developer"
        assert entry["provider"] == "anthropic"
        assert entry["model"] == "claude-sonnet-4-6"
        assert entry["timestamp"] == "2026-07-19T10:00:00"
        assert entry["duration_ms"] == 1234
        assert entry["tokens"]["prompt"] == 100
        assert entry["tokens"]["completion"] == 50
        assert entry["tokens"]["total"] == 150
        assert entry["request"]["messages_count"] == 1
        assert entry["request"]["tools_count"] == 0

    def test_log_call_stores_full_request_messages(self, log_dir: Path) -> None:
        """Request messages are stored in full, not truncated."""
        logger = AuditLogger(log_dir / "audit")
        messages = [
            {"role": "user", "content": "A" * 1000},
            {"role": "assistant", "content": "B" * 2000},
        ]
        logger.log_call(
            stage="architect",
            provider="openai",
            model="gpt-4",
            request_messages=messages,
            request_tools=None,
            response={"content": "OK"},
        )
        log_path = log_dir / "audit" / "llm-calls.jsonl"
        entry = json.loads(log_path.read_text().strip())
        assert len(entry["request"]["messages"]) == 2
        assert entry["request"]["messages"][0]["content"] == "A" * 1000

    def test_log_call_stores_full_response(self, log_dir: Path) -> None:
        """Response is stored in full."""
        logger = AuditLogger(log_dir / "audit")
        response = {
            "content": [{"type": "text", "text": "OK"}],
            "model": "gpt-4",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        logger.log_call(
            stage="critic",
            provider="openai",
            model="gpt-4",
            request_messages=[{"role": "user", "content": "Review"}],
            request_tools=None,
            response=response,
        )
        log_path = log_dir / "audit" / "llm-calls.jsonl"
        entry = json.loads(log_path.read_text().strip())
        assert entry["response"]["model"] == "gpt-4"
        assert entry["response"]["usage"]["prompt_tokens"] == 10

    def test_multiple_calls_append(self, log_dir: Path) -> None:
        """Multiple log_call() invocations append lines to the same file."""
        logger = AuditLogger(log_dir / "audit")
        for i in range(5):
            logger.log_call(
                stage="developer",
                provider="anthropic",
                model="claude-sonnet-4-6",
                request_messages=[{"role": "user", "content": f"Msg {i}"}],
                request_tools=None,
                response={"content": f"Resp {i}"},
            )
        log_path = log_dir / "audit" / "llm-calls.jsonl"
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 5
        for line in lines:
            json.loads(line)  # all valid JSON

    def test_timestamp_auto_generated(self, log_dir: Path) -> None:
        """When timestamp is not provided, one is auto-generated."""
        logger = AuditLogger(log_dir / "audit")
        logger.log_call(
            stage="architect",
            provider="anthropic",
            model="claude-sonnet-4-6",
            request_messages=[{"role": "user", "content": "Hi"}],
            request_tools=None,
            response={"content": "Hello"},
        )
        log_path = log_dir / "audit" / "llm-calls.jsonl"
        entry = json.loads(log_path.read_text().strip())
        assert entry["timestamp"]  # non-empty

    def test_tools_count_reflects_tools(self, log_dir: Path) -> None:
        """tools_count matches the number of tools passed."""
        logger = AuditLogger(log_dir / "audit")
        tools = [
            {"name": "bash", "description": "Run command", "input_schema": {"type": "object", "properties": {}}},
            {"name": "edit", "description": "Edit file", "input_schema": {"type": "object", "properties": {}}},
        ]
        logger.log_call(
            stage="developer",
            provider="anthropic",
            model="claude-sonnet-4-6",
            request_messages=[{"role": "user", "content": "Test"}],
            request_tools=tools,
            response={"content": "Done"},
        )
        log_path = log_dir / "audit" / "llm-calls.jsonl"
        entry = json.loads(log_path.read_text().strip())
        assert entry["request"]["tools_count"] == 2
