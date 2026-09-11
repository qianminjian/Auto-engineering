"""Host recovery operation names shared by every host projection."""

from __future__ import annotations

from collections.abc import Mapping

# These values are protocol data, not host-specific prose.  Keep one spelling so
# Claude Code, Codex and the public CLI cannot silently choose different repair
# branches for the same active Action.
WORKER_OUTCOMES_COMMITTED = "worker_outcomes_committed"
REPAIR_COORDINATOR_THEN_FINALIZE = "repair_coordinator_then_finalize"
NATIVE_OUTCOMES_READY = "native_outcomes_ready"
WORKER_RECOVERY_STATUSES = frozenset({
    NATIVE_OUTCOMES_READY,
    WORKER_OUTCOMES_COMMITTED,
    "worker_attestation_pending",
})


def is_worker_execution_action(action: object) -> bool:
    """判断宿主视图是否仍需按 Worker 证据链处理。

    恢复投影会移除 ``spawn`` 以禁止再次启动，但它仍然是同一 Worker
    Action 的记录/最终化视图，不能被误判成 inline Action。
    """

    if not isinstance(action, Mapping):
        return False
    if isinstance(action.get("spawn"), Mapping):
        return True
    host_execution = action.get("host_execution")
    recovery = (
        host_execution.get("recovery")
        if isinstance(host_execution, Mapping)
        else None
    )
    return (
        isinstance(recovery, Mapping)
        and recovery.get("status") in WORKER_RECOVERY_STATUSES
    )

__all__ = [
    "NATIVE_OUTCOMES_READY",
    "REPAIR_COORDINATOR_THEN_FINALIZE",
    "WORKER_OUTCOMES_COMMITTED",
    "WORKER_RECOVERY_STATUSES",
    "is_worker_execution_action",
]
