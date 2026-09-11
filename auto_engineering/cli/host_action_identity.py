"""宿主 Action 的平台恢复与执行代际绑定。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from auto_engineering.host.path_contract import (
    worker_native_result_path,
    worker_outcome_path,
)


def resume_host_platform(root: Path, action: Mapping[str, object]) -> str | None:
    """恢复 active Action 时复用上一次宿主平台，避免合同跨宿主漂移。"""

    from auto_engineering.host import HostPlatform
    from auto_engineering.host.runtime_driver import HostRunLeaseStore

    thread_id = action.get("thread_id")
    message_id = action.get("message_id")
    if not isinstance(thread_id, str) or not isinstance(message_id, str):
        return None

    lease = HostRunLeaseStore(root).load()
    if (
        lease is not None
        and lease.thread_id == thread_id
        and lease.action_message_id == message_id
    ):
        try:
            return HostPlatform(lease.platform).value
        except ValueError:
            return None

    report_root = root.resolve() / ".ae-state" / "host-runtime" / "stop-reports"
    candidates: list[tuple[float, str]] = []
    for path in report_root.glob("*.json"):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if not isinstance(report, Mapping):
            continue
        if (
            report.get("thread_id") != thread_id
            or report.get("action_message_id") != message_id
            or report.get("disposition") != "CONTINUE"
            or report.get("lease_cleared") is not True
        ):
            continue
        platform = report.get("platform")
        if not isinstance(platform, str):
            continue
        try:
            normalized = HostPlatform(platform).value
        except ValueError:
            continue
        try:
            modified = path.stat().st_mtime
        except OSError:
            modified = 0.0
        candidates.append((modified, normalized))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    return None


def bind_worker_execution_identity(
    action: dict,
    root: Path,
    *,
    include_failure_journal: bool = True,
) -> dict:
    """为当前宿主会话绑定 Action generation；普通重读保持幂等。"""

    if not isinstance(action.get("spawn"), Mapping):
        return action
    message_id = action.get("message_id")
    if not isinstance(message_id, str) or not message_id:
        return action
    from auto_engineering.host import HostPlatform, detect_host
    from auto_engineering.host.runtime_driver import (
        HostRunLeaseStore,
        fencing_token_for,
        host_session_id_from_environ,
    )

    detection = detect_host()
    if detection.platform is HostPlatform.UNKNOWN:
        return action
    session_id = host_session_id_from_environ(detection.platform)
    if not session_id:
        return action
    previous = HostRunLeaseStore(root).load()
    failure_journal = (
        root / ".ae-state/host-runtime/outcomes" / f"{message_id}.json"
    )
    try:
        journal = json.loads(failure_journal.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        journal = None
    has_failure_journal = (
        include_failure_journal
        and isinstance(journal, Mapping)
        and journal.get("status") == "worker_failed"
    )
    recovered_generation: int | None = None
    if previous is not None and previous.action_message_id == message_id:
        generation = previous.execution_generation
        for candidate in range(previous.execution_generation, 0, -1):
            artifact_exists = _has_worker_generation_artifact(action, root, candidate)
            artifact_is_valid = _has_valid_native_result_artifact(
                action, root, candidate
            )
            if artifact_exists and (not has_failure_journal or artifact_is_valid):
                recovered_generation = candidate
                generation = candidate
                break
        if previous.host_session_id != session_id and recovered_generation is None:
            generation = previous.execution_generation + 1
    else:
        generation = 1
    if (
        has_failure_journal
        and recovered_generation is None
    ):
        failure_attempt = journal.get("failure_attempt")
        if isinstance(failure_attempt, int) and not isinstance(failure_attempt, bool):
            generation = max(generation, failure_attempt + 1)
    bound = dict(action)
    bound["execution_generation"] = generation
    bound["fencing_token"] = fencing_token_for(message_id, session_id, generation)
    return bound


def _has_worker_generation_artifact(
    action: Mapping[str, object], root: Path, generation: int
) -> bool:
    """判断当前 Action 的某一代是否已有宿主/Worker 事实。"""

    if generation < 1:
        return False
    message_id = action.get("message_id")
    spawn = action.get("spawn")
    invocations = spawn.get("invocations") if isinstance(spawn, Mapping) else None
    if not isinstance(message_id, str) or not message_id or not isinstance(invocations, list):
        return False
    root = root.resolve()
    for invocation in invocations:
        if not isinstance(invocation, Mapping):
            continue
        worker_id = invocation.get("worker_id")
        if not isinstance(worker_id, str) or not worker_id:
            continue
        for relative in (
            worker_native_result_path(message_id, worker_id, generation),
            worker_outcome_path(message_id, worker_id, generation),
        ):
            candidate = (root / relative).resolve()
            if root in candidate.parents and candidate.is_file():
                return True
    return False


def _has_valid_native_result_artifact(
    action: Mapping[str, object], root: Path, generation: int
) -> bool:
    """只有能被唯一 native 解析器接受的结果才可复用旧代。"""

    if generation < 1:
        return False
    message_id = action.get("message_id")
    spawn = action.get("spawn")
    invocations = spawn.get("invocations") if isinstance(spawn, Mapping) else None
    if not isinstance(message_id, str) or not message_id or not isinstance(invocations, list):
        return False
    from auto_engineering.host.worker_evidence import _native_business_artifact

    root = root.resolve()
    for invocation in invocations:
        if not isinstance(invocation, Mapping):
            continue
        worker_id = invocation.get("worker_id")
        if not isinstance(worker_id, str) or not worker_id:
            continue
        native_path = (root / worker_native_result_path(
            message_id, worker_id, generation
        )).resolve()
        if root not in native_path.parents or not native_path.is_file():
            continue
        try:
            native_value = json.loads(native_path.read_text(encoding="utf-8"))
            native_status = (
                native_value.get("status")
                if isinstance(native_value, Mapping)
                else None
            )
            _native_business_artifact(
                native_value,
                worker_id=worker_id,
                status=native_status if isinstance(native_status, str) else "completed",
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            continue
        return True
    return False


__all__ = ["bind_worker_execution_identity", "resume_host_platform"]
