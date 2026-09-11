"""原生 Worker 结果漏回写的恢复探测。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path


def native_result_worker_ids(
    host_execution: object,
    *,
    root: Path,
    root_bound_path_fn: Callable[[Path, Path], Path],
) -> list[str]:
    """返回当前 Action 中已落盘且可解析的 native result Worker。"""

    workers = (
        host_execution.get("workers")
        if isinstance(host_execution, Mapping)
        else None
    )
    if not isinstance(workers, list):
        return []
    ready: list[str] = []
    for worker in workers:
        if not isinstance(worker, Mapping):
            continue
        worker_id = worker.get("worker_id")
        native_ref = worker.get("native_result_path")
        if not isinstance(worker_id, str) or not worker_id:
            continue
        if not isinstance(native_ref, str) or not native_ref:
            continue
        native_path = root_bound_path_fn(Path(native_ref), root)
        try:
            native_value = json.loads(native_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            continue
        if isinstance(native_value, (Mapping, list)) and native_value:
            ready.append(worker_id)
    return ready


__all__ = ["native_result_worker_ids"]
