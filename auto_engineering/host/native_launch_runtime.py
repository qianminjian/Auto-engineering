"""原生 Guard 读取当前 lease 与 Action 的运行态事实。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from auto_engineering.host import HostPlatform
from auto_engineering.host.native_launch_messages import NativeLaunchGuardError


def active_native_workers(
    *,
    project_root: Path,
    platform: HostPlatform,
) -> list[Mapping[str, object]] | None:
    """读取当前租约绑定 Action 的宿主 Worker 模板。"""

    from auto_engineering.host.adapters import adapter_for
    from auto_engineering.host.runtime_driver import HostRunLeaseError, HostRunLeaseStore
    from auto_engineering.loop.event_store import SQLiteEventStore

    try:
        lease = HostRunLeaseStore(project_root).load()
    except HostRunLeaseError as exc:
        raise NativeLaunchGuardError(str(exc)) from exc
    if lease is None or lease.disposition != "CONTINUE":
        return None
    if lease.platform != platform.value:
        raise NativeLaunchGuardError("NATIVE_HOST_PLATFORM_MISMATCH")
    events_path = project_root.resolve() / ".ae-state" / "events.db"
    if not events_path.is_file():
        raise NativeLaunchGuardError("NATIVE_ACTIVE_ACTION_UNAVAILABLE")
    events = SQLiteEventStore(events_path)
    try:
        action = events.load_action_snapshot(lease.thread_id)
    finally:
        events.close()
    if not isinstance(action, Mapping) or action.get("message_id") != lease.action_message_id:
        raise NativeLaunchGuardError("NATIVE_ACTIVE_ACTION_MISMATCH")
    if action.get("project_root") != str(project_root.resolve()):
        raise NativeLaunchGuardError("NATIVE_PROJECT_ROOT_MISMATCH")
    bound_action = dict(action)
    bound_action["execution_generation"] = lease.execution_generation
    adapter = adapter_for(platform)
    profile = adapter.profile(
        detected=adapter.capabilities,
        authorized=adapter.capabilities,
    )
    try:
        mapped = adapter.map_action(bound_action, profile=profile).payload
    except (OSError, TypeError, ValueError) as exc:
        raise NativeLaunchGuardError("NATIVE_ACTIVE_ACTION_INVALID") from exc
    host_execution = mapped.get("host_execution")
    if not isinstance(host_execution, Mapping):
        raise NativeLaunchGuardError("NATIVE_WORKER_TEMPLATE_UNAVAILABLE")
    if "workers" not in host_execution:
        return []
    workers = host_execution.get("workers")
    if not isinstance(workers, list) or not all(
        isinstance(item, Mapping) for item in workers
    ):
        raise NativeLaunchGuardError("NATIVE_WORKER_TEMPLATE_UNAVAILABLE")
    observation = host_execution.get("worker_observation")
    if isinstance(observation, Mapping):
        return [
            {**dict(item), "worker_observation": dict(observation)}
            for item in workers
        ]
    return workers


def spawn_action_requires_lease(project_root: Path) -> bool:
    """判断无 lease 时是否仍有未恢复的 EventStore Worker Action。"""

    events_path = project_root.resolve() / ".ae-state" / "events.db"
    if not events_path.is_file():
        return False
    from auto_engineering.loop.event_store import SQLiteEventStore

    events = SQLiteEventStore(events_path)
    try:
        unfinished = [str(thread_id) for thread_id in events.unfinished_threads()]
        if len(unfinished) > 1:
            # 多个未终态 thread 时必须阻止无 lease 的新 Worker，避免把
            # 项目级状态歧义误判为“没有需要恢复的 Action”。
            return True
        if not unfinished:
            return False
        thread_id = unfinished[0]
        if not isinstance(thread_id, str) or not thread_id:
            return False
        action = events.load_action_snapshot(thread_id)
        if not isinstance(action, Mapping):
            return False
        if action.get("project_root") != str(project_root.resolve()):
            return False
        host_execution = action.get("host_execution")
        workers = host_execution.get("workers") if isinstance(host_execution, Mapping) else None
        return isinstance(workers, list) and bool(workers)
    except (OSError, TypeError, ValueError):
        return False
    finally:
        events.close()


__all__ = ["active_native_workers", "spawn_action_requires_lease"]
