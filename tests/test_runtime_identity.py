"""Phase 82 T435：Coordinator/Worker 运行身份契约。"""

from __future__ import annotations

import pytest

from auto_engineering.host.runtime_identity import (
    ExecutionIdentity,
    RuntimeIdentityError,
    RuntimeRole,
)


def test_coordinator_is_the_only_identity_allowed_to_drive_loop() -> None:
    identity = ExecutionIdentity.coordinator(stage="architect")

    assert identity.role is RuntimeRole.COORDINATOR
    assert identity.may_drive_loop is True
    assert identity.may_spawn_workers is True
    assert identity.inherit_parent_context is True


def test_worker_is_isolated_and_cannot_reenter_or_spawn() -> None:
    identity = ExecutionIdentity.worker(stage="architect")

    assert identity.role is RuntimeRole.WORKER
    assert identity.may_drive_loop is False
    assert identity.may_spawn_workers is False
    assert identity.inherit_parent_context is False


def test_worker_identity_rejects_privilege_escalation() -> None:
    with pytest.raises(RuntimeIdentityError, match="WORKER_IDENTITY_ESCALATION"):
        ExecutionIdentity.from_dict({
            "role": "worker",
            "stage": "architect",
            "may_drive_loop": True,
            "may_spawn_workers": False,
            "inherit_parent_context": False,
        })
