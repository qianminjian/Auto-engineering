"""v2.0 — RoundResult dataclass (Round 汇总结果).

TaskOutcome 已迁移至 engine/models.py (P2-2, 2026-07-21).
通过 plan.py 重新导出. 向后兼容: 保留 from round import TaskOutcome.

RoundResult 仅剩测试消费方 (test_loop_round_extended.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from auto_engineering.gates.base import GateVerdict
from auto_engineering.loop.plan import TaskOutcome  # noqa: F401  # backward compat re-export

if __import__("typing").TYPE_CHECKING:
    from auto_engineering.loop.convergence import RoundHistory


@dataclass
class RoundResult:
    """一轮的汇总结果.

    Attributes:
        round_id: 轮次 ID
        outcomes: 每个 task 的执行结果 (顺序与输入无关, gather 不保证)
        gate_results: v2.2 Phase H — 本轮运行的 Gate 结果 dict[gate_name, GateVerdict].
                      包含 Gate 异常时的 failed GateVerdict (不传播给上层).
        history: v2.3 Phase G (P1.3) — 本轮的 RoundHistory 列表 (通常 1 个元素).
        started_at: 启动时间戳
        finished_at: 完成时间戳
    """

    round_id: int
    stage: str = ""
    outcomes: list[TaskOutcome] = field(default_factory=list)
    gate_results: dict[str, GateVerdict] = field(default_factory=dict)
    history: list[RoundHistory] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def duration(self) -> float:
        return self.finished_at - self.started_at

    @property
    def completed_count(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "completed")

    @property
    def failed_count(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "failed")

    @property
    def all_succeeded(self) -> bool:
        return all(o.status == "completed" for o in self.outcomes)

    @property
    def all_gates_passed(self) -> bool:
        """所有 Gate 都通过. 规则:
        - gate_results 为空 → True (无 Gate 跑, 不算失败)
        - 存在任一 verdict.passed=False → False
        - 否则 True
        """
        if not self.gate_results:
            return True
        return all(v.passed for v in self.gate_results.values())

    def files_changed(self) -> int:
        """估算本轮修改文件数 (基于成功 task 数量, future 接真实 diff)."""
        return self.completed_count


__all__ = [
    "RoundResult",
    "TaskOutcome",
]
