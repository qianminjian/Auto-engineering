"""收敛判定协作策略 (v5.4 审计 P1-1, v5.5 审计 P1-3 → module-level functions).

从 Orchestrator 提取收敛判定相关职责:
    - Judge 评估 + Gate 反向补丁 (evaluate)
    - Gate 状态收集与校验 (collect_latest_gates, check_gates_passed)
    - 诊断日志 (_log_gate_block)
Orchestrator 委托调用, 减少 Orchestrator 方法数.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from auto_engineering.gates.base import GateVerdict
    from auto_engineering.loop.convergence import ConvergenceJudge, ConvergenceVerdict
    from auto_engineering.loop.round import RoundHistory

__all__ = ["check_gates_passed", "collect_latest_gates", "evaluate"]

_logger = logging.getLogger("ae.loop.convergence_facade")


def evaluate(
    judge: ConvergenceJudge,
    history: list[RoundHistory],
    current_stage: str,
) -> ConvergenceVerdict | None:
    """评估是否应停止循环. 返回 ConvergenceVerdict (应停止) 或 None (继续).

    包含 Bug 3 方案 C 的 gate 反向补丁:
    judge 判定 QUALITY_PASS 但 gate 未全过 → 不停止.
    """
    verdict = judge.evaluate(history=list(history))
    if not verdict.should_stop:
        return None

    latest_gates = collect_latest_gates(history)
    if latest_gates and not check_gates_passed(latest_gates):
        _log_gate_block(verdict, latest_gates, current_stage)
        return None

    return verdict


def collect_latest_gates(history: list[RoundHistory]) -> dict[str, GateVerdict]:
    """收集最近一轮 RoundHistory 的 gate_results."""
    if not history:
        return {}
    return history[-1].gate_results or {}


def check_gates_passed(gate_results: dict[str, GateVerdict]) -> bool:
    """所有 gate 都通过. 空 dict (无 gate 配置) 返回 True."""
    if not gate_results:
        return True
    for verdict in gate_results.values():
        if not verdict.passed:
            return False
    return True


def _log_gate_block(
    verdict: ConvergenceVerdict, latest_gates: dict[str, GateVerdict], current_stage: str
) -> None:
    """记录 gate fail 拦住 stop 的诊断日志 (Bug 3 方案 C)."""
    failed = [
        name
        for name, v in latest_gates.items()
        if not v.passed
    ]
    _logger.info(
        "Bug 3 方案 C: judge QUALITY_PASS 但 gate fail, 不停止 → continue. "
        "verdict_level=%d, current_stage=%s, failed_gates=%s",
        getattr(verdict, "level", -1),
        current_stage,
        failed,
    )
