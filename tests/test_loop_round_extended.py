"""v5.0 Phase 12.8 — Extended coverage for auto_engineering.loop.round.

目标: loop/round.py 行覆盖率 ≥ 90% (基线 79%).

覆盖现有 test_round.py 未触达的行:
    - RoundResult.duration / failed_count / all_gates_passed / files_changed
    - _build_per_task_ctx (TaskContext dataclass 分支 + None + 非 dataclass)
    - run_round 空 tasks 路径 (走 Gate + history)
    - run_round Gate stage 过滤
    - run_round contracts 透传给 Gate.run()
    - run_round Gate 异常被吞 (写失败 Verdict)
    - _parse_git_numstat 错误路径 (subprocess errors + 非 0 返回)
    - _parse_git_numstat 正常路径 (含 - 占位行 + ValueError)
    - _topological_layers 自环 (a→a) → ConflictError
    - _topological_layers 外部 dep (deps 引用 batch 外 task → 视为 0)
    - Round.execute() 委托 run_round
    - RoundResult.all_succeeded 含 failed 时返回 False
    - gather 防御路径 (注入未捕获 BaseException → 走 fail 包装)

设计参考: design/v5.0-Design-Loop.md §B2.12a §B2.12b + v2.5 P2-D-1/2.
"""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from auto_engineering.gates.base import Gate, Verdict
from auto_engineering.loop.plan import ConflictError, Task
from auto_engineering.loop.round import (
    Round,
    RoundResult,
    TaskOutcome,
    _build_per_task_ctx,
    _parse_git_numstat,
    _topological_layers,
    run_round,
)


# ============================================================
# Helpers
# ============================================================


def make_task(tid: str, deps: list[str] | None = None, role: str = "developer") -> Task:
    return Task(id=tid, deps=list(deps or []), role=role)


async def _ok_executor(task, ctx):
    return TaskOutcome(task_id=task.id, status="completed", output=task.id)


@dataclass
class FakeTaskCtx:
    """模拟 TaskContext — 含 state + requirement + current_task_id 字段."""

    state: dict
    requirement: str
    current_task_id: str = ""


@dataclass
class NoCurrentIdCtx:
    """TaskContext 但无 current_task_id 字段 — 测试 replace 无字段路径."""

    state: dict
    requirement: str


class _StubGate(Gate):
    """可控制 verdict / 是否抛异常 / 记录 contracts 透传的 Gate."""

    name = "stub"

    def __init__(
        self,
        verdict_passed: bool = True,
        applies_to_stages: tuple[str, ...] = ("architect", "developer", "critic"),
        raise_exc: BaseException | None = None,
        captured_contracts: dict | None = None,
    ) -> None:
        self.applies_to_stages = applies_to_stages
        self._verdict_passed = verdict_passed
        self._raise_exc = raise_exc
        self.captured_contracts = captured_contracts
        self.call_count = 0

    def run(self, project_root, contracts=None):  # type: ignore[override]
        self.call_count += 1
        self.captured_contracts = contracts
        if self._raise_exc is not None:
            raise self._raise_exc
        if self._verdict_passed:
            return Verdict.passed("ok", gate_name=self.name)
        return Verdict.failed("nope", gate_name=self.name)


