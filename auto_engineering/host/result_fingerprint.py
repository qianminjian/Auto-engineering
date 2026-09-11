"""一次 Worker Result 事务的规范化事实指纹。"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from auto_engineering.host.spawn_contract import SpawnPlan
from auto_engineering.host.worker_evidence import (
    NativeWorkerOutcome,
    _canonical_bytes,
)


def serialize_and_fingerprint_outcomes(
    *,
    action_message_id: str,
    outcome_by_worker: Mapping[str, NativeWorkerOutcome],
    plan: SpawnPlan,
    coordinator_payload: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], str, str]:
    """返回序列化 outcomes、事实指纹和包含 Coordinator 语义的 Result 指纹。"""

    serialized_outcomes = [
        outcome_by_worker[item.worker_id].to_dict() for item in plan.invocations
    ]
    outcomes_fingerprint = hashlib.sha256(
        _canonical_bytes({
            "action_message_id": action_message_id,
            "outcomes": serialized_outcomes,
        })
    ).hexdigest()
    fingerprint = hashlib.sha256(_canonical_bytes({
        "action_message_id": action_message_id,
        "outcomes": serialized_outcomes,
        "coordinator_payload": dict(coordinator_payload),
    })).hexdigest()
    return serialized_outcomes, outcomes_fingerprint, fingerprint


__all__ = ["serialize_and_fingerprint_outcomes"]
