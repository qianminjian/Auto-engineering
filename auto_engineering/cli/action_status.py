"""当前 Action 的只读状态摘要。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def status_action_summary(action: Mapping[str, Any]) -> dict[str, Any]:
    """投影当前 Action 的宿主所需字段，不泄漏 Canonical 私有 context。"""
    host_execution = action.get("host_execution")
    work_files = action.get("work_files")
    if not isinstance(work_files, Mapping) and isinstance(host_execution, Mapping):
        work_files = host_execution.get("work_files")
    summary: dict[str, Any] = {}
    for key in (
        "message_id", "correlation_id", "causation_id", "thread_id", "tick",
        "action", "stage", "current_gap_index", "total_gaps",
        "gap_review_contract", "gate", "current_gap", "expected_format",
    ):
        value = action.get(key)
        if isinstance(value, Mapping):
            summary[key] = dict(value)
        elif value is not None:
            summary[key] = value
    if isinstance(work_files, Mapping):
        summary["work_files"] = dict(work_files)
    extensions = action.get("extensions")
    ae = extensions.get("ae") if isinstance(extensions, Mapping) else None
    runtime_revision = (
        ae.get("runtime_revision") if isinstance(ae, Mapping) else None
    )
    if isinstance(runtime_revision, Mapping):
        engine_build_id = runtime_revision.get("engine_build_id")
        if isinstance(engine_build_id, str) and engine_build_id:
            summary["runtime_identity"] = {
                "engine_build_id": engine_build_id,
            }
    return summary


__all__ = ["status_action_summary"]
