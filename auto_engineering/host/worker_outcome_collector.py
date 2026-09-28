"""从 Action 绑定的 Worker artifact 汇总唯一共享 outcomes。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from auto_engineering.host.recovery_contract import HOST_PROTOCOL_FAILURE
from auto_engineering.host.spawn_contract import SpawnContractError, SpawnPlan
from auto_engineering.host.worker_artifact_repair import (
    bound_native_business_is_valid,
)
from auto_engineering.host.worker_evidence import (
    NativeWorkerOutcome,
    WorkerOutcomeCollectionError,
    _atomic_write_json,
    _resolve_worker_execution_binding,
)


def collect_worker_outcomes_from_artifacts(
    *,
    project_root: Path,
    action: Mapping[str, Any],
    outcomes_path: Path,
) -> list[NativeWorkerOutcome]:
    """汇总私有 Worker 产出；Coordinator 不创造 Worker 事实。"""

    try:
        plan = SpawnPlan.for_recording(action)
    except SpawnContractError as exc:
        raise WorkerOutcomeCollectionError(
            HOST_PROTOCOL_FAILURE, "unknown", str(exc)
        ) from exc
    outcomes: list[NativeWorkerOutcome] = []
    host_execution = action.get("host_execution")
    worker_templates = (
        host_execution.get("workers")
        if isinstance(host_execution, Mapping)
        else None
    )
    template_by_worker = {
        item.get("worker_id"): item
        for item in worker_templates
        if isinstance(item, Mapping) and isinstance(item.get("worker_id"), str)
    } if isinstance(worker_templates, list) else {}
    for invocation in plan.invocations:
        template = template_by_worker.get(invocation.worker_id)
        if isinstance(template, Mapping):
            candidate = template.get("outcome_path")
            if not isinstance(candidate, str) or not candidate:
                raise WorkerOutcomeCollectionError(
                    HOST_PROTOCOL_FAILURE, invocation.worker_id,
                    "outcome_path_missing",
                )
            if candidate != invocation.outcome_path:
                raise WorkerOutcomeCollectionError(
                    HOST_PROTOCOL_FAILURE, invocation.worker_id,
                    "outcome_path_drift",
                )
        path = (project_root / invocation.outcome_path).resolve()
        if path == project_root or project_root not in path.parents:
            raise WorkerOutcomeCollectionError(
                HOST_PROTOCOL_FAILURE, invocation.worker_id,
                "path_outside_project",
            )
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise WorkerOutcomeCollectionError(
                "HOST_WORKER_OUTPUT_MISSING", invocation.worker_id
            ) from exc
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            if bound_native_business_is_valid(
                project_root=project_root,
                invocation=invocation,
                template=template if isinstance(template, Mapping) else None,
            ):
                raise WorkerOutcomeCollectionError(
                    "HOST_WORKER_ARTIFACT_REPAIRABLE", invocation.worker_id,
                    "private_artifact_unreadable_native_result_available",
                ) from exc
            raise WorkerOutcomeCollectionError(
                HOST_PROTOCOL_FAILURE, invocation.worker_id,
                exc.__class__.__name__,
            ) from exc
        if isinstance(raw, Mapping) and isinstance(raw.get("outcome"), Mapping):
            raw = raw["outcome"]
        if not isinstance(raw, Mapping):
            if bound_native_business_is_valid(
                project_root=project_root,
                invocation=invocation,
                template=template if isinstance(template, Mapping) else None,
            ):
                raise WorkerOutcomeCollectionError(
                    "HOST_WORKER_ARTIFACT_REPAIRABLE", invocation.worker_id,
                    "private_artifact_not_object_native_result_available",
                )
            raise WorkerOutcomeCollectionError(
                HOST_PROTOCOL_FAILURE, invocation.worker_id,
                "top_level_must_be_object",
            )
        business_fields = {"worker_id", "status", "payload", "summary"}
        host_fields = {"native_worker_handle", "actual_model", "isolation_evidence"}
        if (
            (bool(raw) and set(raw).issubset(business_fields))
            or (
                business_fields.issubset(raw)
                and not host_fields.intersection(raw)
            )
        ):
            incomplete = (
                set(raw).issubset(business_fields)
                and not business_fields.issubset(raw)
            )
            if incomplete and bound_native_business_is_valid(
                project_root=project_root,
                invocation=invocation,
                template=template if isinstance(template, Mapping) else None,
            ):
                raise WorkerOutcomeCollectionError(
                    "HOST_WORKER_ARTIFACT_REPAIRABLE", invocation.worker_id,
                    "private_artifact_incomplete_native_result_available",
                )
            raise WorkerOutcomeCollectionError(
                "HOST_WORKER_ATTESTATION_MISSING", invocation.worker_id,
                "private_business_artifact_only",
            )
        try:
            outcome = NativeWorkerOutcome(**dict(raw))
        except (TypeError, ValueError) as exc:
            if bound_native_business_is_valid(
                project_root=project_root,
                invocation=invocation,
                template=template if isinstance(template, Mapping) else None,
            ):
                raise WorkerOutcomeCollectionError(
                    "HOST_WORKER_ARTIFACT_REPAIRABLE", invocation.worker_id,
                    "private_artifact_invalid_native_result_available",
                ) from exc
            raise WorkerOutcomeCollectionError(
                HOST_PROTOCOL_FAILURE, invocation.worker_id,
                exc.__class__.__name__,
            ) from exc
        if outcome.worker_id != invocation.worker_id:
            raise WorkerOutcomeCollectionError(
                HOST_PROTOCOL_FAILURE, invocation.worker_id,
                "worker_id_mismatch",
            )
        if (
            outcome.status == "completed"
            and outcome.native_worker_handle.startswith("unreported:")
        ):
            raise WorkerOutcomeCollectionError(
                HOST_PROTOCOL_FAILURE, invocation.worker_id,
                "native_handle_unreported",
            )
        expected_generation, expected_fence = _resolve_worker_execution_binding(
            action,
            template if isinstance(template, Mapping) else None,
            invocation.worker_id,
        )
        if (
            (expected_generation is not None or expected_fence is not None)
            and (
                not isinstance(expected_generation, int)
                or expected_generation < 1
                or not isinstance(expected_fence, str)
                or len(expected_fence) != 64
                or outcome.execution_generation != expected_generation
                or outcome.fencing_token != expected_fence
            )
        ):
            raise WorkerOutcomeCollectionError(
                "HOST_WORKER_OUTPUT_STALE", invocation.worker_id,
                "execution_fence_mismatch",
            )
        outcomes.append(outcome)
    _atomic_write_json(outcomes_path, {"outcomes": [item.to_dict() for item in outcomes]})
    return outcomes


__all__ = ["collect_worker_outcomes_from_artifacts"]
