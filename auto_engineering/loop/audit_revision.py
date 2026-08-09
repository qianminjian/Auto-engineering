"""Deep Audit 的稳定 revision key 与内容指纹。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.state import EngineState
from auto_engineering.loop.guardrails.stateful import aggregate_files_sha


class AuditRevisionService:
    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    @staticmethod
    def key(stage: str, batch_state: BatchState | None) -> str:
        if stage == "plate_deep_audit" and batch_state is not None:
            try:
                return f"{stage}:{batch_state.current_plate().name}"
            except (AssertionError, IndexError):
                pass
        return stage

    def fingerprint(
        self,
        stage: str,
        state: EngineState,
        batch_state: BatchState | None,
    ) -> str:
        snapshot = state.developer_snapshot or {}
        files = snapshot.get("files_changed") or state.files_changed
        scope = {
            "stage": stage,
            "key": self.key(stage, batch_state),
            "files_sha": aggregate_files_sha(
                list(files or []),
                self._project_root,
            ),
            "plan_refine_count": state.plan_refine_count,
            "coverage_map": state.coverage_map or [],
        }
        encoded = json.dumps(
            scope,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


__all__ = ["AuditRevisionService"]
