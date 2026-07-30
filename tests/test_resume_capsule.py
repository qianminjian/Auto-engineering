"""v5.8 T309：ResumeCapsule 最小恢复契约。"""

from __future__ import annotations

import pytest

from auto_engineering.loop.resume_capsule import (
    ResumeCapsule,
    ResumeCapsuleError,
)


def _capsule() -> ResumeCapsule:
    return ResumeCapsule.create(
        thread_id="thread-1",
        source_session_id="session-1",
        projection_sequence=146,
        active_action={"message_id": "action-146", "action": "developer"},
        state_digest={
            "stage": "developer",
            "active_batch_id": "B27",
            "plan_revision": 4,
            "done_task_ids": ["B1-T1"],
        },
        required_artifacts=[{
            "artifact_id": "audit-1",
            "sha256": "a" * 64,
            "kind": "audit_report",
        }],
        policy_snapshot={"policy_id": "default-v1"},
        budget={"remaining_ticks": 20},
    )


def test_capsule_round_trip_and_hash() -> None:
    capsule = _capsule()
    restored = ResumeCapsule.from_dict(capsule.to_dict())

    assert restored == capsule
    assert restored.verify_payload_hash()
    assert restored.active_action["message_id"] == "action-146"


def test_capsule_rejects_tampering() -> None:
    raw = _capsule().to_dict()
    raw["state_digest"]["active_batch_id"] = "B1"

    with pytest.raises(ResumeCapsuleError, match="sha256"):
        ResumeCapsule.from_dict(raw)


@pytest.mark.parametrize("forbidden", ["messages", "transcript", "action_history"])
def test_capsule_rejects_conversation_history(forbidden: str) -> None:
    with pytest.raises(ResumeCapsuleError, match="历史"):
        ResumeCapsule.create(
            thread_id="thread-1",
            source_session_id="session-1",
            projection_sequence=1,
            active_action={
                "message_id": "action-1",
                "action": "developer",
                forbidden: ["large history"],
            },
            state_digest={"stage": "developer"},
        )


def test_capsule_rejects_invalid_artifact_hash() -> None:
    with pytest.raises(ResumeCapsuleError, match="artifact"):
        ResumeCapsule.create(
            thread_id="thread-1",
            source_session_id="session-1",
            projection_sequence=1,
            active_action={"message_id": "a1", "action": "developer"},
            state_digest={"stage": "developer"},
            required_artifacts=[{"artifact_id": "x", "sha256": "bad", "kind": "audit"}],
        )
