"""Worker 交接路径的唯一确定性规则。"""

from __future__ import annotations

import hashlib


def worker_outcome_path(action_identity: str) -> str:
    """Return a deterministic, action-scoped handoff location for one Worker."""

    digest = hashlib.sha256(action_identity.encode("utf-8")).hexdigest()
    return f".ae-state/host-runtime/worker-outcomes/{digest}.json"
