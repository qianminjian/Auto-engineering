"""Codex native_wait 超时的终止所有权验证。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from auto_engineering.host.worker_evidence import NativeWorkerOutcome
from auto_engineering.host.worker_observation import (
    WorkerObservationContractError,
    WorkerObservationRecord,
)


def timeout_ownership_issues(
    *,
    project_root: Path,
    action: Mapping[str, Any],
    templates: Mapping[str, Mapping[str, Any]],
    outcomes: Sequence[NativeWorkerOutcome],
    bindings: Mapping[str, tuple[int | None, str | None]],
) -> tuple[str, ...]:
    """返回未形成同一 Worker 终止事实的 timeout 诊断。"""

    host_execution = action.get("host_execution")
    contract = (
        host_execution.get("worker_observation")
        if isinstance(host_execution, Mapping)
        else None
    )
    if not isinstance(contract, Mapping) or contract.get("mode") != "native_wait":
        return ()
    message_id = action.get("message_id")
    issues: list[str] = []
    for outcome in outcomes:
        is_timeout = outcome.status in {"timeout", "timed_out"} or (
            isinstance(outcome.payload, Mapping)
            and outcome.payload.get("error_code") in {
                "HOST_WORKER_TIMEOUT", "HOST_WORKER_TIMED_OUT",
            }
        )
        if not is_timeout:
            continue
        template = templates.get(outcome.worker_id)
        observation_ref = (
            template.get("observation_path")
            if isinstance(template, Mapping)
            else None
        )
        if not isinstance(observation_ref, str) or not observation_ref:
            issues.append(f"WORKER_OBSERVATION_MISSING:{outcome.worker_id}")
            continue
        observation_path = (project_root / observation_ref).resolve()
        if (
            observation_path == project_root
            or project_root not in observation_path.parents
        ):
            issues.append(f"WORKER_OBSERVATION_PATH_INVALID:{outcome.worker_id}")
            continue
        try:
            record = WorkerObservationRecord.from_dict(
                json.loads(observation_path.read_text(encoding="utf-8"))
            )
        except FileNotFoundError:
            issues.append(f"WORKER_OBSERVATION_MISSING:{outcome.worker_id}")
            continue
        except (
            OSError, UnicodeDecodeError, json.JSONDecodeError,
            WorkerObservationContractError, TypeError, ValueError,
        ):
            issues.append(f"WORKER_OBSERVATION_INVALID:{outcome.worker_id}")
            continue
        expected_generation, expected_fence = bindings.get(
            outcome.worker_id, (None, None)
        )
        if (
            record.action_message_id != message_id
            or record.worker_id != outcome.worker_id
            or record.execution_generation != expected_generation
            or record.fencing_token != expected_fence
            or record.native_status != "timed_out"
            or not record.owner_known
            or record.native_worker_handle != outcome.native_worker_handle
        ):
            issues.append(f"WORKER_OWNER_UNCERTAIN:{outcome.worker_id}")
    return tuple(issues)


__all__ = ["timeout_ownership_issues"]
