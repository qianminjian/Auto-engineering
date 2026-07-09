"""T8 — ConvergenceJudge.evaluate() 扩展: design_coverage_ok + system_deep_audit_ok.

设计参考: v5.6-Design-Loop.md §B4 (line 751-757) + §C.5.5 (_convergence_check).

v5.6 终态成功判定 (GOAL_ACHIEVED, level=1=LEVEL_SEMANTIC):
  system_deep_audit 全部通过 + design_coverage_ok → stop(1, GOAL_ACHIEVED).

正交性 (DS-8): Judge 只管收敛质量 + max_iterations 硬上限; plan_refine 环路耗尽
由 StageRouter 产出 (REFINE_LIMIT), 不经 Judge.

两个新 kwarg 默认 False → 保留 Orchestrator (v5.5 debug 路径) evaluate(history)
调用行为完全不变 (向后兼容).
"""

from __future__ import annotations

from auto_engineering.loop.convergence import (
    LEVEL_SEMANTIC,
    ConvergenceConfig,
    ConvergenceJudge,
    RoundHistory,
)


def _judge(max_iter: int = 10) -> ConvergenceJudge:
    return ConvergenceJudge(ConvergenceConfig(max_iterations=max_iter))


def _hist(round_id: int) -> list[RoundHistory]:
    return [RoundHistory(round_id=round_id, stage="system_deep_audit")]


class TestGoalAchieved:
    def test_both_ok_returns_goal_achieved(self) -> None:
        v = _judge().evaluate(_hist(2), design_coverage_ok=True, system_deep_audit_ok=True)
        assert v.should_stop is True
        assert v.level == LEVEL_SEMANTIC
        assert v.level_name == "GOAL_ACHIEVED"

    def test_goal_achieved_wins_over_hard_limit(self) -> None:
        """终态成功优先于硬上限: 恰在 max_iterations 达成成功 → GOAL_ACHIEVED, 非 HARD_LIMIT."""
        v = _judge(max_iter=3).evaluate(
            _hist(3), design_coverage_ok=True, system_deep_audit_ok=True)
        assert v.level == LEVEL_SEMANTIC
        assert v.level_name == "GOAL_ACHIEVED"

    def test_audit_ok_but_coverage_gap_not_goal_achieved(self) -> None:
        v = _judge().evaluate(_hist(1), design_coverage_ok=False, system_deep_audit_ok=True)
        assert not (v.should_stop and v.level == LEVEL_SEMANTIC)

    def test_coverage_ok_but_audit_not_ok_not_goal_achieved(self) -> None:
        v = _judge().evaluate(_hist(1), design_coverage_ok=True, system_deep_audit_ok=False)
        assert not (v.should_stop and v.level == LEVEL_SEMANTIC)


class TestBackwardCompatible:
    def test_defaults_unchanged_empty_history_continues(self) -> None:
        """无 kwarg (retained 路径): 空 history → CONTINUE (行为不变)."""
        v = _judge().evaluate([])
        assert v.should_stop is False

    def test_defaults_hard_limit_still_fires(self) -> None:
        """无 kwarg: 达 max_iterations → 仍触发硬上限停止."""
        v = _judge(max_iter=2).evaluate(_hist(2))
        assert v.should_stop is True
