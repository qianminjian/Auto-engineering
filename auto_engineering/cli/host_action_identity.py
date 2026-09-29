"""宿主 Action 的平台恢复与执行代际绑定。"""

from __future__ import annotations

import json
import re
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
        and journal.get("status") in {"worker_failed", "protocol_failed"}
    )
    recovered_generation: int | None = None
    if previous is not None and previous.action_message_id == message_id:
        generation = previous.execution_generation
        if previous.host_session_id != session_id:
            # 跨会话只能复用 canonical parser 已确认的 native 事实。仅凭
            # 文件存在不能恢复旧代：半写入、空对象或自然语言回包都可能
            # 占住旧路径，随后让新的宿主在同一 generation 无限重复失败。
            # 同会话则保留当前代，由唯一 record 边界完成原地 repair。
            for candidate in range(previous.execution_generation, 0, -1):
                if _has_recoverable_worker_artifact(action, root, candidate):
                    recovered_generation = candidate
                    generation = candidate
                    break
            if recovered_generation is None:
                generation = previous.execution_generation + 1
    else:
        generation = 1
        existing_generations = _existing_worker_generations(action, root)
        if existing_generations:
            latest = max(existing_generations)
            # Stop Report 清理 lease 后，不能无条件回到 generation 1。
            # 只有最新代的 native 或私有业务 artifact 能被唯一边界接受时
            # 才复用；否则递增到新路径，保留旧证据并避免重复消费半成品。
            generation = (
                latest
                if _has_recoverable_worker_artifact(action, root, latest)
                else latest + 1
            )
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
    spawn = action.get("spawn")
    if isinstance(spawn, Mapping) and isinstance(spawn.get("invocations"), list):
        bound_spawn = dict(spawn)
        bound_spawn["invocations"] = [
            {
                **invocation,
                "outcome_path": worker_outcome_path(
                    message_id,
                    invocation["worker_id"],
                    generation,
                ),
            }
            if isinstance(invocation, Mapping)
            and isinstance(invocation.get("worker_id"), str)
            else invocation
            for invocation in spawn["invocations"]
        ]
        bound["spawn"] = bound_spawn
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


def _existing_worker_generations(
    action: Mapping[str, object], root: Path
) -> set[int]:
    """列出当前 Action 预期路径上已经落盘的 generation。"""

    message_id = action.get("message_id")
    spawn = action.get("spawn")
    invocations = spawn.get("invocations") if isinstance(spawn, Mapping) else None
    if not isinstance(message_id, str) or not message_id or not isinstance(invocations, list):
        return set()
    root = root.resolve()
    generations: set[int] = set()
    for invocation in invocations:
        if not isinstance(invocation, Mapping):
            continue
        worker_id = invocation.get("worker_id")
        if not isinstance(worker_id, str) or not worker_id:
            continue
        for relative in (
            worker_native_result_path(message_id, worker_id, 1),
            worker_outcome_path(message_id, worker_id, 1),
        ):
            directory = (root / relative).resolve().parent
            prefix = Path(relative).name.removesuffix("-g1.json")
            if directory == root or root not in directory.parents:
                continue
            try:
                candidates = directory.glob(f"{prefix}-g*.json")
            except OSError:
                continue
            pattern = re.compile(rf"^{re.escape(prefix)}-g([1-9][0-9]*)\.json$")
            for candidate in candidates:
                match = pattern.fullmatch(candidate.name)
                if match is not None and candidate.is_file():
                    generations.add(int(match.group(1)))
    return generations


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


def _has_valid_private_outcome_artifact(
    action: Mapping[str, object], root: Path, generation: int
) -> bool:
    """判断跨会话是否已有可继续 attestation 的私有业务 outcome。"""

    if generation < 1:
        return False
    message_id = action.get("message_id")
    spawn = action.get("spawn")
    invocations = spawn.get("invocations") if isinstance(spawn, Mapping) else None
    if not isinstance(message_id, str) or not message_id or not isinstance(invocations, list):
        return False
    root = root.resolve()
    from auto_engineering.host.worker_evidence import parse_private_worker_artifact

    for invocation in invocations:
        if not isinstance(invocation, Mapping):
            continue
        worker_id = invocation.get("worker_id")
        if not isinstance(worker_id, str) or not worker_id:
            continue
        outcome_path = (root / worker_outcome_path(
            message_id, worker_id, generation
        )).resolve()
        if root not in outcome_path.parents or not outcome_path.is_file():
            continue
        try:
            raw = json.loads(outcome_path.read_text(encoding="utf-8"))
            expected_format = action.get("expected_format")
            parse_private_worker_artifact(
                raw,
                worker_id=worker_id,
                status="completed",
                expected_format=(
                    expected_format if isinstance(expected_format, Mapping) else None
                ),
            )
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
        ):
            continue
        return True
    return False


def _has_recoverable_worker_artifact(
    action: Mapping[str, object], root: Path, generation: int
) -> bool:
    """返回可在新宿主中继续绑定的唯一 Worker artifact 判断。"""

    return _has_valid_native_result_artifact(action, root, generation) or (
        _has_valid_private_outcome_artifact(action, root, generation)
    )


__all__ = ["bind_worker_execution_identity", "resume_host_platform"]
