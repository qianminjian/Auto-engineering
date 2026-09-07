"""Architect/Critic Stage 共用的确定性辅助逻辑。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.stages.base import StageName, TransitionContext


def advanced(
    *,
    source: StageName,
    target: StageName,
    context: TransitionContext,
) -> LoopEvent:
    return LoopEvent.create(
        thread_id=context.thread_id,
        sequence=context.event_sequence,
        event_type=LoopEventType.STAGE_ADVANCED,
        payload={"from": source, "to": target},
        correlation_id=context.thread_id,
    )


def has_batches(raw: object) -> bool:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return False
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        nested = item.get("batches")
        if nested is None or (
            isinstance(nested, Sequence)
            and not isinstance(nested, (str, bytes))
            and bool(nested)
        ):
            return True
    return False


def architect_evidence(
    result: Mapping[str, Any],
    context: TransitionContext,
) -> tuple[dict[str, Any], Mapping[str, Any] | None, tuple[dict[str, str], ...]]:
    prepared = context.extensions.get("architect_prepared")
    if isinstance(prepared, Mapping):
        evidence = prepared.get("evidence_changes")
        reconciliation = prepared.get("plan_reconciliation_changes")
        superseded = prepared.get("superseded_tasks", ())
        if isinstance(evidence, Mapping):
            retired = tuple(
                item for item in superseded
                if isinstance(item, dict)
            ) if isinstance(superseded, (list, tuple)) else ()
            return dict(evidence), (
                dict(reconciliation)
                if isinstance(reconciliation, Mapping)
                else None
            ), retired
    raw_batches = result.get("batch_plan")
    if not isinstance(raw_batches, list):
        patch = result.get("plan_patch")
        raw_batches = patch.get("add_batches", []) if isinstance(patch, Mapping) else []
    evidence = {
        "plan": result.get("plan", ""),
        "file_list": list(result.get("file_list", [])),
        "batch_plan": list(raw_batches),
        "contracts": dict(result.get("contracts", {}))
        if isinstance(result.get("contracts"), Mapping) else {},
    }
    return evidence, None, ()


__all__ = ["advanced", "architect_evidence", "has_batches"]
