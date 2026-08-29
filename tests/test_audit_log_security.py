"""审计日志默认最小化、脱敏且有界。"""

from __future__ import annotations

import json

from auto_engineering.observability.audit_log import AuditLogger


def test_audit_log_default_does_not_persist_request_or_response_payload(tmp_path) -> None:
    logger = AuditLogger(tmp_path)
    logger.log_call(
        stage="developer",
        provider="codex",
        model="gpt-5",
        request_messages=[{"role": "user", "content": "SECRET-PROMPT"}],
        request_tools=None,
        response={"content": "SECRET-RESPONSE", "usage": {"total_tokens": 3}},
    )

    raw = (tmp_path / "llm-calls.jsonl").read_text(encoding="utf-8")
    assert "SECRET-PROMPT" not in raw
    assert "SECRET-RESPONSE" not in raw
    entry = json.loads(raw)
    assert entry["request"]["messages_count"] == 1
    assert entry["request"]["payload_sha256"]
    assert entry["response"]["payload_sha256"]


def test_audit_log_full_payload_requires_explicit_debug_opt_in(tmp_path) -> None:
    logger = AuditLogger(tmp_path, debug_full=True)
    logger.log_call(
        stage="developer",
        provider="codex",
        model="gpt-5",
        request_messages=[{"role": "user", "content": "DEBUG-ONLY"}],
        request_tools=None,
        response={"content": "DEBUG-RESPONSE"},
    )

    raw = (tmp_path / "llm-calls.jsonl").read_text(encoding="utf-8")
    assert "DEBUG-ONLY" in raw
    assert "DEBUG-RESPONSE" in raw


def test_audit_log_bounds_large_full_payload(tmp_path) -> None:
    logger = AuditLogger(tmp_path, debug_full=True, max_entry_bytes=512)
    logger.log_call(
        stage="developer",
        provider="codex",
        model="gpt-5",
        request_messages=[{"role": "user", "content": "X" * 10_000}],
        request_tools=None,
        response={"content": "Y" * 10_000},
    )

    line = (tmp_path / "llm-calls.jsonl").read_bytes().splitlines()[0]
    assert len(line) <= 512
    assert json.loads(line)["bounded"] is True


def test_audit_log_rotates_when_file_retention_limit_is_reached(tmp_path) -> None:
    logger = AuditLogger(tmp_path, max_entry_bytes=512, max_log_bytes=700)
    for _ in range(4):
        logger.log_event(event="tick", payload="Z" * 200)

    assert (tmp_path / "llm-calls.jsonl").stat().st_size <= 700
    assert (tmp_path / "llm-calls.jsonl.1").is_file()
