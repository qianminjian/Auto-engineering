"""私有 Worker artifact 的唯一解析与归一化边界。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from auto_engineering.host.worker_evidence_contracts import (
    HostEvidenceValidationError,
)


def parse_private_worker_artifact(
    raw: object,
    *,
    worker_id: str,
    status: str | None = None,
    expected_format: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """解析并归一化唯一的私有 Worker 业务 envelope。

    Inspector、generation probe 和 ``record-worker-outcome`` 都必须调用这
    个入口。这里集中保留两种明确兼容行为：私有 envelope 可以省略非业务
    ``summary``，以及当前 Action 的 ``expected_format`` 能唯一确认裸业务
    payload 时由 Host 补齐 envelope。除此之外不猜测嵌套对象、宿主事实或
    任意旧字段。
    """

    required = {"worker_id", "status", "payload", "summary"}
    envelope = {"worker_id", "status", "payload"}
    forbidden = {
        "spawned", "spawn_proof_token",
        "native_worker_handle", "actual_model", "isolation_evidence",
        "attestation", "worker_attestations", "receipt", "outcomes",
        "execution_generation", "fencing_token",
    }
    if isinstance(raw, Mapping) and set(raw) == {"outcome"}:
        raw = raw["outcome"]
    if not isinstance(raw, Mapping):
        raise HostEvidenceValidationError((
            f"WORKER_PRIVATE_ARTIFACT_INVALID:{worker_id}",
        ))
    if forbidden.intersection(raw):
        raise HostEvidenceValidationError((
            f"WORKER_BUSINESS_BOUNDARY_VIOLATION:{worker_id}",
        ))
    keys = set(raw)
    if keys in (required, envelope):
        if (
            raw.get("worker_id") != worker_id
            or not isinstance(raw.get("status"), str)
            or not isinstance(raw.get("payload"), dict)
        ):
            raise HostEvidenceValidationError((
                f"WORKER_PRIVATE_ARTIFACT_INVALID:{worker_id}",
            ))
        if keys == required:
            if not isinstance(raw.get("summary"), str) or not raw.get("summary"):
                raise HostEvidenceValidationError((
                    f"WORKER_PRIVATE_ARTIFACT_INVALID:{worker_id}",
                ))
            return dict(raw)
        return {**raw, "summary": "native_worker_result"}
    if envelope.intersection(keys):
        raise HostEvidenceValidationError((
            f"WORKER_BUSINESS_BOUNDARY_VIOLATION:{worker_id}",
        ))

    expected_keys = (
        set(expected_format) if isinstance(expected_format, Mapping) else set()
    )
    if (
        expected_keys
        and expected_keys.issubset(keys)
        and isinstance(status, str)
        and status
    ):
        return {
            "worker_id": worker_id,
            "status": status,
            "payload": dict(raw),
            "summary": "native_worker_result",
        }
    raise HostEvidenceValidationError((
        f"WORKER_PRIVATE_ARTIFACT_INVALID:{worker_id}",
    ))


__all__ = ["parse_private_worker_artifact"]
