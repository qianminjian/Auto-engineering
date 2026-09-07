"""同一 Action 的 Worker outcome 修复与保守合并规则。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from auto_engineering.host.worker_evidence import (
    HostEvidenceValidationError,
    NativeWorkerOutcome,
)


def merge_authoritative_outcomes(
    authoritative: Sequence[Mapping[str, Any]],
    current: Sequence[NativeWorkerOutcome],
) -> dict[str, NativeWorkerOutcome]:
    """固定已有 Worker 事实，并允许 assembly repair 追加新 Worker。"""

    try:
        authoritative_by_worker = {
            item.worker_id: item
            for item in (
                NativeWorkerOutcome(**dict(raw)) for raw in authoritative
            )
        }
        return {
            item.worker_id: authoritative_by_worker.get(item.worker_id, item)
            for item in current
        }
    except (TypeError, ValueError) as exc:
        raise HostEvidenceValidationError((
            "OUTCOME_JOURNAL_OUTCOMES_INVALID",
        )) from exc


def assembly_rejection_can_extend_outcomes(
    journal: Mapping[str, Any],
    current: Sequence[NativeWorkerOutcome],
) -> bool:
    """判断 assembly_rejected 是否只是在追加尚未回写的 Worker。"""

    if journal.get("status") != "assembly_rejected":
        return False
    raw_authoritative = journal.get("outcomes")
    if not isinstance(raw_authoritative, list):
        return False
    authoritative_items = [
        item for item in raw_authoritative if isinstance(item, Mapping)
    ]
    if len(authoritative_items) != len(raw_authoritative):
        return False
    authoritative_by_worker: dict[str, dict[str, Any]] = {}
    for item in authoritative_items:
        worker_id = item.get("worker_id")
        if not isinstance(worker_id, str) or worker_id in authoritative_by_worker:
            return False
        authoritative_by_worker[worker_id] = dict(item)
    current_by_worker = {
        item.worker_id: item.to_dict() for item in current
    }
    return bool(authoritative_by_worker) and all(
        current_by_worker.get(worker_id) == item
        for worker_id, item in authoritative_by_worker.items()
    )
