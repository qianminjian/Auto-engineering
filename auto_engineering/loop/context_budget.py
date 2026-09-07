"""v5.8 宿主会话上下文预算的确定性策略。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BudgetDecision(StrEnum):
    CONTINUE = "continue"
    ROLLOVER = "rollover"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class ContextBudgetPolicy:
    policy_id: str
    soft_input_units: int
    hard_input_units: int
    max_prompt_bytes: int

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ValueError("policy_id 必须为非空字符串")
        limits = (
            self.soft_input_units,
            self.hard_input_units,
            self.max_prompt_bytes,
        )
        if any(limit <= 0 for limit in limits):
            raise ValueError("ContextBudget 阈值必须为正整数")
        if self.soft_input_units > self.hard_input_units:
            raise ValueError("soft_input_units 不得大于 hard_input_units")


@dataclass(frozen=True, slots=True)
class ContextUsage:
    ticks: int
    wall_seconds: int
    input_units: int | None
    prompt_bytes: int
    estimated: bool = False


@dataclass(frozen=True, slots=True)
class BudgetOutcome:
    decision: BudgetDecision
    reason: str | None = None
    error_code: str | None = None


def evaluate_budget(
    policy: ContextBudgetPolicy,
    usage: ContextUsage,
) -> BudgetOutcome:
    """只校验单个 Action 的 Prompt 大小；宿主会话生命周期不由 Core 切换。"""
    if usage.prompt_bytes > policy.max_prompt_bytes:
        return BudgetOutcome(
            BudgetDecision.REJECT,
            reason="prompt_hard_limit",
            error_code="ACTION_CONTEXT_TOO_LARGE",
        )
    return BudgetOutcome(BudgetDecision.CONTINUE)


__all__ = [
    "BudgetDecision",
    "BudgetOutcome",
    "ContextBudgetPolicy",
    "ContextUsage",
    "evaluate_budget",
]
