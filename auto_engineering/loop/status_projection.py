"""协调状态的只读 CLI 投影。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def reconciliation_status(state: Any, batch_state: Any | None) -> dict[str, Any] | None:
    """返回协调摘要和 Current Work Set 的下一任务。"""
    raw = getattr(state, "plan_reconciliation", None)
    if not isinstance(raw, Mapping):
        return None
    payload = dict(raw)
    payload["historical_tasks"] = list(
        getattr(state, "superseded_tasks", []) or []
    )
    payload["next_batch"] = None
    payload["next_task"] = None
    if batch_state is None or batch_state.is_all_complete():
        return payload
    batch = batch_state.current_batch()
    payload["next_batch"] = batch.get("batch_id")
    tasks = batch.get("tasks", [])
    if tasks and isinstance(tasks[0], Mapping):
        payload["next_task"] = tasks[0].get("id")
    return payload
