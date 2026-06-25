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