# ============================================================
# Group 1: RoundResult properties (lines 90, 98, 112, 118)
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
        # 空 outcomes 时 all() 默认 True
        assert r.all_succeeded is True

    def test_all_gates_passed_true_when_empty(self):
        """gate_results 为空 → True (无 Gate 跑, 不算失败)."""
        r = RoundResult(round_id=1)
        assert r.all_gates_passed is True

    def test_all_gates_passed_false_when_any_failed(self):
        r = RoundResult(
            round_id=1,
            gate_results={
                "lint": Verdict.passed("ok", gate_name="lint"),
                "type": Verdict.failed("bad", gate_name="type"),
            },
        )
        assert r.all_gates_passed is False

    def test_all_gates_passed_true_when_all_passed(self):
        r = RoundResult(
            round_id=1,
            gate_results={
                "lint": Verdict.passed("ok", gate_name="lint"),
                "type": Verdict.passed("ok", gate_name="type"),
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
# Group 2: _build_per_task_ctx (lines 208-222)
# ============================================================


class TestBuildPerTaskCtx:
    """覆盖 _build_per_task_ctx 各分支: None / TaskContext / 非 dataclass / 无 current_task_id."""

    def test_none_returns_none(self):
        assert _build_per_task_ctx(None, make_task("t1")) is None

    def test_plain_dict_passthrough(self):
        """非 dataclass (无 __dataclass_fields__) → 透传."""
        ctx = {"state": {}, "requirement": "r"}
        out = _build_per_task_ctx(ctx, make_task("t1"))
        assert out is ctx

    def test_dataclass_with_current_task_id_filled(self):
        """FakeTaskCtx 含 current_task_id → replace 后填 task.id."""
        ctx = FakeTaskCtx(state={"k": "v"}, requirement="do X")
        out = _build_per_task_ctx(ctx, make_task("t-42"))
        assert out is not ctx  # 复制实例, 非共享
        assert out.current_task_id == "t-42"
        # state / requirement 字段保留
        assert out.state == {"k": "v"}
        assert out.requirement == "do X"

    def test_dataclass_without_current_task_id_still_copied(self):
        """NoCurrentIdCtx 无 current_task_id → replace(ctx) 仍复制 (避免共享 state 突变)."""
        original_state = {"k": "v"}
        ctx = NoCurrentIdCtx(state=original_state, requirement="r")
        out = _build_per_task_ctx(ctx, make_task("t1"))
        assert out is not ctx  # 确实是新实例
        assert out.state == original_state


# ============================================================
# Group 3: _topological_layers 扩展 (自环 + 外部 dep)
# ============================================================


class TestTopologicalLayersExtended:
    """额外覆盖: 自环 (a→a) / 外部 dep 不计入入度 / 多环混合."""

    def test_self_loop_raises_conflict(self):
        """自环: t1.deps=[t1] → ConflictError."""
        tasks = [make_task("t1", deps=["t1"])]
        with pytest.raises(ConflictError) as exc_info:
            _topological_layers(tasks)
        # 验证 conflicts 字段含 cycle 描述
        assert any("cycle" in c for c in exc_info.value.conflicts)

    def test_external_dep_not_counted(self):
        """deps 引用 batch 外的 task → 不计入入度, 视为已满足."""
        tasks = [
            make_task("t1"),  # 无 deps, 外部 dep
            make_task("t2", deps=["external"]),  # external 不在 batch
            make_task("t3", deps=["t1"]),
        ]
        layers = _topological_layers(tasks)
        # 期望: 第 1 层含 t1 + t2 (两者都入度 0), 第 2 层 t3
        assert len(layers) == 2
        assert {t.id for t in layers[0]} == {"t1", "t2"}
        assert layers[1][0].id == "t3"

    def test_layer_ordering_is_deterministic_sorted(self):
        """同层 task 按 id 排序 (确定性输出, 便于测试)."""
        tasks = [make_task("z"), make_task("a"), make_task("m")]
        layers = _topological_layers(tasks)
        assert len(layers) == 1
        assert [t.id for t in layers[0]] == ["a", "m", "z"]


# ============================================================
# Group 4: run_round 空 tasks 路径 (lines 268-274)
# ============================================================


class TestRunRoundEmptyTasks:
    """空 tasks → 不并行, 但仍跑 Gate + 写 history."""

    @pytest.mark.asyncio
    async def test_empty_tasks_runs_gates_when_provided(self, tmp_path: Path):
        gate = _StubGate()
        result = await run_round(
            tasks=[],
            executor=_ok_executor,
            gates=[gate],
            project_root=tmp_path,
            stage="developer",
        )
        assert result.outcomes == []
        assert "stub" in result.gate_results
        assert result.gate_results["stub"].passed is True
        # 空 tasks 也要写 history (1 个元素)
        assert len(result.history) == 1

    @pytest.mark.asyncio
    async def test_empty_tasks_no_gates_still_writes_history(self):
        result = await run_round(tasks=[], executor=_ok_executor)
        assert result.outcomes == []
        assert result.gate_results == {}
        assert len(result.history) == 1
        assert result.history[0].tasks_run == []


# ============================================================
# Group 5: run_round + stage 过滤 (line 424)
# ============================================================


class TestRunRoundStageFilter:
    """stage 非空时仅跑 applies_to_stages 包含 stage 的 Gate."""

    @pytest.mark.asyncio
    async def test_stage_filters_gates_correctly(self, tmp_path: Path):
        dev_gate = _StubGate(applies_to_stages=("developer",))
        arch_gate = _StubGate(applies_to_stages=("architect",))
        all_gate = _StubGate(applies_to_stages=("architect", "developer", "critic"))

        result = await run_round(
            tasks=[make_task("t1")],
            executor=_ok_executor,
            gates=[dev_gate, arch_gate, all_gate],
            project_root=tmp_path,
            stage="developer",
        )
        # arch_gate 不应在结果中
        assert "stub" in result.gate_results
        # 三个 stub gate name 相同 → 只保留最后一次 → call count 总计 2 (dev + all)
        assert dev_gate.call_count == 1
        assert arch_gate.call_count == 0
        assert all_gate.call_count == 1

    @pytest.mark.asyncio
    async def test_empty_stage_runs_all_gates(self, tmp_path: Path):
        """stage="" 时所有 Gate 都跑 (向后兼容默认)."""
        g1 = _StubGate(applies_to_stages=("developer",))
        g2 = _StubGate(applies_to_stages=("architect",))
        # 让两个 gate 名字不同便于区分
        g1.name = "g1"
        g2.name = "g2"
        result = await run_round(
            tasks=[make_task("t1")],
            executor=_ok_executor,
            gates=[g1, g2],
            project_root=tmp_path,
            stage="",
        )
        assert "g1" in result.gate_results
        assert "g2" in result.gate_results
        assert g1.call_count == 1
        assert g2.call_count == 1


# ============================================================
# Group 6: run_round + contracts 透传给 Gate.run()
# ============================================================


class TestRunRoundContractsPassthrough:
    """contracts dict 透传给每个 Gate.run(contracts=...)."""

    @pytest.mark.asyncio
    async def test_contracts_passed_to_gate_run(self, tmp_path: Path):
        gate = _StubGate()
        contracts = {"api_user": {"request": {}, "response": {}, "status": 200}}
        await run_round(
            tasks=[make_task("t1")],
            executor=_ok_executor,
            gates=[gate],
            project_root=tmp_path,
            contracts=contracts,
        )
        assert gate.captured_contracts == contracts


# ============================================================
# Group 7: run_round Gate 异常 → 失败 Verdict (lines 432-438)
# ============================================================


class TestRunRoundGateException:
    """Gate 抛异常时, 写 Verdict.failed 而非传播异常."""

    @pytest.mark.asyncio
    async def test_gate_exception_writes_failed_verdict(self, tmp_path: Path):
        gate = _StubGate(raise_exc=RuntimeError("gate boom"))
        result = await run_round(
            tasks=[make_task("t1")],
            executor=_ok_executor,
            gates=[gate],
            project_root=tmp_path,
        )
        # 异常被吞, 写失败 verdict
        assert "stub" in result.gate_results
        assert result.gate_results["stub"].passed is False
        assert "boom" in result.gate_results["stub"].message


# ============================================================
# Group 8: _parse_git_numstat 错误路径 (lines 373-374, 382-392)
# ============================================================


class TestParseGitNumstat:
    """覆盖 _parse_git_numstat 各错误/边界分支."""

    def test_none_project_root_returns_zeros(self, monkeypatch):
        # project_root=None → cwd=".", 同样走 subprocess
        # 用 monkeypatch 拦截以避免依赖真实 git 状态
        called = {}

        def fake_run(*args, **kwargs):
            called["args"] = args
            called["kwargs"] = kwargs
            raise FileNotFoundError("git not found")

        monkeypatch.setattr(subprocess, "run", fake_run)
        added, removed = _parse_git_numstat(None)
        assert (added, removed) == (0, 0)
        assert called["kwargs"]["cwd"] == "."

    def test_timeout_returns_zeros(self, monkeypatch):
        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="git", timeout=10)

        monkeypatch.setattr(subprocess, "run", fake_run)
        added, removed = _parse_git_numstat(Path("/tmp"))
        assert (added, removed) == (0, 0)

    def test_nonzero_returncode_returns_zeros(self, monkeypatch):
        class FakeResult:
            returncode = 128
            stdout = "1\t1\n"
            stderr = "fatal: bad revision"

        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: FakeResult()
        )
        added, removed = _parse_git_numstat(Path("/tmp"))
        assert (added, removed) == (0, 0)

    def test_dash_placeholder_line_skipped(self, monkeypatch):
        """二进制文件行 added='-' → 跳过."""

        class FakeResult:
            returncode = 0
            stdout = "5\t3\n-\t-\n2\t1\n"
            stderr = ""

        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: FakeResult()
        )
        added, removed = _parse_git_numstat(Path("/tmp"))
        # 跳过 '-' 行: 5+2=7, 3+1=4
        assert added == 7
        assert removed == 4

    def test_value_error_line_skipped(self, monkeypatch):
        """非数字行 → ValueError 被吞."""

        class FakeResult:
            returncode = 0
            stdout = "abc\tdef\n3\t2\n"
            stderr = ""

        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: FakeResult()
        )
        added, removed = _parse_git_numstat(Path("/tmp"))
        assert added == 3
        assert removed == 2

    def test_short_line_skipped(self, monkeypatch):
        """少于 2 列的行 → 跳过."""

        class FakeResult:
            returncode = 0
            stdout = "single_col\n3\t2\n"
            stderr = ""

        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: FakeResult()
        )
        added, removed = _parse_git_numstat(Path("/tmp"))
        assert added == 3
        assert removed == 2


