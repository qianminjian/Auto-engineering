"""v5.8 T308：ExecutionSession 事件与投影契约。"""

from __future__ import annotations

import pytest

from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.session import (
    ExecutionSession,
    SessionProjection,
    SessionProjectionError,
    SessionStatus,
)


def _event(sequence: int, event_type: LoopEventType, payload: dict) -> LoopEvent:
    return LoopEvent.create(
        thread_id="thread-1",
        sequence=sequence,
        event_type=event_type,
        payload=payload,
        correlation_id="thread-1",
    )


def test_session_events_replay_without_business_state() -> None:
    events = [
        _event(0, LoopEventType.LOOP_INITIALIZED, {"state": {}}),
        _event(1, LoopEventType.EXECUTION_SESSION_STARTED, {
            "session_id": "s1",
            "host": "claude_code",
            "started_by": "initial",
        }),
        _event(2, LoopEventType.SESSION_ROLLOVER_REQUESTED, {
            "session_id": "s1",
            "reason": "context_soft_limit",
        }),
        _event(3, LoopEventType.EXECUTION_SESSION_CLOSED, {
            "session_id": "s1",
            "successor_session_id": "s2",
        }),
        _event(4, LoopEventType.EXECUTION_SESSION_STARTED, {
            "session_id": "s2",
            "host": "codex",
            "started_by": "rollover",
            "predecessor_session_id": "s1",
        }),
    ]

    projection = SessionProjection().replay(events)

    assert projection.active_session_id == "s2"
    assert projection.sessions["s1"].status is SessionStatus.CLOSED
    assert projection.sessions["s2"].predecessor_session_id == "s1"


def test_session_model_rejects_invalid_status_and_identity() -> None:
    with pytest.raises(ValueError):
        ExecutionSession(
            session_id="",
            thread_id="thread-1",
            host="codex",
            started_by="initial",
        )


def test_projection_rejects_two_active_sessions() -> None:
    events = [
        _event(0, LoopEventType.EXECUTION_SESSION_STARTED, {
            "session_id": "s1", "host": "claude_code", "started_by": "initial",
        }),
        _event(1, LoopEventType.EXECUTION_SESSION_STARTED, {
            "session_id": "s2", "host": "codex", "started_by": "recovery",
        }),
    ]

    with pytest.raises(SessionProjectionError, match="active"):
        SessionProjection().replay(events)
