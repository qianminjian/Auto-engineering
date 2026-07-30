"""v5.8 修复、Worker 与 Deep Audit 的确定性预算。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LoopBudgetPolicy:
    policy_id: str
    max_repair_cycles: int
    max_workers_per_stage: int
    max_workers_per_thread: int
    max_plate_audits: int
    max_system_audits: int


@dataclass(frozen=True, slots=True)
class LoopUsage:
    repair_cycles: int
    requested_workers: int
    completed_workers: int
    plate_audits: int
    system_audits: int
    next_stage: str = ""


@dataclass(frozen=True, slots=True)
class LoopBudgetOutcome:
    allowed: bool
    error_code: str | None = None


def evaluate_loop_budget(
    policy: LoopBudgetPolicy,
    usage: LoopUsage,
) -> LoopBudgetOutcome:
    if usage.repair_cycles >= policy.max_repair_cycles:
        return LoopBudgetOutcome(False, "REPAIR_CYCLE_LIMIT")
    if usage.requested_workers > policy.max_workers_per_stage:
        return LoopBudgetOutcome(False, "WORKER_STAGE_LIMIT")
    if (
        usage.completed_workers + usage.requested_workers
        > policy.max_workers_per_thread
    ):
        return LoopBudgetOutcome(False, "WORKER_THREAD_LIMIT")
    if (
        usage.next_stage == "plate_deep_audit"
        and usage.plate_audits >= policy.max_plate_audits
    ):
        return LoopBudgetOutcome(False, "PLATE_AUDIT_LIMIT")
    if (
        usage.next_stage == "system_deep_audit"
        and usage.system_audits >= policy.max_system_audits
    ):
        return LoopBudgetOutcome(False, "SYSTEM_AUDIT_LIMIT")
    return LoopBudgetOutcome(True)


__all__ = [
    "LoopBudgetOutcome",
    "LoopBudgetPolicy",
    "LoopUsage",
    "evaluate_loop_budget",
]