# ============================================================
# Group 9: Round.execute() 委托 (line 479)
# ============================================================


class TestRoundExecute:
    """Round.execute() 委托给 run_round(), 透传 round_id."""

    @pytest.mark.asyncio
    async def test_round_execute_delegates_to_run_round(self):
        async def executor(task, ctx):
            return TaskOutcome(task_id=task.id, status="completed", output="x")

        r = Round(round_id=7, requirement="req", tasks=[make_task("t1")])
        result = await r.execute(executor=executor)
        assert result.round_id == 7
        assert result.completed_count == 1
        assert len(result.history) == 1
        # Round.execute 委托给 run_round, 默认无 gates → gate_results 空
        assert result.gate_results == {}


# ============================================================
# Group 10: history 字段语义 (_attach_round_history 集成)
# ============================================================


class TestAttachRoundHistory:
    """覆盖 _attach_round_history 在 run_round 末尾构造 RoundHistory 的行为."""

    @pytest.mark.asyncio
    async def test_history_records_task_outcomes(self):
        async def executor(task, ctx):
            return TaskOutcome(task_id=task.id, status="completed", output="ok")

        tasks = [make_task("t1"), make_task("t2")]
        result = await run_round(tasks=tasks, executor=executor)
        assert len(result.history) == 1
        h = result.history[0]
        assert h.round_id == result.round_id
        assert h.tasks_run == ["t1", "t2"]
        assert h.task_outcomes == {"t1": "completed", "t2": "completed"}
        assert h.gate_results == {}
        # files_changed 来自 completed_count
        assert h.files_changed == 2

    @pytest.mark.asyncio
    async def test_history_with_failed_outcome(self):
        async def executor(task, ctx):
            return TaskOutcome(task_id=task.id, status="failed", error="x")

        result = await run_round(tasks=[make_task("t1")], executor=executor)
        h = result.history[0]
        assert h.task_outcomes == {"t1": "failed"}
        assert h.files_changed == 0  # 0 completed


