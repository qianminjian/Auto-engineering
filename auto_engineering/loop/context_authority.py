"""v5.8 事实投影与信息性上下文的权威边界。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_COMPARABLE_ANCHORS = ("stage", "tick", "active_batch_id", "plan_revision")


def informational_drift(
    *,
    projection: Mapping[str, Any],
    informational: Mapping[str, Any] | None,
    source: str,
) -> list[dict[str, Any]]:
    """只报告冲突；绝不将摘要值合并回事实投影。"""
    if not informational:
        return []
    drift: list[dict[str, Any]] = []
    for field in _COMPARABLE_ANCHORS:
        if field not in projection or field not in informational:
            continue
        if projection[field] != informational[field]:
            drift.append({
                "code": "INFORMATIONAL_CONTEXT_DRIFT",
                "source": source,
                "authority": "informational",
                "field": field,
                "projection_value": projection[field],
                "informational_value": informational[field],
            })
    return drift


__all__ = ["informational_drift"]
