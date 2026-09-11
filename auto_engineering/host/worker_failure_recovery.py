"""Worker 失败记录的恢复读取。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from auto_engineering.host.outcome_file import OutcomeFileError, parse_outcomes_document
from auto_engineering.host.spawn_contract import SpawnContractError, SpawnPlan
from auto_engineering.host.worker_evidence import (
    NativeWorkerOutcome,
)


def read_recorded_failure_outcomes(
    project_root: Path,
    action: Mapping[str, Any],
) -> list[NativeWorkerOutcome] | None:
    """读取已由 record 边界固化的失败事实，避免退回 synthetic missing。"""

    host_execution = action.get("host_execution")
    work_files = (
        host_execution.get("work_files")
        if isinstance(host_execution, Mapping)
        else None
    )
    outcomes_ref = (
        work_files.get("outcomes")
        if isinstance(work_files, Mapping)
        else None
    )
    if not isinstance(outcomes_ref, str) or not outcomes_ref:
        return None
    outcomes_ref_path = Path(outcomes_ref)
    outcomes_path = (
        outcomes_ref_path.resolve()
        if outcomes_ref_path.is_absolute()
        else (project_root / outcomes_ref_path).resolve()
    )
    if outcomes_path == project_root or project_root not in outcomes_path.parents:
        return None
    try:
        raw = json.loads(outcomes_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    try:
        items = parse_outcomes_document(raw)
    except OutcomeFileError:
        return None
    try:
        outcomes = [NativeWorkerOutcome(**item) for item in items]
    except (TypeError, ValueError):
        return None
    try:
        expected = {
            invocation.worker_id
            for invocation in SpawnPlan.for_recording(action).invocations
        }
    except SpawnContractError:
        return None
    failure_statuses = {"errored", "failed", "cancelled", "timeout", "timed_out"}
    if (
        {outcome.worker_id for outcome in outcomes} != expected
        or any(outcome.status not in failure_statuses for outcome in outcomes)
    ):
        return None
    return outcomes


__all__ = ["read_recorded_failure_outcomes"]
