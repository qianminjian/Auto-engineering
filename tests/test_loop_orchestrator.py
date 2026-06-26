"""v2.0 Phase 03 测试 — Orchestrator + Round + 多 Agent 并发.

设计来源:
    - design/v2.0-Analysis-Loop.md §4.2 两层 Loop + §4.3 文件隔离 + §4.5 多 Agent 并发
    - design/v2.0-Analysis-Loop.md §五 Phase 3

测试覆盖:
    A. Task DAG 拓扑排序 (≥2 用例)
    B. check_file_isolation 文件冲突检测 (≥2 用例)
    C. Plan parallelism_groups 分组 (≥1 用例)
    D. Round asyncio.gather 单 Agent + 多 Agent 并发 (≥2 用例)
    E. Orchestrator 单/多 Agent 完整流程 (≥3 用例)
    F. CancellationToken 整合 (≥1 用例)
    合计: ≥10 用例

测试约束 (遵循 pytest-memory-management.md):
    - 单文件 pytest --no-cov --timeout=60
    - 用 mock runtime 避免真实 LLM 调用
    - 跑完清理 .pytest_cache
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest

from auto_engineering.loop.orchestrator import (
    Orchestrator,
    OrchestratorConfig,
)
from auto_engineering.loop.plan import (
    ConflictError,
    Plan,
    Task,
    check_file_isolation,
    topological_sort,
)
from auto_engineering.loop.round import TaskOutcome, run_round

if TYPE_CHECKING:
    from auto_engineering.loop.convergence import RoundHistory

# ============================================================
# Fixtures + helpers
# ============================================================


def make_task(
    task_id: str,
    target_files: list[str] | None = None,
    deps: list[str] | None = None,
    agent_type: str = "developer",
) -> Task:
    """构造测试 Task (target_files 用字符串列表, 内部转 frozenset).

    Phase 2.1-D: 补 title/expected_output 字段满足 Plan.validate contract.
    """
    return Task(
        id=task_id,
        title=f"Task {task_id}",
        description=f"task {task_id}",
        expected_output=f"output for {task_id}",
        role=agent_type,
        target_files=frozenset(target_files or []),
        depends_on=list(deps or []),
        agent_type=agent_type,
    )


@pytest.fixture
def three_independent_tasks() -> list[Task]:
    """三个文件集互不重叠的 task."""
    return [
        make_task("t1", ["src/auth.py"]),
        make_task("t2", ["src/user.py"]),
        make_task("t3", ["src/product.py"]),
    ]


@pytest.fixture
def conflicting_tasks() -> list[Task]:
    """两个 task 共享同一文件 (冲突)."""
    return [
        make_task("t1", ["src/shared.py"]),
        make_task("t2", ["src/shared.py"]),
    ]


# ============================================================
# A. TaskDAG 拓扑排序
# ============================================================


def test_topological_sort_linear_chain():
    """线性依赖链: t1 → t2 → t3."""
    tasks = [
        make_task("t3", deps=["t2"]),
        make_task("t2", deps=["t1"]),
        make_task("t1"),
    ]
    order = topological_sort(tasks)
    assert order == ["t1", "t2", "t3"]


def test_topological_sort_diamond_dependency():
    """菱形依赖: t1 → t2, t1 → t3, t2 → t4, t3 → t4."""
    tasks = [
        make_task("t1"),
        make_task("t2", deps=["t1"]),
        make_task("t3", deps=["t1"]),
        make_task("t4", deps=["t2", "t3"]),
    ]
    order = topological_sort(tasks)
    # t1 必须先, t4 必须最后
    assert order[0] == "t1"
    assert order[-1] == "t4"
    # t2, t3 在中间(顺序不限)
    assert set(order[1:3]) == {"t2", "t3"}


def test_topological_sort_detects_cycle():
    """循环依赖 → ValueError."""
    tasks = [
        make_task("t1", deps=["t2"]),
        make_task("t2", deps=["t1"]),
    ]
    with pytest.raises(ValueError, match=r"[Cc]ycle|[Cc]ircular"):
        topological_sort(tasks)


# ============================================================
# B. check_file_isolation 文件冲突检测
# ============================================================


def test_check_file_isolation_no_conflict(three_independent_tasks):
    """三个独立 task (文件不重叠) → 无冲突."""
    conflicts = check_file_isolation(three_independent_tasks)
    assert conflicts == []


def test_check_file_isolation_detects_conflict(conflicting_tasks):
    """两个 task 共享文件 → 冲突列表非空."""
    conflicts = check_file_isolation(conflicting_tasks)
    assert len(conflicts) > 0
    assert any("shared.py" in c for c in conflicts)


def test_check_file_isolation_only_parallel_groups():
    """串行的两个 task 共享文件 → 不算冲突(因为不会并行)."""
    # t1 先做, t2 依赖 t1 (串行, 不并行)
    tasks = [
        make_task("t1", ["src/shared.py"]),
        make_task("t2", ["src/shared.py"], deps=["t1"]),
    ]
    conflicts = check_file_isolation(tasks)
    assert conflicts == []


def test_check_file_isolation_throws_conflict_error_on_violation():
    """ConflictError 暴露给 Orchestrator 用."""
    tasks = [
        make_task("t1", ["src/x.py"]),
        make_task("t2", ["src/x.py"]),  # 并行 + 共享文件
    ]
    with pytest.raises(ConflictError):
        check_file_isolation(tasks, raise_on_conflict=True)


# ============================================================
# C. Plan parallelism_groups
# ============================================================


def test_plan_parallelism_groups_three_independent(three_independent_tasks):
    """三个独立 task → 一个并行组."""
    plan = Plan(tasks=three_independent_tasks)
    groups = plan.parallelism_groups()
    assert len(groups) == 1
    assert set(groups[0]) == {"t1", "t2", "t3"}


def test_plan_parallelism_groups_diamond():
    """菱形依赖 → 两个并行组: [t1] → [t2,t3] → [t4]."""
    tasks = [
        make_task("t1"),
        make_task("t2", deps=["t1"]),
        make_task("t3", deps=["t1"]),
        make_task("t4", deps=["t2", "t3"]),
    ]
    plan = Plan(tasks=tasks)
    groups = plan.parallelism_groups()
    assert len(groups) == 3
    assert groups[0] == ["t1"]
    assert set(groups[1]) == {"t2", "t3"}
    assert groups[2] == ["t4"]


def test_plan_validate_runs_file_isolation(three_independent_tasks):
    """Plan.validate() 调用 check_file_isolation."""
    plan = Plan(tasks=three_independent_tasks)
    plan.validate()  # 无冲突 → 不抛


def test_plan_validate_raises_on_conflict(conflicting_tasks):
    """Plan.validate() 检测到冲突 → 抛 ConflictError."""
    plan = Plan(tasks=conflicting_tasks)
    with pytest.raises(ConflictError):
        plan.validate()


# ============================================================
# D. Round asyncio.gather 并发
# ============================================================


@pytest.mark.asyncio
async def test_run_round_single_task_executes():
    """单 task Round: 执行一次 executor."""
    called = []

    async def executor(task, ctx):
        called.append(task.id)
        return TaskOutcome(task_id=task.id, status="completed", output="ok")

    task = make_task("only_one")
    result = await run_round(
        tasks=[task],
        executor=executor,
    )
    assert called == ["only_one"]
    assert result.completed_count == 1
    assert result.all_succeeded


@pytest.mark.asyncio
async def test_run_round_multiple_tasks_run_concurrently():
    """多 task Round: asyncio.gather 真并行 (总耗时 < 串行)."""

    async def slow_executor(task, ctx):
        await asyncio.sleep(0.1)  # 模拟 LLM 调用
        return TaskOutcome(task_id=task.id, status="completed", output=task.id)

    tasks = [make_task(f"t{i}") for i in range(3)]
    start = time.monotonic()
    result = await run_round(tasks=tasks, executor=slow_executor)
    elapsed = time.monotonic() - start

    # 串行需要 3 * 0.1 = 0.3s, 并行应该 ~0.1s
    assert elapsed < 0.25, f"应该真并行, 但耗时 {elapsed:.3f}s"
    assert result.completed_count == 3
    assert result.all_succeeded


@pytest.mark.asyncio
async def test_run_round_collects_failures():
    """某个 task 失败 → Round 标记 failed."""
    async def executor(task, ctx):
        if task.id == "bad":
            return TaskOutcome(task_id=task.id, status="failed", error="boom")
        return TaskOutcome(task_id=task.id, status="completed", output="ok")

    tasks = [make_task("good"), make_task("bad"), make_task("good2")]
    result = await run_round(tasks=tasks, executor=executor)
    assert result.completed_count == 2
    assert not result.all_succeeded
    assert any(o.task_id == "bad" and o.status == "failed" for o in result.outcomes)


# ============================================================
# E. Orchestrator 完整流程
# ============================================================


@pytest.mark.asyncio
async def test_orchestrator_single_agent_one_round():
    """单 Agent (1 task / round) 流程: 跑一轮 → 触发硬上限."""
    from auto_engineering.loop.convergence import ConvergenceConfig

    task = make_task("only_task", ["src/x.py"])

    async def executor(t, ctx):
        return TaskOutcome(task_id=t.id, status="completed", output="done")

    # max_rounds=1 + 高 stagnation_threshold → 第 1 轮跑完触发硬上限
    config = OrchestratorConfig(
        max_rounds=1,
        convergence_config=ConvergenceConfig(stagnation_threshold=10),
    )
    orch = Orchestrator(
        requirement="实现 X",
        tasks=[task],
        executor=executor,
        config=config,
    )

    history = await orch.run()
    assert len(history) == 1
    assert history[0].round_id == 1
    assert orch.verdict is not None
    assert orch.verdict.should_stop


@pytest.mark.asyncio
async def test_orchestrator_multi_agent_three_round():
    """多 Agent (3 tasks / round) 第一轮全完成 → max_rounds 触发."""
    from auto_engineering.loop.convergence import ConvergenceConfig

    tasks = [
        make_task("auth", ["src/auth.py"]),
        make_task("user", ["src/user.py"]),
        make_task("product", ["src/product.py"]),
    ]

    async def executor(t, ctx):
        return TaskOutcome(task_id=t.id, status="completed", output=t.id)

    # max_rounds=1 + 高 stagnation_threshold → 第 1 轮跑完触发硬上限
    config = OrchestratorConfig(
        max_rounds=1,
        convergence_config=ConvergenceConfig(stagnation_threshold=10),
    )
    orch = Orchestrator(
        requirement="实现多模块",
        tasks=tasks,
        executor=executor,
        config=config,
    )

    history = await orch.run()
    assert len(history) == 1
    assert orch.verdict.should_stop


@pytest.mark.asyncio
async def test_orchestrator_respects_max_rounds():
    """达到 max_rounds → MAX_ROUNDS verdict (硬上限)."""
    from auto_engineering.loop.convergence import (
        LEVEL_HARD_LIMIT,
        ConvergenceConfig,
    )

    # 用永远不收敛的 executor (不触发语义/质量门)
    async def executor(t, ctx):
        return TaskOutcome(task_id=t.id, status="completed", output="still going")

    task = make_task("loop_task")
    # 高 stagnation_threshold (10) 防止停滞检测过早触发
    # max_rounds=2 触发硬上限
    config = OrchestratorConfig(
        max_rounds=2,
        convergence_config=ConvergenceConfig(stagnation_threshold=10),
    )
    orch = Orchestrator(
        requirement="loop test",
        tasks=[task],
        executor=executor,
        config=config,
    )

    history = await orch.run()
    assert len(history) == 2
    assert orch.verdict is not None
    assert orch.verdict.should_stop
    # 硬上限
    assert orch.verdict.level == LEVEL_HARD_LIMIT


@pytest.mark.asyncio
async def test_orchestrator_propagates_conflict_error():
    """Orchestrator 构造时若文件冲突 → 抛 ConflictError."""
    bad_tasks = [
        make_task("t1", ["src/shared.py"]),
        make_task("t2", ["src/shared.py"]),
    ]

    async def executor(t, ctx):
        return TaskOutcome(task_id=t.id, status="completed", output="x")

    orch = Orchestrator(
        requirement="conflict test",
        tasks=bad_tasks,
        executor=executor,
    )
    with pytest.raises(ConflictError):
        await orch.run()


# ============================================================
# F. CancellationToken 整合
# ============================================================


@pytest.mark.asyncio
async def test_orchestrator_cancellation_stops_loop():
    """Orchestrator.run() 接受 cancellation token → cancelled 时停止."""

    async def executor(t, ctx):
        await asyncio.sleep(0.05)
        return TaskOutcome(task_id=t.id, status="completed", output="x")

    # 导入 cancellation token
    from auto_engineering.runtime.cancellation import CancellationToken

    task = make_task("task1")
    config = OrchestratorConfig(max_rounds=10)
    orch = Orchestrator(
        requirement="cancel test",
        tasks=[task],
        executor=executor,
        config=config,
    )

    token = CancellationToken()

    async def cancel_after_first_round():
        # 第一轮完成后取消
        await asyncio.sleep(0.15)
        token.cancel()

    cancel_task = asyncio.create_task(cancel_after_first_round())
    history = await orch.run(cancellation=token)
    await cancel_task

    # 至少跑过一轮, 但因为 cancellation 提前停止
    assert len(history) >= 1
    assert len(history) < 10  # 没跑到 max_rounds


# ============================================================
# G. v2.2 Phase H — RoundResult 集成 Gate (P2.4)
# 设计: RoundResult 真含 gate_results 字段 + run_round 跑 Gate
#       Orchestrator 不再 _build_history 跑 Gate, 改从 RoundResult 读
# ============================================================


@pytest.mark.asyncio
async def test_round_result_contains_gate_results_after_run_round(tmp_path):
    """run_round 接受 gates + project_root → RoundResult.gate_results 非空.

    严禁虚化: 真跑 SafetyGate + LintGate (无 mock), 验证 gate_results 含 verdicts.
    """
    from auto_engineering.gates.lint import LintGate
    from auto_engineering.gates.safety import SafetyGate

    # 真项目根 (一个简单 print 文件, ruff 通过, 无 secret)
    (tmp_path / "ok.py").write_text('print("hello")\n')

    async def executor(task, ctx):
        return TaskOutcome(task_id=task.id, status="completed", output="done")

    task = make_task("t1")
    result = await run_round(
        tasks=[task],
        executor=executor,
        gates=[SafetyGate(), LintGate()],
        project_root=tmp_path,
    )
    # 🔥 RoundResult 真含 gate_results (Phase H 新增)
    assert result.gate_results != {}, (
        f"gate_results 应非空, 实际: {result.gate_results}"
    )
    assert "safety" in result.gate_results
    assert "lint" in result.gate_results
    # SafetyGate/LintGate 通过无 secret + ruff pass 的目录
    assert result.gate_results["safety"].passed
    assert result.gate_results["lint"].passed


@pytest.mark.asyncio
async def test_round_result_all_gates_passed_property(tmp_path):
    """all_gates_passed property: 所有 gate_results[name].passed == True → True."""
    from auto_engineering.gates.lint import LintGate
    from auto_engineering.gates.safety import SafetyGate

    (tmp_path / "ok.py").write_text('print("hello")\n')

    async def executor(task, ctx):
        return TaskOutcome(task_id=task.id, status="completed", output="done")

    task = make_task("t1")
    result = await run_round(
        tasks=[task],
        executor=executor,
        gates=[SafetyGate(), LintGate()],
        project_root=tmp_path,
    )
    # 所有 Gate 真 pass → all_gates_passed == True
    assert result.all_gates_passed, (
        f"all_gates_passed 应 True, gate_results: {result.gate_results}"
    )


@pytest.mark.asyncio
async def test_round_result_handles_gate_exceptions(tmp_path):
    """Gate 抛异常时, gate_results 含 passed=False entry, 不传播异常.

    严禁虚化: 用一个真会抛异常的 Gate (run() 抛 RuntimeError),
    验证 RoundResult 吞掉异常 + 写入 failed Verdict.
    """
    from auto_engineering.gates.base import Gate

    class BoomGate(Gate):
        name = "boom"

        def run(self, project_root):  # type: ignore[override]
            raise RuntimeError("gate crashed intentionally")

    async def executor(task, ctx):
        return TaskOutcome(task_id=task.id, status="completed", output="done")

    task = make_task("t1")
    # 不应抛异常 — RoundResult 吞掉 + 写入 failed Verdict
    result = await run_round(
        tasks=[task],
        executor=executor,
        gates=[BoomGate()],
        project_root=tmp_path,
    )
    assert "boom" in result.gate_results
    assert result.gate_results["boom"].passed is False
    # 异常 message 写入 verdict.message
    assert "gate crashed intentionally" in result.gate_results["boom"].message
    # all_gates_passed = False (因为有 failed entry)
    assert result.all_gates_passed is False


@pytest.mark.asyncio
async def test_orchestrator_reads_gate_results_from_round_result(tmp_path):
    """Orchestrator._build_history 从 RoundResult.gate_results 读 (不再硬编码).

    严禁虚化: 真跑 Orchestrator + SafetyGate + LintGate, 验证
    RoundHistory.gate_results 从 RoundResult 读 (含 'safety' + 'lint' keys).
    """
    from auto_engineering.gates.lint import LintGate
    from auto_engineering.gates.safety import SafetyGate
    from auto_engineering.loop.convergence import ConvergenceConfig

    (tmp_path / "ok.py").write_text('print("hello")\n')

    async def executor(task, ctx):
        return TaskOutcome(task_id=task.id, status="completed", output="done")

    task = make_task("t1")
    config = OrchestratorConfig(
        max_rounds=1,
        convergence_config=ConvergenceConfig(stagnation_threshold=10),
        gates=[SafetyGate(), LintGate()],
        project_root=tmp_path,
    )
    orch = Orchestrator(
        requirement="gate integration test",
        tasks=[task],
        executor=executor,
        config=config,
    )
    history = await orch.run()
    # 第一轮的 RoundHistory.gate_results 应从 RoundResult 读
    assert len(history) == 1
    assert history[0].gate_results != {}, (
        f"RoundHistory.gate_results 应从 RoundResult 读, 实际: {history[0].gate_results}"
    )
    # 含 'safety' + 'lint' (从 RoundResult.gate_results keys 来)
    assert "safety" in history[0].gate_results
    assert "lint" in history[0].gate_results
    # 都通过 (v2.3 Phase D: gate_results 是 dict[gate_name, Verdict])
    assert history[0].gate_results["safety"].passed is True
    assert history[0].gate_results["lint"].passed is True


# ============================================================
# H. v2.3 Phase C — Orchestrator 增量 task 选择 (P0.3)
# 设计: Round 1 全跑, Round 2+ 仅跑失败 / 新增 task (避免每轮重跑浪费 LLM token)
# ============================================================


def _build_round_history_with_outcomes(
    round_id: int,
    task_outcomes: dict[str, str],
    tasks_run: list[str] | None = None,
) -> RoundHistory:
    """构造测试用 RoundHistory (含 tasks_run + 模拟 task_outcomes).

    Args:
        round_id: 轮次 ID
        task_outcomes: {task_id: status} (status: "completed" / "failed")
        tasks_run: 本轮跑的 task IDs (Phase 2.3-C 新增字段)

    Note:
        RoundHistory 含 tasks_run + task_outcomes 两个字段
        (Phase 2.3-C 增量选择依赖).
    """
    from auto_engineering.loop.convergence import RoundHistory

    return RoundHistory(
        round_id=round_id,
        files_changed=len(task_outcomes),
        tasks_run=tasks_run or list(task_outcomes.keys()),
        task_outcomes=dict(task_outcomes),
    )


def test_select_round_tasks_round_1_all():
    """Round 1: 跑所有 task (history 为空).

    严禁虚化: 直接调 _select_round_tasks, 验证 Round 1 + 空 history 时返回所有 task.
    """
    tasks = [
        make_task("t1"),
        make_task("t2"),
        make_task("t3"),
    ]
    orch = Orchestrator(
        requirement="round 1 all",
        tasks=tasks,
        executor=None,  # type: ignore[arg-type]  # _select_round_tasks 不调 executor
    )
    selected = orch._select_round_tasks(round_id=1, history=[])
    assert {t.id for t in selected} == {"t1", "t2", "t3"}


def test_select_round_tasks_round_2_only_failed():
    """Round 2: 仅跑 Round 1 中失败的 task (output=None/FAILED).

    严禁虚化: 构造 Round 1 history 含 t1=completed / t2=failed, 验证
    Round 2 只选 t2 (t1 已 completed 不重跑).
    """
    tasks = [
        make_task("t1"),
        make_task("t2"),
    ]
    # Round 1 history: t1 成功, t2 失败
    history_round_1 = _build_round_history_with_outcomes(
        round_id=1,
        task_outcomes={"t1": "completed", "t2": "failed"},
    )
    orch = Orchestrator(
        requirement="round 2 failed only",
        tasks=tasks,
        executor=None,  # type: ignore[arg-type]
    )
    selected = orch._select_round_tasks(round_id=2, history=[history_round_1])
    # 仅 t2 (失败) 入选, t1 (completed) 跳过
    selected_ids = {t.id for t in selected}
    assert selected_ids == {"t2"}, (
        f"Round 2 应仅选 failed task (t2), 实际: {selected_ids}"
    )


def test_select_round_tasks_round_2_includes_new_task():
    """Round 2: 包含历史中未跑过的新 task.

    严禁虚化: Round 1 跑了 t1 (completed), Round 2 时 self.tasks 多了 t3.
    验证 Round 2 选 t2 (failed) + t3 (新增).
    """
    # Round 1 时只有 t1 + t2 (initial_tasks 变量去掉 — 直接用 history 表达)
    history_round_1 = _build_round_history_with_outcomes(
        round_id=1,
        task_outcomes={"t1": "completed", "t2": "failed"},
        tasks_run=["t1", "t2"],
    )
    # Round 2 时新增 t3 (self.tasks 多了 t3)
    updated_tasks = [
        make_task("t1"),
        make_task("t2"),
        make_task("t3"),  # 新加
    ]
    orch = Orchestrator(
        requirement="round 2 new task",
        tasks=updated_tasks,
        executor=None,  # type: ignore[arg-type]
    )
    selected = orch._select_round_tasks(round_id=2, history=[history_round_1])
    selected_ids = {t.id for t in selected}
    # t1 (completed 跳过) + t3 (新增 入选) + t2 (failed 入选)
    assert "t1" not in selected_ids, f"t1 已 completed, 不应重跑: {selected_ids}"
    assert "t2" in selected_ids, f"t2 failed, 应重跑: {selected_ids}"
    assert "t3" in selected_ids, f"t3 新加, 应跑: {selected_ids}"


def test_select_round_tasks_round_3_skip_completed():
    """Round 3: 跳过 Round 1+2 都 completed 的 task.

    严禁虚化: Round 1 (t1=completed, t2=failed), Round 2 (t2=completed).
    验证 Round 3 不跑任何 task (所有都 completed).
    """
    tasks = [
        make_task("t1"),
        make_task("t2"),
    ]
    history_round_1 = _build_round_history_with_outcomes(
        round_id=1,
        task_outcomes={"t1": "completed", "t2": "failed"},
        tasks_run=["t1", "t2"],
    )
    history_round_2 = _build_round_history_with_outcomes(
        round_id=2,
        task_outcomes={"t2": "completed"},
        tasks_run=["t2"],
    )
    orch = Orchestrator(
        requirement="round 3 all completed",
        tasks=tasks,
        executor=None,  # type: ignore[arg-type]
    )
    selected = orch._select_round_tasks(
        round_id=3, history=[history_round_1, history_round_2]
    )
    # t1 + t2 都 completed → 不跑任何 task
    assert selected == [], (
        f"Round 3 所有 task 已 completed, 应空列表, 实际: "
        f"{[t.id for t in selected]}"
    )


def test_round_history_has_tasks_run_field():
    """RoundHistory 字段 tasks_run: list[str] (Phase 2.3-C 新增).

    严禁虚化: 构造 RoundHistory 含 tasks_run, 验证字段存在且为 list[str].
    """
    from auto_engineering.loop.convergence import RoundHistory

    rh = RoundHistory(round_id=1, tasks_run=["t1", "t2", "t3"])
    assert rh.tasks_run == ["t1", "t2", "t3"]
    # 默认空列表 (向后兼容)
    rh_default = RoundHistory(round_id=2)
    assert rh_default.tasks_run == []
    # task_outcomes 字段也存在
    rh2 = RoundHistory(
        round_id=3, tasks_run=["t1"], task_outcomes={"t1": "completed"}
    )
    assert rh2.task_outcomes == {"t1": "completed"}


# ============================================================
# I. v2.3 Phase E — max_rounds 单一来源 (P1.1)
# 设计: 删除 OrchestratorConfig.max_rounds 字段, 复用 ConvergenceConfig.max_iterations
#       作为 Orchestrator 主循环上限的单一来源.
#       借鉴 LangGraph Pregel.recursion_limit (单一字段多处引用).
# ============================================================


@pytest.mark.asyncio
async def test_orchestrator_uses_convergence_config_max_iterations():
    """ConvergenceConfig.max_iterations 是 Orchestrator 主循环的唯一上限.

    严禁虚化: 改 ConvergenceConfig(max_iterations=3) → Orchestrator 跑 3 轮.
    验证: history 长度 == 3, verdict.level == LEVEL_HARD_LIMIT.
    """
    from auto_engineering.loop.convergence import (
        LEVEL_HARD_LIMIT,
        ConvergenceConfig,
    )

    async def executor(t, ctx):
        return TaskOutcome(task_id=t.id, status="completed", output="x")

    task = make_task("t1")
    # 仅传 ConvergenceConfig.max_iterations=3, 不传 max_rounds
    config = OrchestratorConfig(
        convergence_config=ConvergenceConfig(
            max_iterations=3,
            stagnation_threshold=10,  # 防止停滞检测干扰
        ),
    )
    orch = Orchestrator(
        requirement="single source test",
        tasks=[task],
        executor=executor,
        config=config,
    )
    history = await orch.run()
    # 跑 3 轮
    assert len(history) == 3, f"应跑 3 轮, 实际 {len(history)}"
    # 硬上限
    assert orch.verdict is not None
    assert orch.verdict.level == LEVEL_HARD_LIMIT
    assert orch.verdict.should_stop is True


def test_orchestrator_max_rounds_field_removed():
    """OrchestratorConfig 应删除 max_rounds 字段 (vars() 不含).

    严禁虚化: 构造 OrchestratorConfig() 用 vars() 检查所有字段,
    验证 'max_rounds' 不在字段列表里. 若仍存在则测试 FAIL.
    """
    config = OrchestratorConfig()
    fields = vars(config)
    assert "max_rounds" not in fields, (
        f"OrchestratorConfig 仍含 max_rounds 字段, 应删除. 实际 fields: "
        f"{list(fields.keys())}"
    )
    # 同时验证 dataclass 字段声明也不含 max_rounds
    from dataclasses import fields as dc_fields

    field_names = {f.name for f in dc_fields(OrchestratorConfig)}
    assert "max_rounds" not in field_names, (
        f"OrchestratorConfig dataclass 字段声明仍含 max_rounds: {field_names}"
    )


@pytest.mark.asyncio
async def test_orchestrator_default_max_iterations():
    """不传 ConvergenceConfig → 默认 max_iterations=10 (单一来源不变).

    严禁虚化: 构造 OrchestratorConfig() (无 convergence_config),
    验证 ConvergenceJudge.config.max_iterations == 10 (DEFAULT_MAX_ITERATIONS).
    """
    config = OrchestratorConfig()
    orch = Orchestrator(
        requirement="default test",
        tasks=[],
        executor=None,  # type: ignore[arg-type]
        config=config,
    )
    # __post_init__ 已构造 judge, 直接读
    assert orch.judge is not None
    assert orch.judge.config is not None
    assert orch.judge.config.max_iterations == 10, (
        f"默认 max_iterations 应为 10, 实际: {orch.judge.config.max_iterations}"
    )