"""v5.8 T313：150+ Tick 跨会话确定性验收。"""

from __future__ import annotations

import pytest

from auto_engineering.loop.resume_capsule import ResumeCapsule
from auto_engineering.loop.session_handoff import (
    SessionHandoff,
    SessionHandoffError,
)


def test_150_tick_projection_is_equivalent_across_three_sessions() -> None:
    golden_actions = [
        {"message_id": f"action-{tick}", "action": "developer", "tick": tick}
        for tick in range(1, 151)
    ]
    restored_actions: list[dict] = []
    current_session = "session-1"
    session_count = 1

    for index, action in enumerate(golden_actions, start=1):
        restored_actions.append(action)
        if index not in {50, 100}:
            continue
        handoff = SessionHandoff(
            token_factory=lambda index=index: f"claim-{index}",
            artifact_id_factory=lambda index=index: f"capsule-{index}",
        )
        capsule = ResumeCapsule.create(
            thread_id="thread-1",
            source_session_id=current_session,
            projection_sequence=index,
            active_action=golden_actions[index],
            state_digest={"tick": index, "stage": "developer"},
            issued_at=f"2026-07-30T00:{index // 2:02d}:00+00:00",
        )
        rollover = handoff.request_rollover(
            current_session_id=current_session,
            reason="host_process_lost",
            capsule=capsule,
        )
        assert handoff.request_rollover(
            current_session_id=current_session,
            reason="host_process_lost",
            capsule=capsule,
        ) == rollover

        successor = f"session-{session_count + 1}"
        claim = {
            "stage": "session_claimed",
            "claim_token": rollover["claim_token"],
            "session_id": successor,
            "host": "codex" if session_count == 1 else "claude_code",
        }
        assert handoff.claim(claim) == golden_actions[index]
        assert handoff.claim(dict(claim)) == golden_actions[index]
        with pytest.raises(SessionHandoffError) as late:
            handoff.assert_session_may_submit(current_session)
        assert late.value.error_code == "SESSION_NOT_ACTIVE"
        current_session = successor
        session_count += 1

    assert session_count == 3
    assert restored_actions == golden_actions
    assert restored_actions[-1]["tick"] == 150
