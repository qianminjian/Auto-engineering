"""Tests for RoundResult properties (loop/round.py).

P0-1 audit deleted run_round / _build_per_task_ctx / _parse_git_numstat from
loop/round.py. Tests for deleted symbols removed. RoundResult dataclass remains
with zero non-test consumers — test coverage retained for RoundResult properties.

Also includes _topological_levels extended coverage (self-loop, external dep).
"""

from __future__ import annotations

import pytest

from auto_engineering.gates.base import GateVerdict
from auto_engineering.loop.plan import ConflictError, Task, _topological_levels
from auto_engineering.loop.round import RoundResult, TaskOutcome


def make_task(tid: str, depends_on: list[str] | None = None, role: str = "developer") -> Task:
    return Task(id=tid, depends_on=list(depends_on or []), role=role)


# ============================================================
# Group 1: RoundResult properties
# ============================================================


class TestRoundResultProperties:
    """覆盖 RoundResult.duration / failed_count / all_gates_passed / files_changed."""

    def test_duration_subtracts_timestamps(self):
        r = RoundResult(round_id=1)
        r.started_at = 10.0
        r.finished_at = 13.5
        assert r.duration == pytest.approx(3.5)

    def test_duration_zero_when_not_started(self):
        r = RoundResult(round_id=1)
        assert r.duration == 0.0

    def test_failed_count_counts_failed_only(self):
        r = RoundResult(
            round_id=1,
            outcomes=[
                TaskOutcome(task_id="a", status="completed"),
                TaskOutcome(task_id="b", status="failed"),
                TaskOutcome(task_id="c", status="cancelled"),
                TaskOutcome(task_id="d", status="failed"),
            ],
        )
        assert r.failed_count == 2
        assert r.completed_count == 1
        assert r.all_succeeded is False

    def test_all_succeeded_true_when_all_completed(self):
        r = RoundResult(
            round_id=1,
            outcomes=[
                TaskOutcome(task_id="a", status="completed"),
                TaskOutcome(task_id="b", status="completed"),
            ],
        )
        assert r.all_succeeded is True

    def test_all_succeeded_true_when_empty_outcomes(self):
        r = RoundResult(round_id=1)
        assert r.all_succeeded is True

    def test_all_gates_passed_true_when_empty(self):
        """gate_results 为空 → True (无 Gate 跑, 不算失败)."""
        r = RoundResult(round_id=1)
        assert r.all_gates_passed is True

    def test_all_gates_passed_false_when_any_failed(self):
        r = RoundResult(
            round_id=1,
            gate_results={
                "lint": GateVerdict.ok("ok", gate_name="lint"),
                "type": GateVerdict.failed("bad", gate_name="type"),
            },
        )
        assert r.all_gates_passed is False

    def test_all_gates_passed_true_when_all_passed(self):
        r = RoundResult(
            round_id=1,
            gate_results={
                "lint": GateVerdict.ok("ok", gate_name="lint"),
                "type": GateVerdict.ok("ok", gate_name="type"),
            },
        )
        assert r.all_gates_passed is True

    def test_files_changed_equals_completed_count(self):
        r = RoundResult(
            round_id=1,
            outcomes=[
                TaskOutcome(task_id="a", status="completed"),
                TaskOutcome(task_id="b", status="failed"),
                TaskOutcome(task_id="c", status="completed"),
            ],
        )
        assert r.files_changed() == 2


# ============================================================
# Group 2: _topological_levels 扩展 (自环 + 外部 dep)
# ============================================================


class TestTopologicalLayersExtended:
    """额外覆盖: 自环 (a→a) / 外部 dep 不计入入度 / 多环混合."""

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
