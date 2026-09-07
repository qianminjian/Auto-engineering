"""Architect Result 的唯一候选准备边界。"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.architecture_candidate import ArchitectureCandidateBuilder
from auto_engineering.loop.plan_reconciliation import PlanReconciliationResult


@dataclass(frozen=True, slots=True)
class ArchitectPreparation:
    """供 Architect Handler 生成事件、供激活 Effect 消费的候选。"""

    candidate: dict[str, Any]
    evidence_changes: dict[str, Any]
    plan_reconciliation_changes: dict[str, Any] | None = None
    superseded_tasks: tuple[dict[str, str], ...] = ()
    plan_patch_base_revision: int | None = None


def is_same_action_repair(*, error_code: str, current_stage: str | None) -> bool:
    """判断 Architect 候选拒绝是否应留在当前 Coordinator Action。"""

    return error_code == "ARCHITECT_PLAN_INVALID" and current_stage == "architect"


class ArchitectResultPreparer:
    """只计算候选，不修改 EngineState Projection。"""

    def prepare(
        self,
        state: EngineState,
        result: Mapping[str, Any],
    ) -> ArchitectPreparation:
        if result.get("result_type") == "plan_reconciliation":
            return self._prepare_reconciliation(state, result)

        patch = result.get("plan_patch")
        if isinstance(patch, Mapping):
            candidate = ArchitectureCandidateBuilder().build(
                result,
                active_revision=state.plan_refine_count,
                current_baseline=state.architecture_baseline,
            )
            raw_batches = patch.get("add_batches", [])
            batches = self._objects(raw_batches, "plan_patch.add_batches")
            base_revision = patch.get("base_revision")
            if not isinstance(base_revision, int) or isinstance(base_revision, bool):
                base_revision = state.plan_refine_count
        else:
            candidate = deepcopy(dict(result))
            batches = self._objects(
                result.get("batch_plan", []),
                "batch_plan",
            )
            base_revision = None

        return ArchitectPreparation(
            candidate=candidate,
            evidence_changes=self._evidence_changes(
                result,
                batch_plan=batches,
                contracts=candidate.get("contracts", {}),
            ),
            plan_patch_base_revision=base_revision,
        )

    def _prepare_reconciliation(
        self,
        state: EngineState,
        result: Mapping[str, Any],
    ) -> ArchitectPreparation:
        raw = state._runtime_ctx.get("plan_reconciliation_candidate")
        if not isinstance(raw, PlanReconciliationResult):
            raise ValueError("PLAN_RECONCILE 候选未经 Core 校验")
        current = raw.current_batch_plan(state.batch_plan)
        candidate = {
            "reconciled": True,
            "batch_plan": deepcopy(current),
            "contracts": dict(result.get("contracts", {})),
            "obligations": list(result.get("obligations", [])),
        }
        retired = tuple(
            {"task_id": task_id, "status": status}
            for status, task_ids in (
                ("superseded", raw.superseded),
                ("unverifiable", raw.unverifiable),
            )
            for task_id in task_ids
        )
        reconciliation = {
            "source_revision": raw.source_revision,
            "current_revision": raw.current_revision,
            "verified_completed": len(raw.verified_completed),
            "still_pending": len(raw.still_pending),
            "superseded": len(raw.superseded),
            "unverifiable": len(raw.unverifiable),
        }
        state_reconciliation = {
            **(state.state_reconciliation or {}),
            "status": "reconciled",
            "choice": "reconcile",
        }
        return ArchitectPreparation(
            candidate=candidate,
            evidence_changes=self._evidence_changes(
                result,
                batch_plan=current,
                contracts=candidate["contracts"],
            ),
            plan_reconciliation_changes={
                "plan_reconciliation": reconciliation,
                "state_reconciliation": state_reconciliation,
            },
            superseded_tasks=retired,
        )

    @staticmethod
    def _evidence_changes(
        result: Mapping[str, Any],
        *,
        batch_plan: list[dict[str, Any]],
        contracts: object,
    ) -> dict[str, Any]:
        return {
            "plan": result.get("plan", ""),
            "file_list": list(result.get("file_list", [])),
            "batch_plan": batch_plan,
            "contracts": dict(contracts) if isinstance(contracts, Mapping) else {},
        }

    @staticmethod
    def _objects(value: object, field: str) -> list[dict[str, Any]]:
        if not isinstance(value, list) or not all(
            isinstance(item, Mapping) for item in value
        ):
            raise ValueError(f"{field} 必须为 object array")
        return [deepcopy(dict(item)) for item in value]


__all__ = [
    "ArchitectPreparation",
    "ArchitectResultPreparer",
    "is_same_action_repair",
]
