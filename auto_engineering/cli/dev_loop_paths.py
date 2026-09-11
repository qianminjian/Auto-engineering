"""dev-loop 的状态目录、路径绑定和 Action 工作文件清理。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Protocol

_STATE_GITIGNORE = "*\n!.gitignore\n"


class _DebugLogger(Protocol):
    def debug(self, message: str, *, exc_info: bool = False) -> None: ...


def write_json_atomically(path: Path, payload: object) -> None:
    """以同目录临时文件替换 Coordinator 产物，避免半写 JSON 被采集。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary_name)


def ensure_state_dir(root: Path) -> Path:
    """创建 Core 状态目录并阻止宿主把内部事实重复注入工作区 diff。"""

    state_dir = root / ".ae-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    ignore_file = state_dir / ".gitignore"
    if not ignore_file.exists():
        try:
            with ignore_file.open("x", encoding="utf-8") as handle:
                handle.write(_STATE_GITIGNORE)
        except FileExistsError:
            pass
    return state_dir


def ensure_event_db_path(root: Path) -> Path:
    """返回 EventStore 事实库路径。"""

    return ensure_state_dir(root) / "events.db"


def cleanup_completed_action_work_files(
    *,
    root: Path,
    result_file: Path,
    completed_action: Mapping[str, object] | None,
    next_action: Mapping[str, object],
    commit_confirmed: bool = True,
    map_bound_action_for_host: Callable[..., Mapping[str, object]],
    root_bound_path: Callable[[Path, Path], Path],
    logger: _DebugLogger,
) -> None:
    """仅在 Core 确认提交后删除 Action 临时交接文件。"""

    if not commit_confirmed or completed_action is None:
        return
    message_id = completed_action.get("message_id")
    if not isinstance(message_id, str) or not message_id:
        return
    if next_action.get("message_id") == message_id:
        return
    action_key = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:24]
    work_dir = root.resolve() / ".ae-state" / "host-runtime" / "work" / action_key
    if result_file.parent != work_dir:
        return
    for name in ("outcomes.json", "coordinator-result.json", "result.json"):
        with suppress(FileNotFoundError):
            (work_dir / name).unlink()

    private_paths: set[Path] = set()
    try:
        mapped = map_bound_action_for_host(
            dict(completed_action), root, include_failure_journal=False
        )
        host_execution = mapped.get("host_execution")
        workers = (
            host_execution.get("workers")
            if isinstance(host_execution, Mapping)
            else None
        )
        if isinstance(workers, list):
            private_paths.update(
                root_bound_path(Path(str(worker["outcome_path"])), root)
                for worker in workers
                if isinstance(worker, Mapping)
                and isinstance(worker.get("outcome_path"), str)
            )
    except Exception:
        logger.debug("generation-bound worker artifact cleanup skipped", exc_info=True)
    try:
        from auto_engineering.host.spawn_contract import SpawnPlan

        plan = SpawnPlan.from_action(completed_action)
        for invocation in plan.invocations:
            private_paths.add(root_bound_path(Path(invocation.outcome_path), root))
    except Exception:
        logger.debug("worker private artifact cleanup skipped", exc_info=True)
    for private_path in private_paths:
        if private_path.is_relative_to(root):
            with suppress(FileNotFoundError):
                private_path.unlink()
    with suppress(OSError):
        work_dir.rmdir()


__all__ = [
    "cleanup_completed_action_work_files",
    "ensure_event_db_path",
    "ensure_state_dir",
    "write_json_atomically",
]
