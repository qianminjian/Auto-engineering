"""宿主会话异常结束与 Stop Report 的回归测试。"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

from auto_engineering.host.claude_hooks import main
from auto_engineering.host.runtime_driver import (
    HostRunLease,
    HostRunLeaseStore,
    fencing_token_for,
)


def _save_lease(
    root: Path,
    *,
    session_id: str = "session-1",
    disposition: str = "CONTINUE",
    continuation_required: bool = True,
    yield_allowed: bool = False,
) -> HostRunLease:
    lease = HostRunLease(
        schema_version="1.0",
        thread_id="thread-1",
        action_message_id="action-1",
        platform="claude-code",
        host_session_id=session_id,
        build_id="build-1",
        disposition=disposition,
        continuation_required=continuation_required,
        yield_allowed=yield_allowed,
    )
    HostRunLeaseStore(root).save(lease)
    return lease


def test_session_end_records_report_and_clears_same_session_continue_lease(
    tmp_path: Path,
) -> None:
    _save_lease(tmp_path)
    output = StringIO()

    assert main(
        StringIO(json.dumps({
            "hook_event_name": "SessionEnd",
            "cwd": str(tmp_path),
            "session_id": "session-1",
            "reason": "budget_exceeded",
            "transcript_path": "/private/sensitive/transcript.jsonl",
        })),
        output,
    ) == 0

    response = json.loads(output.getvalue())
    assert response["reason_code"] == "HOST_RUNTIME_PROTOCOL_ERROR"
    assert response["lease_cleared"] is True
    assert HostRunLeaseStore(tmp_path).load() is None

    report_path = tmp_path / response["stop_report_path"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report == {
        "action_message_id": "action-1",
        "build_id": "build-1",
        "disposition": "CONTINUE",
        "host_session_id": "session-1",
        "last_host_observation": {
            "event": "SessionEnd",
            "reason": "budget_exceeded",
        },
        "lease_cleared": True,
        "next_operation": {
            "argv": ["dev-loop", "--resume", "thread-1"],
            "operation": "resume_active_action",
            "thread_id": "thread-1",
        },
        "continuation": {
            "action_identity": {
                "execution_generation": 1,
                "fencing_token": fencing_token_for("action-1", "session-1", 1),
                "message_id": "action-1",
                "thread_id": "thread-1",
            },
            "after_host_return": "recheck_core_status",
            "forbidden_success_when": ["CONTINUE", "active_action_present"],
            "resume_only_when": ["status.execution_control.disposition=CONTINUE"],
            "resume_operation": {
                "argv": ["dev-loop", "--resume", "thread-1"],
                "operation": "resume_active_action",
            },
            "schema_version": "1.0",
            "status_operation": {
                "argv": ["dev-loop", "--status", "--format", "json"],
                "operation": "recheck_core_status",
            },
        },
        "platform": "claude-code",
        "reason_code": "HOST_RUNTIME_PROTOCOL_ERROR",
        "schema_version": "1.0",
        "termination_category": "session_ended_with_continue",
        "thread_id": "thread-1",
    }
    assert "transcript" not in report_path.read_text(encoding="utf-8")


def test_session_end_preserves_continue_lease_for_auto_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save_lease(tmp_path)
    monkeypatch.setenv("AE_HOST_ADAPTER_AUTO_RESUME", "1")
    output = StringIO()

    assert main(
        StringIO(json.dumps({
            "hook_event_name": "SessionEnd",
            "cwd": str(tmp_path),
            "session_id": "session-1",
            "reason": "budget_exceeded",
        })),
        output,
    ) == 0

    response = json.loads(output.getvalue())
    assert response["lease_cleared"] is False
    assert HostRunLeaseStore(tmp_path).load() is not None
    report_path = tmp_path / response["stop_report_path"]
    assert json.loads(report_path.read_text(encoding="utf-8"))["lease_cleared"] is False


def test_session_end_clears_terminal_lease_without_protocol_error(
    tmp_path: Path,
) -> None:
    _save_lease(
        tmp_path,
        disposition="TERMINAL",
        continuation_required=False,
        yield_allowed=True,
    )
    output = StringIO()

    assert main(
        StringIO(json.dumps({
            "hook_event_name": "SessionEnd",
            "cwd": str(tmp_path),
            "session_id": "session-1",
            "reason": "completed",
        })),
        output,
    ) == 0

    response = json.loads(output.getvalue())
    assert response["systemMessage"] == "Auto-Engineering 宿主会话已结束"
    assert "reason_code" not in response
    assert HostRunLeaseStore(tmp_path).load() is None
    reports = list((tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json"))
    assert reports == []


def test_session_end_does_not_touch_lease_owned_by_another_session(
    tmp_path: Path,
) -> None:
    _save_lease(tmp_path, session_id="session-owner")
    lease = HostRunLeaseStore(tmp_path).load()
    assert lease is not None
    output = StringIO()

    assert main(
        StringIO(json.dumps({
            "hook_event_name": "SessionEnd",
            "cwd": str(tmp_path),
            "session_id": "session-other",
            "reason": "interrupted",
        })),
        output,
    ) == 0

    response = json.loads(output.getvalue())
    assert response["systemMessage"] == "Auto-Engineering 宿主会话已结束"
    assert HostRunLeaseStore(tmp_path).load() == lease


def test_session_end_observation_is_bounded_and_allowlisted(tmp_path: Path) -> None:
    _save_lease(tmp_path)
    output = StringIO()
    long_reason = "x" * 500

    assert main(
        StringIO(json.dumps({
            "hook_event_name": "SessionEnd",
            "cwd": str(tmp_path),
            "session_id": "session-1",
            "reason": long_reason,
            "secret": "must-not-be-recorded",
            "last_host_receipt": {"raw": "must-not-be-recorded"},
        })),
        output,
    ) == 0

    response = json.loads(output.getvalue())
    report_path = tmp_path / response["stop_report_path"]
    report_text = report_path.read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert len(report["last_host_observation"]["reason"]) == 128
    assert "must-not-be-recorded" not in report_text


def test_stop_failure_records_protocol_report_for_continue_lease(tmp_path: Path) -> None:
    _save_lease(tmp_path)
    output = StringIO()

    assert main(
        StringIO(json.dumps({
            "hook_event_name": "StopFailure",
            "cwd": str(tmp_path),
            "session_id": "session-1",
            "reason": "budget_exhausted",
        })),
        output,
    ) == 0

    response = json.loads(output.getvalue())
    assert response["reason_code"] == "HOST_RUNTIME_PROTOCOL_ERROR"
    assert HostRunLeaseStore(tmp_path).load() is None
    report_path = tmp_path / response["stop_report_path"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["termination_category"] == "host_action_failed_with_continue"
    assert report["last_host_observation"]["event"] == "StopFailure"
