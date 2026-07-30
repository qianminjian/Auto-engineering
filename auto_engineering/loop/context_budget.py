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
    max_session_ticks: int
    max_session_wall_seconds: int
    soft_input_units: int
    hard_input_units: int
    max_prompt_bytes: int

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ValueError("policy_id 必须为非空字符串")
        limits = (
            self.max_session_ticks,
            self.max_session_wall_seconds,
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
    """对相同策略和观测产生相同决策；未知 input 使用其他硬边界。"""
    if usage.prompt_bytes > policy.max_prompt_bytes:
        return BudgetOutcome(
            BudgetDecision.REJECT,
            reason="prompt_hard_limit",
            error_code="ACTION_CONTEXT_TOO_LARGE",
        )
    if usage.input_units is not None:
        if usage.input_units >= policy.hard_input_units:
            return BudgetOutcome(BudgetDecision.ROLLOVER, "context_hard_limit")
        if usage.input_units >= policy.soft_input_units:
            return BudgetOutcome(BudgetDecision.ROLLOVER, "context_soft_limit")
    if usage.ticks >= policy.max_session_ticks:
        return BudgetOutcome(BudgetDecision.ROLLOVER, "tick_limit")
    if usage.wall_seconds >= policy.max_session_wall_seconds:
        return BudgetOutcome(BudgetDecision.ROLLOVER, "time_limit")
    return BudgetOutcome(BudgetDecision.CONTINUE)


__all__ = [
    "BudgetDecision",
    "BudgetOutcome",
    "ContextBudgetPolicy",
    "ContextUsage",
    "evaluate_budget",
]