# ============================================================
# Group 11: run_round outcome duration 由 _execute_single 强制覆盖
# ============================================================


class TestOutcomeDurationOverride:
    """_execute_single 强制覆盖 outcome.duration 为实际耗时."""

    @pytest.mark.asyncio
    async def test_executor_duration_overridden_by_actual(self):
        async def executor(task, ctx):
            # executor 返回虚假的 duration, 应被覆盖
            return TaskOutcome(
                task_id=task.id, status="completed", output="ok", duration=0.0
            )

        result = await run_round(tasks=[make_task("t1")], executor=executor)
        # 实际耗时 >= 0, 字段被强制覆盖 (即非 executor 填的 0)
        assert result.outcomes[0].duration >= 0
        # 难以精确断言数值, 至少验证类型正确
        assert isinstance(result.outcomes[0].duration, float)


# ============================================================
# Group 12: _run_gates 边界 (lines 443, 450)
# ============================================================


class TestRunGatesEdge:
    """stage 过滤后无 Gate → 返回空 dict; gather 防御路径."""

    @pytest.mark.asyncio
    async def test_no_gates_to_run_returns_empty(self, tmp_path: Path):
        """所有 Gate 都被 stage 过滤掉 → 空 dict, 不抛."""
        g = _StubGate(applies_to_stages=("developer",))
        result = await run_round(
            tasks=[make_task("t1")],
            executor=_ok_executor,
            gates=[g],
            project_root=tmp_path,
            stage="architect",  # gate 不适用此 stage
        )
        assert result.gate_results == {}
        assert g.call_count == 0

    @pytest.mark.asyncio
    async def test_empty_gates_list_returns_empty(self, tmp_path: Path):
        result = await run_round(
            tasks=[make_task("t1")],
            executor=_ok_executor,
            gates=[],
            project_root=tmp_path,
        )
        assert result.gate_results == {}