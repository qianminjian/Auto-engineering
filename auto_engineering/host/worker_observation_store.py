"""Host Runtime Worker 观察事实的原子存储。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from auto_engineering.host.worker_observation import (
    WorkerObservationContractError,
    WorkerObservationRecord,
    observation_path_for,
)


class WorkerObservationStore:
    """原子保存/读取当前 Action 的最新 Worker 观察。"""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()

    def save(self, record: WorkerObservationRecord) -> Path:
        path = observation_path_for(self.project_root, record)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            record.to_dict(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return path

    def load(self, record: WorkerObservationRecord) -> WorkerObservationRecord | None:
        path = observation_path_for(self.project_root, record)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkerObservationContractError(
                "WORKER_OBSERVATION_RECORD_CORRUPT"
            ) from exc
        loaded = WorkerObservationRecord.from_dict(raw)
        if loaded != record:
            raise WorkerObservationContractError(
                "WORKER_OBSERVATION_RECORD_IDENTITY_MISMATCH"
            )
        return loaded


__all__ = ["WorkerObservationStore"]
