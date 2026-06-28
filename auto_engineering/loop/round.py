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
from pathlib import Path
from typing import TYPE_CHECKING, Any

from auto_engineering.gates.base import Gate, Verdict
from auto_engineering.loop.plan import Task
from auto_engineering.runtime.cancellation import CancellationToken

if TYPE_CHECKING:
    from auto_engineering.loop.convergence import RoundHistory


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
        gate_results: v2.2 Phase H — 本轮运行的 Gate 结果 dict[gate_name, Verdict].
                      包含 Gate 异常时的 failed Verdict (不传播给上层).
        history: v2.3 Phase G (P1.3) — 本轮的 RoundHistory 列表 (通常 1 个元素).
                 借鉴 LangGraph Pregel.tick() Packet 模式: run_round 末尾直接构造
                 RoundHistory 写入此字段, Orchestrator 不再 _build_history 二次包装.
        started_at: 启动时间戳
        finished_at: 完成时间戳
    """

    round_id: int
    outcomes: list[TaskOutcome] = field(default_factory=list)
    gate_results: dict[str, Verdict] = field(default_factory=dict)
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
        # v2.0 用 task 数估算
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
    gates: list[Gate] | None = None,
    project_root: Path | None = None,
) -> RoundResult:
    """执行一个 Round: asyncio.gather 并行调度所有 task + 跑 Gate.

    Args:
        tasks: 本轮执行的 task 列表 (来自 Plan.parallelism_groups() 的一组)
        executor: 异步函数, 签名 async (task, ctx) -> TaskOutcome
        ctx: 共享上下文 (传递给 executor, 可以是 engine.state.LoopState 等)
        cancellation: 可选 CancellationToken
        round_id: 轮次 ID (用于 RoundResult)
        gates: v2.2 Phase H — 可选 Gate 列表, Round 完成后顺序执行
        project_root: v2.2 Phase H — Gate 运行的项目根目录 (与 gates 同时提供才生效)

    Returns:
        RoundResult 含每个 task 的 outcome + gate_results + history[0] (RoundHistory).
        借鉴 LangGraph Pregel.tick() Packet 模式: run_round 末尾直接构造 RoundHistory
        写入 round_result.history, Orchestrator 不再 _build_history 二次包装.
        semantic_satisfied 默认 None, 由 Orchestrator 在 run() 中补充.

    Note:
        - asyncio.gather 会并行执行所有 task (LLM 调用 I/O bound 天然适配)
        - 若 gather 中一个 task 抛异常, 默认 return_exceptions=False 会传播
          此实现包装 _execute_single 捕获异常, 返回 failed outcome (不传播)
        - Gate 异常不传播, 写入 Verdict(passed=False, message=str(exc))
        - 末位构造 RoundHistory (含 gate_results + files_changed + task_outcomes +
          lines_added/removed), semantic_satisfied 由 Orchestrator 写回
    """
    result = RoundResult(round_id=round_id)
    result.started_at = time.monotonic()

    if not tasks:
        result.finished_at = time.monotonic()
        # 即使无 task, 也跑 Gate (若提供) — Phase H 行为: Gate 在 task 之后跑
        if gates and project_root is not None:
            result.gate_results = _run_gates(gates, project_root)
        _attach_round_history(result, tasks, project_root)
        return result

    # 创建并发任务
    coros = [
        _execute_single(task, ctx, executor, cancellation) for task in tasks
    ]
    # gather 并行执行 (D-P2-3: return_exceptions=True 防御性 — 防止未来
    # refactor 让 _execute_single 重新抛出时一个 task 异常取消整个 round.
    # 当前 _execute_single 内部捕获所有 Exception 返回 failed outcome,
    # 所以 return_exceptions=True 不会改变行为, 但提供 belt-and-suspenders.)
    gathered = await asyncio.gather(*coros, return_exceptions=True)
    outcomes: list[TaskOutcome] = []
    for item in gathered:
        if isinstance(item, BaseException):
            # 防御路径: _execute_single 重新抛出 (例如未来 asyncio.CancelledError)
            outcomes.append(
                TaskOutcome(
                    task_id="<gathered-exception>",
                    success=False,
                    output="",
                    error=f"gathered exception: {type(item).__name__}: {item}",
                )
            )
        else:
            outcomes.append(item)
    result.outcomes = outcomes
    result.finished_at = time.monotonic()

    # v2.2 Phase H: 跑 Gate (task 完成后), 写入 gate_results
    if gates and project_root is not None:
        result.gate_results = _run_gates(gates, project_root)

    # v2.3 Phase G (P1.3): 末尾构造 RoundHistory 写入 round_result.history
    _attach_round_history(result, tasks, project_root)
    return result


def _attach_round_history(
    result: RoundResult,
    tasks: list[Task],
    project_root: Path | None,
) -> None:
    """在 run_round 末尾构造 RoundHistory 写入 result.history.

    v2.3 Phase G (P1.3) — 借鉴 LangGraph Pregel.tick() Packet 模式:
        - 从 RoundResult 读 gate_results (已就绪)
        - 从 RoundResult.outcomes 提取 task_outcomes
        - 从 result.completed_count 算 files_changed (兼容旧版估算)
        - 从 git diff --numstat HEAD~1 HEAD 算 lines_added/removed
        - 写入 result.history (1 个元素), semantic_satisfied=None
          (由 Orchestrator._evaluate_semantic 在 run() 中写回)

    Args:
        result: RoundResult (已含 outcomes + gate_results)
        tasks: 本轮 task 列表 (供 tasks_run)
        project_root: git diff 的项目根目录 (None = 跳过 git diff)
    """
    from auto_engineering.loop.convergence import RoundHistory

    lines_added, lines_removed = _parse_git_numstat(project_root)
    history = RoundHistory(
        round_id=result.round_id,
        files_changed=result.completed_count,
        lines_added=lines_added,
        lines_removed=lines_removed,
        gate_results=dict(result.gate_results),
        semantic_satisfied=None,
        tasks_run=[t.id for t in tasks],
        task_outcomes={o.task_id: o.status for o in result.outcomes},
    )
    result.history = [history]


def _parse_git_numstat(project_root: Path | None) -> tuple[int, int]:
    """解析 git diff --numstat HEAD~1 HEAD 输出 → (lines_added, lines_removed).

    从 auto_engineering.loop.orchestrator 提取 (Phase G P1.3):
        单一数据源: RoundHistory 构造在 round.py 内完成, 不需 Orchestrator 中转.
        仓库无 HEAD / git 不可用 → (0, 0)
    """
    import subprocess

    cwd = str(project_root) if project_root is not None else "."
    try:
        result_run = subprocess.run(
            ["git", "diff", "--numstat", "HEAD~1", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return (0, 0)

    if result_run.returncode != 0:
        return (0, 0)

    total_added = 0
    total_removed = 0
    for line in result_run.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        added_str, removed_str = parts[0], parts[1]
        if added_str == "-" or removed_str == "-":
            continue
        try:
            total_added += int(added_str)
            total_removed += int(removed_str)
        except ValueError:
            continue
    return (total_added, total_removed)


def _run_gates(gates: list[Gate], project_root: Path) -> dict[str, Verdict]:
    """跑 Gate 列表, 返回 {gate_name: Verdict} dict.

    Gate 异常被吞, 写入 Verdict(passed=False, message=str(exc)).
    与 Orchestrator._run_gates 不同: 这里始终写入 dict (含失败 entry),
    让 RoundResult.all_gates_passed 能正确反映"有 Gate 失败".
    """
    results: dict[str, Verdict] = {}
    for gate in gates:
        try:
            verdict = gate.run(project_root)
        except Exception as exc:
            verdict = Verdict.failed(
                f"Gate {gate.name} 异常: {exc}",
                gate_name=gate.name,
            )
        results[gate.name] = verdict
    return results


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