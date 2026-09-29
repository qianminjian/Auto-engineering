"""检查 Action 绑定的私有 Worker artifact，不升级宿主事实。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class WorkerArtifactClassification:
    """当前 Action 的唯一私有/native 交接分类。"""

    code: str
    worker_id: str
    detail: str = ""


def classify_private_worker_artifacts(
    *,
    project_root: Path,
    action: Mapping[str, Any],
) -> WorkerArtifactClassification:
    """按全部 Worker 证据给出一次确定性恢复分类。"""

    try:
        plan = SpawnPlan.for_recording(action)
    except SpawnContractError as exc:
        return WorkerArtifactClassification(HOST_PROTOCOL_FAILURE, "unknown", str(exc))

    root = project_root.resolve()
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
    classifications: list[tuple[int, WorkerArtifactClassification]] = []
    for invocation in plan.invocations:
        template = template_by_worker.get(invocation.worker_id)
        if isinstance(template, Mapping):
            candidate = template.get("outcome_path")
            if not isinstance(candidate, str) or not candidate:
                return WorkerArtifactClassification(
                    HOST_PROTOCOL_FAILURE, invocation.worker_id, "outcome_path_missing"
                )
            if candidate != invocation.outcome_path:
                return WorkerArtifactClassification(
                    HOST_PROTOCOL_FAILURE, invocation.worker_id, "outcome_path_drift"
                )
        path = (root / invocation.outcome_path).resolve()
        if path == root or root not in path.parents:
            return WorkerArtifactClassification(
                HOST_PROTOCOL_FAILURE, invocation.worker_id, "path_outside_project"
            )
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            if bound_native_business_is_valid(
                project_root=root,
                invocation=invocation,
                template=template if isinstance(template, Mapping) else None,
            ):
                classifications.append((
                    1,
                    WorkerArtifactClassification(
                        "HOST_WORKER_ARTIFACT_REPAIRABLE",
                        invocation.worker_id,
                        "private_artifact_unreadable_native_result_available",
                    ),
                ))
            else:
                classifications.append((
                    0,
                    WorkerArtifactClassification(
                        HOST_PROTOCOL_FAILURE,
                        invocation.worker_id,
                        exc.__class__.__name__,
                    ),
                ))
            continue
        try:
            expected_format = action.get("expected_format")
            parse_private_worker_artifact(
                raw,
                worker_id=invocation.worker_id,
                status="completed",
                expected_format=(
                    expected_format if isinstance(expected_format, Mapping) else None
                ),
            )
        except HostEvidenceValidationError:
            if bound_native_business_is_valid(
                project_root=root,
                invocation=invocation,
                template=template if isinstance(template, Mapping) else None,
            ):
                classifications.append((
                    1,
                    WorkerArtifactClassification(
                        "HOST_WORKER_ARTIFACT_REPAIRABLE",
                        invocation.worker_id,
                        "private_artifact_invalid_native_result_available",
                    ),
                ))
            else:
                classifications.append((
                    0,
                    WorkerArtifactClassification(
                        HOST_PROTOCOL_FAILURE,
                        invocation.worker_id,
                        "private_artifact_invalid",
                    ),
                ))
            continue
        classifications.append((
            2,
            WorkerArtifactClassification(
                "HOST_WORKER_ATTESTATION_MISSING",
                invocation.worker_id,
                "private_business_artifact_only",
            ),
        ))
    if classifications:
        return min(classifications, key=lambda item: (item[0], item[1].worker_id))[1]
    return WorkerArtifactClassification(
        "HOST_WORKER_OUTPUT_MISSING", plan.invocations[0].worker_id
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

    classification = classify_private_worker_artifacts(
        project_root=project_root,
        action=action,
    )
    raise WorkerOutcomeCollectionError(
        classification.code,
        classification.worker_id,
        classification.detail,
    )

__all__ = [
    "WorkerArtifactClassification",
    "classify_private_worker_artifacts",
    "inspect_private_worker_artifacts",
]
