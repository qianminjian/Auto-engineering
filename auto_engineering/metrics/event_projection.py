"""从 Core 事实流投影项目指标，禁止依赖进程内旁路计数。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.metrics.usage_ledger import UsageRecord


def _changes(event: LoopEvent) -> dict[str, Any]:
    changes = event.payload.get("changes")
    return dict(changes) if isinstance(changes, Mapping) else {}


def project_event_metrics(
    events: Iterable[LoopEvent],
    usage_records: Sequence[UsageRecord] = (),
) -> dict[str, Any]:
    """重放不可变事实，生成可审计且明确标注缺测的摘要。"""

    total_majors = 0
    plan_refine_count = 0
    for event in events:
        changes = _changes(event)
        if event.event_type is LoopEventType.CRITIC_STATE_UPDATED:
            value = changes.get("total_majors")
            if isinstance(value, int) and not isinstance(value, bool):
                total_majors = max(total_majors, value)
        elif event.event_type is LoopEventType.PLAN_STATE_UPDATED:
            value = changes.get("plan_refine_count")
            if isinstance(value, int) and not isinstance(value, bool):
                plan_refine_count = max(plan_refine_count, value)

    usage_fields = (
        "input_units",
        "cache_read_units",
        "cache_write_units",
        "output_units",
    )
    usage_totals = {
        field: sum(
            value for record in usage_records
            if (value := getattr(record, field)) is not None
        )
        for field in usage_fields
    }
    unknown_usage_records = sum(
        all(getattr(record, field) is None for field in usage_fields)
        for record in usage_records
    )
    measurement_complete = bool(usage_records) and unknown_usage_records == 0
    return {
        "source": "event_store",
        "total_majors": total_majors,
        "plan_refine_count": plan_refine_count,
        "usage": {
            **usage_totals,
            "records": len(usage_records),
            "unknown_records": unknown_usage_records,
        },
        "measurement_complete": measurement_complete,
        "measurement_incomplete": not measurement_complete,
    }


__all__ = ["project_event_metrics"]
