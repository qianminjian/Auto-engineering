"""PLAN_RECONCILE 候选的确定性任务分类与证据校验。"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PlanReconciliationError(ValueError):
    """计划协调候选不满足完成事实与 ID 不变量。"""


@dataclass(frozen=True, slots=True)
class PlanReconciliationResult:
    source_revision: int
    current_revision: int
    verified_completed: tuple[str, ...]
    still_pending: tuple[str, ...]
    superseded: tuple[str, ...]
    unverifiable: tuple[str, ...]
    new_batch_plan: tuple[Mapping[str, Any], ...]


class PlanReconciliationValidator:
    _STATUSES = frozenset({
        "verified_completed",
        "still_pending",
        "superseded",
        "unverifiable",
    })

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root.resolve()

    def validate(
        self,
        *,
        old_batch_plan: Sequence[Mapping[str, Any]],
        candidate: Mapping[str, Any],
        evidence: Mapping[str, Mapping[str, Any]],
    ) -> PlanReconciliationResult:
        source_revision = candidate.get("source_revision")
        if not isinstance(source_revision, int) or isinstance(source_revision, bool) or source_revision < 1:
            raise PlanReconciliationError("source_revision 无效")
        old_tasks = self._flatten_tasks(old_batch_plan)
        raw_classifications = candidate.get("classifications")
        if not isinstance(raw_classifications, list):
            raise PlanReconciliationError("classifications 必须为数组")
        classifications: dict[str, Mapping[str, Any]] = {}
        for item in raw_classifications:
            if not isinstance(item, Mapping):
                raise PlanReconciliationError("任务分类必须为 object")
            task_id = item.get("task_id")
            status = item.get("status")
            if not isinstance(task_id, str) or status not in self._STATUSES:
                raise PlanReconciliationError("任务分类字段无效")
            if task_id in classifications:
                raise PlanReconciliationError("任务分类集合包含重复项")
            classifications[task_id] = item
        if set(classifications) != set(old_tasks):
            raise PlanReconciliationError("任务分类集合必须与旧任务完全一致")

        grouped: dict[str, list[str]] = {status: [] for status in self._STATUSES}
        for task_id, item in classifications.items():
            status = str(item["status"])
            if status == "verified_completed":
                self._validate_completed_evidence(
                    task_id=task_id,
                    task=old_tasks[task_id],
                    classification=item,
                    evidence=evidence,
                )
            elif not isinstance(item.get("reason"), str) or not item.get("reason"):
                raise PlanReconciliationError(f"{task_id} 的 {status} 分类缺少 reason")
            grouped[status].append(task_id)

        raw_new_plan = candidate.get("new_batch_plan")
        if not isinstance(raw_new_plan, list):
            raise PlanReconciliationError("new_batch_plan 必须为数组")
        new_tasks = self._flatten_tasks(raw_new_plan)
        retired_ids = set(grouped["superseded"]) | set(grouped["unverifiable"])
        reused = sorted(set(new_tasks) & retired_ids)
        if reused:
            raise PlanReconciliationError("新任务不得复用已失效任务 ID: " + ", ".join(reused))

        return PlanReconciliationResult(
            source_revision=source_revision,
            current_revision=source_revision + 1,
            verified_completed=tuple(sorted(grouped["verified_completed"])),
            still_pending=tuple(sorted(grouped["still_pending"])),
            superseded=tuple(sorted(grouped["superseded"])),
            unverifiable=tuple(sorted(grouped["unverifiable"])),
            new_batch_plan=tuple(dict(batch) for batch in raw_new_plan),
        )

    @staticmethod
    def _flatten_tasks(
        batches: Sequence[Mapping[str, Any]],
    ) -> dict[str, Mapping[str, Any]]:
        tasks: dict[str, Mapping[str, Any]] = {}
        for batch in batches:
            raw_tasks = batch.get("tasks", [])
            if not isinstance(raw_tasks, list):
                raise PlanReconciliationError("batch tasks 必须为数组")
            for task in raw_tasks:
                if not isinstance(task, Mapping) or not isinstance(task.get("id"), str):
                    raise PlanReconciliationError("task id 无效")
                task_id = str(task["id"])
                if task_id in tasks:
                    raise PlanReconciliationError(f"重复 task id: {task_id}")
                tasks[task_id] = task
        return tasks

    def _validate_completed_evidence(
        self,
        *,
        task_id: str,
        task: Mapping[str, Any],
        classification: Mapping[str, Any],
        evidence: Mapping[str, Mapping[str, Any]],
    ) -> None:
        evidence_ref = classification.get("evidence_ref")
        item = evidence.get(evidence_ref) if isinstance(evidence_ref, str) else None
        if item is None or item.get("task_id") != task_id or item.get("gate_passed") is not True:
            raise PlanReconciliationError(f"{task_id} 缺少 Core Gate 完成证据")
        files = item.get("files")
        if not isinstance(files, Mapping) or not files:
            raise PlanReconciliationError(f"{task_id} 缺少文件证据")
        targets = task.get("file_targets", [])
        if not isinstance(targets, list) or not set(targets) <= set(files):
            raise PlanReconciliationError(f"{task_id} 文件证据未覆盖任务目标")
        for relative, expected in files.items():
            if not isinstance(relative, str) or not isinstance(expected, str):
                raise PlanReconciliationError(f"{task_id} 文件证据无效")
            path = (self._project_root / relative).resolve()
            if self._project_root not in path.parents or not path.is_file():
                raise PlanReconciliationError(f"{task_id} 文件证据路径无效")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise PlanReconciliationError(f"{task_id} 文件证据已失效")


__all__ = [
    "PlanReconciliationError",
    "PlanReconciliationResult",
    "PlanReconciliationValidator",
]
