"""v5.8 T311：rollover/claim 幂等交接协议。"""

from __future__ import annotations

import pytest

from auto_engineering.loop.resume_capsule import ResumeCapsule
from auto_engineering.loop.session_handoff import (
    SessionHandoff,
    SessionHandoffError,
)


def _capsule() -> ResumeCapsule:
    return ResumeCapsule.create(
        thread_id="thread-1",
        source_session_id="session-1",
        projection_sequence=10,
        active_action={"message_id": "action-10", "action": "developer"},
        state_digest={"stage": "developer", "tick": 10},
        issued_at="2026-07-30T00:00:00+00:00",
    )


def test_rollover_retry_returns_same_control_action() -> None:
    handoff = SessionHandoff(
        token_factory=lambda: "claim-1",
        artifact_id_factory=lambda: "capsule-1",
    )

    first = handoff.request_rollover(
        current_session_id="session-1",
        reason="context_soft_limit",
        capsule=_capsule(),
    )
    replay = handoff.request_rollover(
        current_session_id="session-1",
        reason="context_soft_limit",
        capsule=_capsule(),
    )

    assert replay == first
    assert first["action"] == "session_rollover"
    assert first["claim_token"] == "claim-1"
    assert first["capsule"]["sha256"] == _capsule().payload_sha256


def test_claim_is_idempotent_and_returns_original_active_action() -> None:
    handoff = SessionHandoff(
        token_factory=lambda: "claim-1",
        artifact_id_factory=lambda: "capsule-1",
    )
    rollover = handoff.request_rollover(
        current_session_id="session-1",
        reason="tick_limit",
        capsule=_capsule(),
    )

    result = {
        "stage": "session_claimed",
        "claim_token": rollover["claim_token"],
        "session_id": "session-2",
        "host": "codex",
    }
    first = handoff.claim(result)
    replay = handoff.claim(dict(result))

    assert first == replay
    assert first["message_id"] == "action-10"
    assert handoff.active_session_id == "session-2"


def test_competing_claim_fails_closed() -> None:
    handoff = SessionHandoff(
        token_factory=lambda: "claim-1",
        artifact_id_factory=lambda: "capsule-1",
    )
    handoff.request_rollover(
        current_session_id="session-1",
        reason="time_limit",
        capsule=_capsule(),
    )
    handoff.claim({
        "stage": "session_claimed",
        "claim_token": "claim-1",
        "session_id": "session-2",
        "host": "claude_code",
    })

    with pytest.raises(SessionHandoffError) as exc:
        handoff.claim({
            "stage": "session_claimed",
            "claim_token": "claim-1",
            "session_id": "session-3",
            "host": "codex",
        })

    assert exc.value.error_code == "SESSION_CLAIM_CONFLICT"


def test_old_session_late_result_is_rejected() -> None:
    handoff = SessionHandoff(
        token_factory=lambda: "claim-1",
        artifact_id_factory=lambda: "capsule-1",
    )
    handoff.request_rollover(
        current_session_id="session-1",
        reason="context_hard_limit",
        capsule=_capsule(),
    )

    with pytest.raises(SessionHandoffError) as exc:
        handoff.assert_session_may_submit("session-1")

    assert exc.value.error_code == "SESSION_NOT_ACTIVE"


def test_invalid_claim_token_is_rejected() -> None:
    handoff = SessionHandoff(
        token_factory=lambda: "claim-1",
        artifact_id_factory=lambda: "capsule-1",
    )
    handoff.request_rollover(
        current_session_id="session-1",
        reason="manual",
        capsule=_capsule(),
    )

    with pytest.raises(SessionHandoffError) as exc:
        handoff.claim({
            "stage": "session_claimed",
            "claim_token": "unknown",
            "session_id": "session-2",
            "host": "codex",
        })

    assert exc.value.error_code == "SESSION_CLAIM_INVALID"
