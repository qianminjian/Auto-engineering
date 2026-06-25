"""v2.0 Phase 03 — Round 生命周期 + asyncio.gather 并发调度.

设计来源: design/v2.0-Analysis-Loop.md §4.5 多 Agent 并发.

核心组件:
    TaskOutcome    — 单个 task 在 Round 中的执行结果
    RoundResult    — 一轮 (含 N 个 task) 的汇总结果
    Round          — Round 抽象 (含 metadata: round_id, requirement, started_at)
    run_round      — asyncio.gather 调度并行 task 的入口

并发模型:
    所有 task 在 Round 内通过 asyncio.gather 并行调度.
    LLM API 调用是 I/O bound, asyncio 天然适配 (无需 Worktree 隔离).
    文件冲突在 Plan 阶段被 check_file_isolation 拦截.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from auto_engineering.loop.plan import Task
from auto_engineering.runtime.cancellation import CancellationToken


@dataclass
class TaskOutcome:
    """单个 task 的执行结果.

    Attributes:
        task_id: 任务 ID
        status: completed | failed | cancelled
        output: 任务输出 (成功时)
        error: 错误信息 (失败时)
        duration: 耗时 (秒)
    """

    task_id: str
    status: str  # completed | failed | cancelled
    output: Any = None
    error: str | None = None
    duration: float = 0.0


@dataclass
class RoundResult:
    """一轮的汇总结果.

    Attributes:
        round_id: 轮次 ID
        outcomes: 每个 task 的执行结果 (顺序与输入无关, gather 不保证)
        started_at: 启动时间戳
        finished_at: 完成时间戳
    """

    round_id: int
    outcomes: list[TaskOutcome] = field(default_factory=list)
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

    def files_changed(self) -> int:
        """估算本轮修改文件数 (基于成功 task 数量, Phase 4+ 接真实 diff)."""
        # Phase 3 用 task 数估算
        return self.completed_count


# Type alias: executor = async (task, ctx) -> TaskOutcome
TaskExecutor = Callable[[Task, Any], Awaitable[TaskOutcome]]


async def _execute_single(
    task: Task,
    ctx: Any,
    executor: TaskExecutor,
    cancellation: CancellationToken | None,
) -> TaskOutcome:
    """执行单个 task + 包装错误 + 统计耗时 + 支持取消."""
    start = time.monotonic()
    try:
        if cancellation is not None:
            cancellation.check()
        outcome = await executor(task, ctx)
        duration = time.monotonic() - start
        # 强制覆盖 duration (executor 可能不填)
        outcome.duration = duration
        return outcome
    except Exception as exc:
        duration = time.monotonic() - start
        return TaskOutcome(
            task_id=task.id,
            status="failed",
            error=str(exc),
            duration=duration,
        )


async def run_round(
    tasks: list[Task],
    executor: TaskExecutor,
    ctx: Any = None,
    cancellation: CancellationToken | None = None,
    round_id: int = 1,
) -> RoundResult:
    """执行一个 Round: asyncio.gather 并行调度所有 task.

    Args:
        tasks: 本轮执行的 task 列表 (来自 Plan.parallelism_groups() 的一组)
        executor: 异步函数, 签名 async (task, ctx) -> TaskOutcome
        ctx: 共享上下文 (传递给 executor, 可以是 LoopState 等)
        cancellation: 可选 CancellationToken
        round_id: 轮次 ID (用于 RoundResult)

    Returns:
        RoundResult 含每个 task 的 outcome

    Note:
        - asyncio.gather 会并行执行所有 task (LLM 调用 I/O bound 天然适配)
        - 若 gather 中一个 task 抛异常, 默认 return_exceptions=False 会传播
          此实现包装 _execute_single 捕获异常, 返回 failed outcome (不传播)
    """
    result = RoundResult(round_id=round_id)
    result.started_at = time.monotonic()

    if not tasks:
        result.finished_at = time.monotonic()
        return result

    # 创建并发任务
    coros = [
        _execute_single(task, ctx, executor, cancellation) for task in tasks
    ]
    # gather 并行执行 (return_exceptions=False 因为 _execute_single 已经捕获)
    outcomes = await asyncio.gather(*coros)
    result.outcomes = list(outcomes)
    result.finished_at = time.monotonic()
    return result


@dataclass
class Round:
    """Round 抽象 — 包含元数据 + 触发执行.

    Attributes:
        round_id: 轮次 ID
        requirement: 本轮目标 (供 Round Close 报告)
        tasks: 本轮 task 列表
        plan_ref: 完整 plan 引用 (可选, 用于后续 round 关联)
    """

    round_id: int
    requirement: str
    tasks: list[Task]
    plan_ref: Any = None  # 避免循环 import

    async def execute(
        self,
        executor: TaskExecutor,
        ctx: Any = None,
        cancellation: CancellationToken | None = None,
    ) -> RoundResult:
        """执行本轮: 委托 run_round()."""
        return await run_round(
            tasks=self.tasks,
            executor=executor,
            ctx=ctx,
            cancellation=cancellation,
            round_id=self.round_id,
        )


__all__ = [
    "Round",
    "RoundResult",
    "TaskExecutor",
    "TaskOutcome",
    "run_round",
]