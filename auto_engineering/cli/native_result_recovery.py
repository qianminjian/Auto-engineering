"""原生 Worker 结果漏回写的恢复探测。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path

from auto_engineering.host.worker_evidence import (
    HostEvidenceValidationError,
    _native_business_artifact,
)


def native_result_worker_ids(
    host_execution: object,
    *,
    action: Mapping[str, object],
    root: Path,
    root_bound_path_fn: Callable[[Path, Path], Path],
) -> list[str]:
    """返回当前 Action 中能被唯一 native parser 接受的 Worker。

    恢复探测不能只看“文件存在且是 JSON”：那会把空 envelope、宿主字段
    污染或多对象正文误投影为 attestation pending。这里与
    ``record-worker-outcome`` 共用同一个业务解析器；探测只返回真正可修复
    的 Worker，不能替代 record 边界写入宿主事实。
    """

    workers = (
        host_execution.get("workers")
        if isinstance(host_execution, Mapping)
        else None
    )
    if not isinstance(workers, list):
        return []
    spawn = action.get("spawn")
    invocations = spawn.get("invocations") if isinstance(spawn, Mapping) else None
    allowed_workers = {
        item.get("worker_id")
        for item in invocations
        if isinstance(item, Mapping) and isinstance(item.get("worker_id"), str)
    } if isinstance(invocations, list) else set()
    if not allowed_workers:
        return []
    ready: list[str] = []
    for worker in workers:
        if not isinstance(worker, Mapping):
            continue
        worker_id = worker.get("worker_id")
        native_ref = worker.get("native_result_path")
        if (
            not isinstance(worker_id, str)
            or not worker_id
            or worker_id not in allowed_workers
        ):
            continue
        if not isinstance(native_ref, str) or not native_ref:
            continue
        native_path = root_bound_path_fn(Path(native_ref), root)
        if native_path == root or root not in native_path.parents:
            continue
        try:
            native_value = json.loads(native_path.read_text(encoding="utf-8"))
            native_status_value = (
                native_value.get("status")
                if isinstance(native_value, Mapping)
                else None
            )
            native_status = (
                native_status_value
                if isinstance(native_status_value, str)
                else "completed"
            )
            _native_business_artifact(
                native_value,
                worker_id=worker_id,
                status=native_status,
            )
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
            HostEvidenceValidationError,
        ):
            continue
        ready.append(worker_id)
    return ready


__all__ = ["native_result_worker_ids"]
