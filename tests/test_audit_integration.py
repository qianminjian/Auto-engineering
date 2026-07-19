"""T77 Integration tests — AuditLogger wired into AnthropicProvider.create_message().

Test layers:
  Layer 1 (Unit) — existing tests in test_audit_log.py
  Layer 2 (Integration) — AnthropicProvider accepts AuditLogger + calls log_call()
  Layer 3 (E2E) — full create_message cycle records audit entry to disk

RED phase: These tests FAIL because:
  - AnthropicProvider.__init__() does not accept audit_logger
  - create_message() does not call AuditLogger.log_call()

Design ref: v5.6-Design-Loop.md appendix E §E.6.2 (T61).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from auto_engineering.observability.audit_log import AuditLogger


class TestAuditLoggerWiring:
    """T77: Verify AuditLogger is wired into AnthropicProvider.create_message()."""

    def test_provider_accepts_audit_logger(self, tmp_path: Path) -> None:
        """AnthropicProvider MUST accept an optional AuditLogger."""
        from auto_engineering.llm.anthropic_provider import AnthropicProvider

        audit_logger = AuditLogger(tmp_path / "audit")
        provider = AnthropicProvider(audit_logger=audit_logger)
        assert provider._audit_logger is not None
        assert isinstance(provider._audit_logger, AuditLogger)

    def test_provider_has_audit_logger_attribute_default_none(self) -> None:
        """Without explicit audit_logger, _audit_logger should be None."""
        from auto_engineering.llm.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider()
        assert hasattr(provider, "_audit_logger"), (
            "T77 NOT WIRED: AnthropicProvider has no _audit_logger attribute"
        )

    def test_create_message_calls_audit_logger(self, tmp_path: Path) -> None:
        """create_message() MUST call audit_logger.log_call() with request/response."""
        from auto_engineering.llm.anthropic_provider import AnthropicProvider
        from auto_engineering.llm.anthropic_provider import LLMResponse, LLMUsage

        audit_logger = AuditLogger(tmp_path / "audit")
        # Build a mock anthropic client that returns a valid response
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(type="text", text="Hello from Claude")]
        mock_message.model = "claude-sonnet-4-6"
        mock_message.stop_reason = "end_turn"
        mock_message.usage = MagicMock(
            input_tokens=10, output_tokens=5,
        )
        mock_client.messages.create.return_value = mock_message

        provider = AnthropicProvider(client=mock_client, audit_logger=audit_logger)
        provider.create_message(
            model="claude-sonnet-4-6",
            max_tokens=100,
            system="You are helpful.",
            messages=[{"role": "user", "content": "Hello"}],
        )

        log_file = tmp_path / "audit" / "llm-calls.jsonl"
        assert log_file.exists(), (
            "T77 NOT WIRED: create_message() did not call AuditLogger.log_call(). "
            "No audit log file was created."
        )
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["stage"] == "llm_call"
        assert entry["provider"] == "anthropic"
        assert entry["model"] == "claude-sonnet-4-6"
        assert "request" in entry
        assert "response" in entry
        assert entry["request"]["messages_count"] == 1

    def test_create_message_no_audit_when_logger_not_set(self) -> None:
        """When audit_logger is None, create_message() should not throw."""
        from auto_engineering.llm.anthropic_provider import AnthropicProvider
        from auto_engineering.llm.anthropic_provider import LLMResponse, LLMUsage

        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(type="text", text="OK")]
        mock_message.model = "claude-sonnet-4-6"
        mock_message.stop_reason = "end_turn"
        mock_message.usage = MagicMock(input_tokens=1, output_tokens=1)
        mock_client.messages.create.return_value = mock_message

        provider = AnthropicProvider(client=mock_client)
        # Should not throw
        result = provider.create_message(
            model="claude-sonnet-4-6",
            max_tokens=100,
            system="You are helpful.",
            messages=[{"role": "user", "content": "Hi"}],
        )
        assert result is not None

    def test_audit_log_entry_contains_timing(self, tmp_path: Path) -> None:
        """Audit log entry MUST contain duration_ms and token counts."""
        from auto_engineering.llm.anthropic_provider import AnthropicProvider

        audit_logger = AuditLogger(tmp_path / "audit")
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(type="text", text="Response")]
        mock_message.model = "claude-sonnet-4-6"
        mock_message.stop_reason = "end_turn"
        mock_message.usage = MagicMock(input_tokens=50, output_tokens=25)
        mock_client.messages.create.return_value = mock_message

        provider = AnthropicProvider(client=mock_client, audit_logger=audit_logger)
        provider.create_message(
            model="claude-sonnet-4-6",
            max_tokens=200,
            system="You are helpful.",
            messages=[{"role": "user", "content": "Test"}],
        )

        log_file = tmp_path / "audit" / "llm-calls.jsonl"
        entry = json.loads(log_file.read_text().strip().split("\n")[0])
        assert "duration_ms" in entry
        assert isinstance(entry["duration_ms"], int)
        assert entry["tokens"]["prompt"] == 50
        assert entry["tokens"]["completion"] == 25
        assert entry["tokens"]["total"] == 75


class TestAuditLoggerE2E:
    """E2E: audit log persists correctly across multiple calls."""

    def test_multiple_calls_append_to_same_log(self, tmp_path: Path) -> None:
        """Multiple create_message calls append to the same JSONL file."""
        from auto_engineering.llm.anthropic_provider import AnthropicProvider

        audit_logger = AuditLogger(tmp_path / "audit")
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(type="text", text="R")]
        mock_message.model = "claude-sonnet-4-6"
        mock_message.stop_reason = "end_turn"
        mock_message.usage = MagicMock(input_tokens=1, output_tokens=1)
        mock_client.messages.create.return_value = mock_message

        provider = AnthropicProvider(client=mock_client, audit_logger=audit_logger)

        for i in range(3):
            provider.create_message(
                model="claude-sonnet-4-6",
                max_tokens=100,
                system="You are helpful.",
                messages=[{"role": "user", "content": f"Call {i}"}],
            )

        log_file = tmp_path / "audit" / "llm-calls.jsonl"
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 3, (
            f"Expected 3 audit entries, got {len(lines)}"
        )
