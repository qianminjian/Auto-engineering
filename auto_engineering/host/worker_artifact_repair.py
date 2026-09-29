"""Worker 私有 artifact 修复的单一 Host 边界。"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from auto_engineering.host.path_contract import (
    worker_native_result_path,
    worker_outcome_path,
)
from auto_engineering.host.worker_evidence import (
    HostEvidenceValidationError,
    _atomic_write_bytes,
    _atomic_write_json,
    _native_business_artifact,
)
from auto_engineering.host.worker_execution_binding import (
    resolve_worker_execution_binding,
)


def bound_native_business_is_valid(
    *,
    project_root: Path,
    invocation: Any,
    template: Mapping[str, Any] | None,
    action: Mapping[str, Any] | None = None,
) -> bool:
    """只读判断绑定 native result 是否能修复私有 artifact。"""

    native_ref = (
        template.get("native_result_path")
        if isinstance(template, Mapping)
        else None
    )
    if not isinstance(native_ref, str) or not native_ref:
        return False
    if action is not None:
        message_id = action.get("message_id")
        if not isinstance(message_id, str) or not message_id:
            return False
        try:
            generation, _fence = resolve_worker_execution_binding(
                action, template, invocation.worker_id
            )
        except HostEvidenceValidationError:
            return False
        if generation is not None:
            if native_ref != worker_native_result_path(
                message_id, invocation.worker_id, generation
            ):
                return False
            if invocation.outcome_path != worker_outcome_path(
                message_id, invocation.worker_id, generation
            ):
                return False
    native_path = (project_root / native_ref).resolve()
    outcome_path = (project_root / invocation.outcome_path).resolve()
    if (
        native_path in (project_root, outcome_path)
        or project_root not in native_path.parents
        or not native_path.is_file()
    ):
        return False
    try:
        raw = json.loads(native_path.read_text(encoding="utf-8"))
        native_status_value = (
            raw.get("status") if isinstance(raw, Mapping) else None
        )
        native_status = (
            native_status_value
            if isinstance(native_status_value, str)
            else "completed"
        )
        _native_business_artifact(
            raw,
            worker_id=invocation.worker_id,
            status=native_status,
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        HostEvidenceValidationError,
    ):
        return False
    return True


def quarantine_private_artifact(
    *,
    project_root: Path,
    action: Mapping[str, Any],
    worker_id: str,
    outcome_ref: str,
    raw_bytes: bytes | None,
    violations: Sequence[str],
    execution_generation: int | None,
    fencing_token: str | None,
    source_path: Path | None = None,
) -> None:
    """将原私有 artifact 移入绑定的隔离区并写入幂等索引。

    ``source_path`` 由 repair 调用方传入时，原文件会被原子移动到隔离区；
    没有 source 的调用仍只物化原始字节和索引，供独立边界测试或已完成
    隔离后的重复记录使用。canonical outcome path 不会被 quarantine 占用，
    后续重复 recovery 可以从绑定 native result 重新物化它。
    """

    message_id = action.get("message_id")
    if not isinstance(message_id, str) or not message_id or raw_bytes is None:
        raise HostEvidenceValidationError(
            ("WORKER_ARTIFACT_QUARANTINE_BINDING_INVALID",)
        )
    digest = hashlib.sha256(raw_bytes).hexdigest()
    safe_worker = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in worker_id
    )
    action_key = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:24]
    generation = (
        str(execution_generation)
        if isinstance(execution_generation, int)
        else "unbound"
    )
    fence_key = (
        hashlib.sha256(fencing_token.encode("utf-8")).hexdigest()[:16]
        if isinstance(fencing_token, str) and fencing_token
        else "unbound"
    )
    quarantine_path = (
        project_root
        / ".ae-state/host-runtime/worker-outcome-quarantine"
        / f"{action_key}-{safe_worker}-g{generation}-f{fence_key}-{digest[:16]}.json"
    )
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    quarantined_bytes_path = quarantine_path.with_suffix(".artifact")
    if source_path is not None:
        root = project_root.resolve()
        source = source_path.resolve()
        if source == root or root not in source.parents:
            raise HostEvidenceValidationError(
                ("WORKER_ARTIFACT_QUARANTINE_SOURCE_INVALID",)
            )
        try:
            if source.is_file():
                if source.read_bytes() != raw_bytes:
                    raise HostEvidenceValidationError(
                        ("WORKER_ARTIFACT_QUARANTINE_RACE",)
                    )
                os.replace(source, quarantined_bytes_path)
        except OSError as exc:
            raise HostEvidenceValidationError(
                ("WORKER_ARTIFACT_QUARANTINE_WRITE_FAILED",)
            ) from exc
    elif not quarantined_bytes_path.is_file():
        _atomic_write_bytes(quarantined_bytes_path, raw_bytes)
    if quarantined_bytes_path.is_file():
        try:
            if quarantined_bytes_path.read_bytes() != raw_bytes:
                raise HostEvidenceValidationError(
                    ("WORKER_ARTIFACT_QUARANTINE_CONFLICT",)
                )
        except OSError as exc:
            raise HostEvidenceValidationError(
                ("WORKER_ARTIFACT_QUARANTINE_READ_FAILED",)
            ) from exc
    _atomic_write_json(
        quarantine_path,
        {
            "schema_version": "1.0",
            "status": "quarantined",
            "reason": "private_artifact_repaired_from_bound_native_result",
            "action_message_id": message_id,
            "worker_id": worker_id,
            "execution_generation": execution_generation,
            "fencing_token": fencing_token,
            "source_path": outcome_ref,
            "quarantined_artifact_ref": str(
                quarantined_bytes_path.relative_to(project_root.resolve())
            ),
            "artifact_sha256": digest,
            "violations": list(violations),
        },
    )


__all__ = ["bound_native_business_is_valid", "quarantine_private_artifact"]
