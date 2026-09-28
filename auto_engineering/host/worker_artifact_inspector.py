"""检查 Action 绑定的私有 Worker artifact，不升级宿主事实。"""

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
    HostEvidenceValidationError,
    WorkerOutcomeCollectionError,
    parse_private_worker_artifact,
)


def inspect_private_worker_artifacts(
    *,
    project_root: Path,
    action: Mapping[str, Any],
) -> None:
    """检查私有 Worker 产物；不把私有字节升级为 Host outcome。

    当前协议中，``outcome_path`` 只能保存四字段业务 artifact。Host
    handle、model、隔离和 generation/fence 只能在当前宿主仍持有原生事实时，
    由 ``record-worker-outcome`` 合并进共享 outcomes。这个恢复边界因此只
    能返回“缺少宿主事实”或“可由绑定 native 结果修复”；它不再接受旧的
    Host-in-private envelope，也不再自行构造第二套 ``NativeWorkerOutcome``。
    """

    try:
        plan = SpawnPlan.for_recording(action)
    except SpawnContractError as exc:
        raise WorkerOutcomeCollectionError(
            HOST_PROTOCOL_FAILURE, "unknown", str(exc)
        ) from exc
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
        try:
            parse_private_worker_artifact(raw, worker_id=invocation.worker_id)
        except HostEvidenceValidationError as exc:
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
                "private_artifact_invalid",
            ) from exc
        raise WorkerOutcomeCollectionError(
            "HOST_WORKER_ATTESTATION_MISSING", invocation.worker_id,
            "private_business_artifact_only",
        )

__all__ = ["inspect_private_worker_artifacts"]
