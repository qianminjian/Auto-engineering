"""Tests for RoundResult properties and _topological_levels extended coverage.

RoundResult dataclass moved into this test file (V1 ghost code cleanup, 2026-07-25)
— it had zero non-test consumers in production.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from auto_engineering.engine.models import _topological_levels
from auto_engineering.gates.base import GateVerdict
from auto_engineering.loop.plan import ConflictError, Task, TaskOutcome


@dataclass
class RoundResult:
    """一輪的匯總結果 (V1 ghost cleanup: moved from production to test file).

    Attributes:
        round_id: 輪次 ID
        outcomes: 每個 task 的執行結果
        gate_results: 本輪運行的 Gate 結果 dict[gate_name, GateVerdict]
        started_at: 啟動時間戳
        finished_at: 完成時間戳
    """

    round_id: int
    stage: str = ""
    outcomes: list[TaskOutcome] = field(default_factory=list)
    gate_results: dict[str, GateVerdict] = field(default_factory=dict)
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
        """所有 Gate 都通過. 規則:
        - gate_results 為空 → True (無 Gate 跑, 不算失敗)
        - 存在任一 verdict.passed=False → False
        - 否則 True
        """
        if not self.gate_results:
            return True
        return all(v.passed for v in self.gate_results.values())

    def files_changed(self) -> int:
        """估算本輪修改文件數 (基於成功 task 數量)."""
        return self.completed_count


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
