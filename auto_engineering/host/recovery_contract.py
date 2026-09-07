"""Host recovery operation names shared by every host projection."""

from __future__ import annotations

# These values are protocol data, not host-specific prose.  Keep one spelling so
# Claude Code, Codex and the public CLI cannot silently choose different repair
# branches for the same active Action.
WORKER_OUTCOMES_COMMITTED = "worker_outcomes_committed"
REPAIR_COORDINATOR_THEN_FINALIZE = "repair_coordinator_then_finalize"
NATIVE_OUTCOMES_READY = "native_outcomes_ready"

__all__ = [
    "NATIVE_OUTCOMES_READY",
    "REPAIR_COORDINATOR_THEN_FINALIZE",
    "WORKER_OUTCOMES_COMMITTED",
]
