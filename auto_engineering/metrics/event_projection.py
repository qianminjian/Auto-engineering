"""从 Core 事实流投影项目指标，禁止依赖进程内旁路计数。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.metrics.usage import UsageRecord


def _changes(event: LoopEvent) -> dict[str, Any]:
    changes = event.payload.get("changes")
    return dict(changes) if isinstance(changes, Mapping) else {}


def project_event_metrics(
    events: Iterable[LoopEvent],
    usage_records: Sequence[UsageRecord] = (),
) -> dict[str, Any]:
    """重放不可变事实，生成可审计且明确标注缺测的摘要。"""

    event_list = list(events)
    if not usage_records:
        usage_records = tuple(usage_records_from_events(event_list))
    total_majors = 0
    plan_refine_count = 0
    for event in event_list:
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


def usage_records_from_events(events: Iterable[LoopEvent]) -> list[UsageRecord]:
    """从 UsageRecorded 事实构造投影记录；格式错误按缺测处理。"""

    records: list[UsageRecord] = []
    for event in events:
        if event.event_type is not LoopEventType.USAGE_RECORDED:
            continue
        usage = event.payload.get("usage")
        if not isinstance(usage, Mapping):
            continue
        records.append(UsageRecord(
            thread_id=event.thread_id,
            session_id=str(usage.get("session_id") or event.thread_id),
            tick=int(usage.get("tick") or 0),
            stage=str(usage.get("stage") or "unknown"),
            worker=str(usage.get("worker") or "unknown"),
            input_units=usage.get("input_units"),
            cache_read_units=usage.get("cache_read_units"),
            cache_write_units=usage.get("cache_write_units"),
            output_units=usage.get("output_units"),
            provider=str(usage.get("provider") or "unknown"),
            model=str(usage.get("model") or "unknown"),
            usage_source=str(usage.get("usage_source") or "unsupported"),
            estimated=bool(usage.get("estimated", False)),
            core_payload_bytes=usage.get("core_payload_bytes"),
            inline_unique_bytes=usage.get("inline_unique_bytes"),
            duplicate_block_bytes=usage.get("duplicate_block_bytes"),
            host_context_window_units=usage.get("host_context_window_units"),
            estimator_version=str(usage.get("estimator_version") or ""),
            action_message_id=usage.get("action_message_id"),
        ))
    return records


def project_metrics_events(events: Iterable[LoopEvent]) -> list[dict[str, Any]]:
    """把 EventStore 语义事实投影为指标聚合器使用的只读事件视图。

    该函数不写文件、不维护游标，也不接受 metrics 目录作为输入。它是
    MetricsCollector 在生产路径上的唯一事件输入；返回的字典只是当前调用
    的临时投影，不能被当作第二条事实流恢复。
    """

    projected: list[dict[str, Any]] = []
    critic_verdict_by_tick: dict[int, str] = {}
    for event in events:
        payload = event.payload
        changes = _changes(event)
        if event.event_type is LoopEventType.CRITIC_STATE_UPDATED:
            verdict = changes.get("critic_verdict")
            if isinstance(verdict, str) and verdict:
                critic_verdict_by_tick[event.sequence] = verdict

        if event.event_type is LoopEventType.ACTION_ISSUED:
            action = payload.get("action")
            if not isinstance(action, Mapping):
                continue
            action_type = action.get("action")
            if action_type in {"error", "resource_wait", "wait_user"}:
                continue
            stage = action.get("stage")
            if not isinstance(stage, str) or not stage:
                continue
            projected.append({
                "timestamp": event.created_at,
                "event_type": "tick_complete",
                "thread_id": event.thread_id,
                "payload": {
                    "tick_number": action.get("tick", event.sequence),
                    "stage": stage,
                    "duration_ms": 0,
                    "gate_results": {},
                    "guardrail_results": {},
                    **({"verdict": action["verdict"]}
                       if isinstance(action.get("verdict"), str)
                       else {}),
                },
            })
            continue

        if event.event_type is LoopEventType.USAGE_RECORDED:
            usage = payload.get("usage")
            if not isinstance(usage, Mapping):
                continue
            projected.append({
                "timestamp": event.created_at,
                "event_type": "token_usage",
                "thread_id": event.thread_id,
                "payload": {
                    "input_tokens": usage.get("input_units") or 0,
                    "output_tokens": usage.get("output_units") or 0,
                    "model": usage.get("model", "unknown"),
                    "provider": usage.get("provider", "unknown"),
                    "stage": usage.get("stage", "unknown"),
                },
            })
            continue

        if event.event_type is LoopEventType.PLAN_STATE_UPDATED:
            value = changes.get("plan_refine_count")
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                projected.append({
                    "timestamp": event.created_at,
                    "event_type": "convergence",
                    "thread_id": event.thread_id,
                    "payload": {
                        "verdict": "PLAN_REFINE",
                        "total_ticks": 0,
                        "criteria_met": "plan_refine",
                    },
                })
            continue

        if event.event_type is LoopEventType.LOOP_COMPLETED:
            verdict = payload.get("verdict", "UNKNOWN")
            projected.append({
                "timestamp": event.created_at,
                "event_type": "convergence",
                "thread_id": event.thread_id,
                "payload": {
                    "verdict": verdict,
                    "total_ticks": payload.get("tick", 0),
                    "criteria_met": str(verdict).lower(),
                },
            })

    # Critic state facts are authoritative for major counting. Add a compact
    # critic transition view instead of trusting an in-memory callback order.
    for sequence, verdict in critic_verdict_by_tick.items():
        projected.append({
            "timestamp": "",
            "event_type": "critic_verdict",
            "thread_id": "",
            "payload": {
                "sequence": sequence,
                "verdict": verdict,
            },
        })
    return projected


__all__ = [
    "project_event_metrics",
    "project_metrics_events",
    "usage_records_from_events",
]
