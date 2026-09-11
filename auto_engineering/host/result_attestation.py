"""Result 组装阶段的 Worker attestation 构造与校验。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from auto_engineering.host.spawn_contract import SpawnPlan
from auto_engineering.host.worker_attestation import validate_attestations
from auto_engineering.host.worker_evidence import NativeWorkerOutcome


def build_validated_attestations(
    *,
    candidates: Mapping[str, NativeWorkerOutcome],
    plan: SpawnPlan,
    worker_templates: Mapping[str, Mapping[str, Any]],
    action_message_id: str,
) -> list[dict[str, Any]]:
    """从宿主模板回填 Worker 事实并校验其与 active Action 的绑定。"""

    built: list[dict[str, Any]] = []
    for invocation in plan.invocations:
        outcome = candidates[invocation.worker_id]
        template = worker_templates[invocation.worker_id]
        raw_attestation = template.get("attestation")
        assert isinstance(raw_attestation, Mapping)
        attestation = dict(raw_attestation)
        attestation["status"] = "completed"
        attestation["actual_model"] = outcome.actual_model
        if outcome.isolation_evidence is not None:
            attestation["isolation_evidence"] = outcome.isolation_evidence
        built.append(attestation)
    validate_attestations(
        action_message_id=action_message_id,
        invocations=plan.invocations,
        attestations=built,
    )
    return built


__all__ = ["build_validated_attestations"]
