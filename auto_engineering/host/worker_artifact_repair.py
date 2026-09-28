"""Worker 私有 artifact 修复的单一 Host 边界。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from auto_engineering.host.worker_evidence import (
    HostEvidenceValidationError,
    _atomic_write_json,
    _native_business_artifact,
)


def bound_native_business_is_valid(
    *,
    project_root: Path,
    invocation: Any,
    template: Mapping[str, Any] | None,
) -> bool:
    """只读判断绑定 native result 是否能修复私有 artifact。"""

    native_ref = (
        template.get("native_result_path")
        if isinstance(template, Mapping)
        else None
    )
    if not isinstance(native_ref, str) or not native_ref:
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
) -> None:
    """写入幂等、脱敏且绑定 Action 的私有 artifact 隔离索引。"""

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
    quarantine_path = (
        project_root
        / ".ae-state/host-runtime/worker-outcome-quarantine"
        / f"{action_key}-{safe_worker}-g{generation}-{digest[:16]}.json"
    )
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
            "artifact_sha256": digest,
            "violations": list(violations),
        },
    )


__all__ = ["bound_native_business_is_valid", "quarantine_private_artifact"]
