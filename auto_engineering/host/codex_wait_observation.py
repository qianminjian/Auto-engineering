"""Codex wait 的 bounded observation 持久化。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path


def next_wait_attempt(
    project_root: Path,
    action_message_id: str,
    worker: Mapping[str, object],
) -> int:
    from auto_engineering.host.worker_observation import observation_relative_path

    generation = worker.get("execution_generation")
    worker_id = worker.get("worker_id")
    if (
        not isinstance(generation, int)
        or isinstance(generation, bool)
        or not isinstance(worker_id, str)
    ):
        return 1
    path = project_root / observation_relative_path(
        action_message_id, worker_id, generation,
    )
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return 1
    attempt = previous.get("wait_attempt") if isinstance(previous, Mapping) else None
    return min(attempt + 1, 3) if isinstance(attempt, int) else 1


def record_codex_wait_observation(
    project_root: Path,
    worker: Mapping[str, object] | None,
    *,
    target_id: str,
    native_status: str,
) -> tuple[bool, str]:
    """把 wait 的宿主观察事实写入当前 Action-scoped 诊断文件。"""

    if worker is None:
        return False, ""
    from auto_engineering.host.runtime_driver import HostRunLeaseStore
    from auto_engineering.host.worker_observation import WorkerObservationRecord
    from auto_engineering.host.worker_observation_store import WorkerObservationStore

    try:
        lease = HostRunLeaseStore(project_root).load()
        generation = worker.get("execution_generation")
        fencing_token = worker.get("fencing_token")
        worker_id = worker.get("worker_id")
        if (
            lease is None
            or not isinstance(generation, int)
            or isinstance(generation, bool)
            or not isinstance(fencing_token, str)
            or not isinstance(worker_id, str)
        ):
            return False, ""
        attempt = next_wait_attempt(project_root, lease.action_message_id, worker)
        # wait 次数耗尽只是观察预算耗尽，不是 Worker 已超时。只有原生 API
        # 明确返回 timed_out，或后续 owner 探测/取消形成终态事实，才允许
        # 写入 timed_out；否则必须进入所有权不确定分支并阻止并发重跑。
        status = "unknown" if native_status == "running" and attempt >= 3 else native_status
        record = WorkerObservationRecord(
            schema_version="1.0",
            action_message_id=lease.action_message_id,
            worker_id=worker_id,
            execution_generation=generation,
            fencing_token=fencing_token,
            observed_at=datetime.now(UTC).isoformat(),
            native_status=status,
            wait_attempt=attempt,
            owner_known=status != "unknown",
            native_worker_handle=target_id,
        )
        WorkerObservationStore(project_root).save(record)
        return True, status
    except (OSError, TypeError, ValueError):
        return False, ""


__all__ = ["next_wait_attempt", "record_codex_wait_observation"]
