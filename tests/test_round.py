"""Tests for _topological_levels (Kahn BFS 分层) — v5.0 §B2.12b.

Test symbols that were deleted from loop/round.py in P0-1 audit (run_round,
_build_per_task_ctx, _parse_git_numstat) have been removed.

Design: v5.0 §B2.12b _topological_levels (Kahn BFS 分层).
Imported via engine/models.py → loop/plan.py re-export.
"""

from __future__ import annotations

import pytest

from auto_engineering.loop.plan import ConflictError, Task, _topological_levels


def make_task(tid: str, depends_on: list[str] | None = None) -> Task:
    """构造测试用 Task (role=developer 默认)."""
    return Task(id=tid, depends_on=list(depends_on or []), role="developer")


# ============================================================
# _topological_levels (Kahn BFS 分层)
# ============================================================


class TestTopologicalLayers:
    """v5.0 §B2.12b — _topological_levels 分层 (engine/models.py, re-exported via plan.py)."""

    def test_topological_levels_single_task(self):
        """单个无依赖 task → [[t1]]."""
        layers = _topological_levels([make_task("t1")])
        assert layers == [[make_task("t1")]]

    def test_topological_levels_parallel(self):
        """多个无依赖 task → [[t1, t2, t3]] (同层并行)."""
        tasks = [make_task("t1"), make_task("t2"), make_task("t3")]
        layers = _topological_levels(tasks)
        assert len(layers) == 1
        assert len(layers[0]) == 3
        layer_ids = {t.id for t in layers[0]}
        assert layer_ids == {"t1", "t2", "t3"}

    def test_topological_levels_chain(self):
        """依赖链 t1 → t2 → t3 → 3 层, 每层 1 个."""
        tasks = [
            make_task("t1"),
            make_task("t2", depends_on=["t1"]),
            make_task("t3", depends_on=["t2"]),
        ]
        layers = _topological_levels(tasks)
        assert len(layers) == 3
        assert layers[0][0].id == "t1"
        assert layers[1][0].id == "t2"
        assert layers[2][0].id == "t3"

    def test_topological_levels_diamond(self):
        """菱形依赖: t1 → t2, t1 → t3, t2 → t4, t3 → t4 → 3 层."""
        tasks = [
            make_task("t1"),
            make_task("t2", depends_on=["t1"]),
            make_task("t3", depends_on=["t1"]),
            make_task("t4", depends_on=["t2", "t3"]),
        ]
        layers = _topological_levels(tasks)
        assert len(layers) == 3
        assert layers[0][0].id == "t1"
        assert {t.id for t in layers[1]} == {"t2", "t3"}
        assert layers[2][0].id == "t4"

    def test_topological_levels_cycle_raises(self):
        """环检测: t1 → t2 → t1 → ConflictError."""
        tasks = [
            make_task("t1", depends_on=["t2"]),
            make_task("t2", depends_on=["t1"]),
        ]
        with pytest.raises(ConflictError):
            _topological_levels(tasks)

    def test_topological_levels_empty(self):
        """空列表 → []."""
        assert _topological_levels([]) == []

    def test_self_loop_raises_conflict(self):
        """自环: t1.depends_on=[t1] → ConflictError."""
        tasks = [make_task("t1", depends_on=["t1"])]
        with pytest.raises(ConflictError) as exc_info:
            _topological_levels(tasks)
        assert any("cycle" in c for c in exc_info.value.conflicts)

    def test_external_dep_not_counted(self):
        """deps 引用 batch 外的 task → 不计入入度, 视为已满足."""
        tasks = [
            make_task("t1"),
            make_task("t2", depends_on=["external"]),
            make_task("t3", depends_on=["t1"]),
        ]
        layers = _topological_levels(tasks)
        assert len(layers) == 2
        assert {t.id for t in layers[0]} == {"t1", "t2"}
        assert layers[1][0].id == "t3"

    def test_layer_ordering_is_deterministic_sorted(self):
        """同层 task 按 id 排序 (确定性输出)."""
        tasks = [make_task("z"), make_task("a"), make_task("m")]
        layers = _topological_levels(tasks)
        assert len(layers) == 1
        assert [t.id for t in layers[0]] == ["a", "m", "z"]
