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
import logging
import subprocess
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from auto_engineering.errors import AEError, ErrorCode
from auto_engineering.gates.base import Gate, GateVerdict
from auto_engineering.loop.plan import Task
from auto_engineering.runtime.cancellation import CancellationToken

_logger = logging.getLogger("ae.loop.round")

if TYPE_CHECKING:
    from auto_engineering.loop.convergence import RoundHistory


@dataclass
class TaskOutcome:
    """单个 task 的执行结果.

    Attributes:
        task_id: 任务 ID
        status: completed | failed | cancelled
        output: 任务输出 (成功时, dict 形式承载 stage-specific 字段)
        error: 错误信息 (失败时)
        duration: 耗时 (秒)
        task_role: v5.0 M3 新增 — 对应 Task.role (architect/developer/critic),
                   供 _apply_outcome_to_state 分发写入 state 字段.
                   默认 None 保持向后兼容 (旧调用方无需传入).
    """

    task_id: str
    status: str  # completed | failed | cancelled
    output: Any = None
    error: str | None = None
    duration: float = 0.0
    task_role: str | None = None  # v5.0 M3 新增 (向后兼容: 默认 None)


@dataclass
class RoundResult:
    """一轮的汇总结果.

    Attributes:
        round_id: 轮次 ID
        outcomes: 每个 task 的执行结果 (顺序与输入无关, gather 不保证)
        gate_results: v2.2 Phase H — 本轮运行的 Gate 结果 dict[gate_name, GateVerdict].
                      包含 Gate 异常时的 failed GateVerdict (不传播给上层).
        history: v2.3 Phase G (P1.3) — 本轮的 RoundHistory 列表 (通常 1 个元素).
                 借鉴 LangGraph Pregel.tick() Packet 模式: run_round 末尾直接构造
                 RoundHistory 写入此字段, Orchestrator 不再 _build_history 二次包装.
        started_at: 启动时间戳
        finished_at: 完成时间戳
    """

    round_id: int
    stage: str = ""
    outcomes: list[TaskOutcome] = field(default_factory=list)
    gate_results: dict[str, GateVerdict] = field(default_factory=dict)
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
    """执行单个 task + 包装错误 + 统计耗时 + 支持取消.

    v5.0 §B2.12a — 错误分类:
        - AEError(ERR_TASK_CANCELLED) → outcome.status="cancelled"
        - asyncio.CancelledError       → outcome.status="cancelled"
        - Exception (其他)              → outcome.status="failed"

    v5.0 §B2.12a — per_task_ctx 独立构造:
        如果 ctx 是 TaskContext 实例, 为本 task 复制一份 (避免 shared ctx.task 串扰).
        否则透传原 ctx.
    """
    start = time.monotonic()

    # v5.0 §B2.12a: 独立 per_task_ctx — 避免并发 task 共享 ctx 字段时串扰
    task_ctx = _build_per_task_ctx(ctx, task)

    # v5.0 §B2.12a: 错误分类 — 三档 (cancelled AEError / asyncio.CancelledError / 其他)
    try:
        if cancellation is not None:
            cancellation.check()
        outcome = await executor(task, task_ctx)
        duration = time.monotonic() - start
        # 强制覆盖 duration (executor 可能不填)
        outcome.duration = duration
        return outcome
    except asyncio.CancelledError:
        # asyncio 取消 → cancelled outcome (不视为 failed)
        duration = time.monotonic() - start
        return TaskOutcome(
            task_id=task.id,
            status="cancelled",
            error="asyncio.CancelledError",
            duration=duration,
        )
    except Exception as exc:
        # v5.0 §B2.12a: AEError(TASK_CANCELLED) → cancelled; 其他 → failed
        if isinstance(exc, AEError) and exc.code is ErrorCode.TASK_CANCELLED:
            duration = time.monotonic() - start
            return TaskOutcome(
                task_id=task.id,
                status="cancelled",
                error=str(exc),
                duration=duration,
            )
        duration = time.monotonic() - start
        _logger.warning(
            "task %s 执行异常 (非取消类): %s", task.id, exc, exc_info=True,
        )
        return TaskOutcome(
            task_id=task.id,
            status="failed",
            error=str(exc),
            duration=duration,
        )


def _build_per_task_ctx(ctx: Any, task: Task) -> Any:
    """v5.0 §B2.12a — 为单个 task 构造独立 ctx, 避免并发共享导致串扰.

    策略:
        - 若 ctx 是 TaskContext (含 state 字段), 用 dataclasses.replace 复制后
          显式赋一个 `current_task_id` 标记 (向后兼容, 不影响已有字段)
        - 否则透传原 ctx (类型不识别时不复制, 保持向后兼容)

    Args:
        ctx: 共享 ctx (TaskContext 或其他)
        task: 当前 task

    Returns:
        独立 ctx (per_task_ctx) 或原 ctx
    """
    # 识别 TaskContext 类型 — 不引入硬 import, 用鸭子类型 (含 state + requirement 字段)
    if ctx is None:
        return None
    # 鸭子类型检查: 必须是 dataclass-like (有 state 字段)
    if hasattr(ctx, "state") and hasattr(ctx, "requirement"):
        try:
            from dataclasses import fields, replace

            # 仅当 dataclass 时才 replace
            if hasattr(ctx, "__dataclass_fields__"):
                # 复制 + 若 dataclass 有 current_task_id 字段则填入
                f_names = {f.name for f in fields(ctx)}
                if "current_task_id" in f_names:
                    return replace(ctx, current_task_id=task.id)
                # 没 current_task_id 字段 → 直接复制 (避免共享 state mutation 风险)
                return replace(ctx)
        except Exception:
            _logger.warning(
                "_inject_task_id failed for task=%s", task.id, exc_info=True,
            )
    return ctx


async def run_round(
    tasks: list[Task],
    executor: TaskExecutor,
    ctx: Any = None,
    cancellation: CancellationToken | None = None,
    round_id: int = 1,
    gates: list[Gate] | None = None,
    project_root: Path | None = None,
    stage: str = "",
    channel_versions: dict[str, int] | None = None,
    start_commit: str | None = None,
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
        stage: v5.0 §B2.12 — 当前阶段名 (architect/developer/critic),
               用于 _run_gates 按 applies_to_stages 过滤

    Returns:
        RoundResult 含每个 task 的 outcome + gate_results + history[0] (RoundHistory).
        借鉴 LangGraph Pregel.tick() Packet 模式: run_round 末尾直接构造 RoundHistory
        写入 round_result.history, Orchestrator 不再 _build_history 二次包装.
        semantic_satisfied 默认 None, 由 Orchestrator 在 run() 中补充.

    Note:
        - asyncio.gather 会并行执行所有 task (LLM 调用 I/O bound 天然适配)
        - 若 gather 中一个 task 抛异常, 默认 return_exceptions=False 会传播
          此实现包装 _execute_single 捕获异常, 返回 failed outcome (不传播)
        - Gate 异常不传播, 写入 GateVerdict(passed=False, message=str(exc))
        - 末位构造 RoundHistory (含 gate_results + files_changed + task_outcomes +
          lines_added/removed), semantic_satisfied 由 Orchestrator 写回
    """
    result = RoundResult(round_id=round_id, stage=stage)
    result.started_at = time.monotonic()

    if not tasks:
        result.finished_at = time.monotonic()
        # 即使无 task, 也跑 Gate (若提供) — Phase H 行为: Gate 在 task 之后跑
        # v5.0 §B6.1: 按 stage 过滤 Gate
        if gates and project_root is not None:
            _mutate_gates_with_diff(gates, project_root, start_commit)
            result.gate_results = await _run_gates(gates, project_root, stage=stage)
        await _attach_round_history(result, tasks, project_root, stage, channel_versions, start_commit)
        return result

    # 创建并发任务
    coros = [
        _execute_single(task, ctx, executor, cancellation) for task in tasks
    ]
    # gather 并行执行 (D-P2-3: return_exceptions=True 防御性 — 防止未来
    # refactor 让 _execute_single 重新抛出时一个 task 异常取消整个 round.
    # 当前 _execute_single 内部捕获所有 Exception 返回 failed outcome,
    # 所以 return_exceptions=True 不会改变行为, 但提供 belt-and-suspenders.)
    #
    # v5.4 审计 P2-21: 防御性断言 — 并行 task 写同一 EngineState channel
    # 会导致未定义行为. 当前每个 task 独占不同 channel, 此断言作为回归栅栏.
    assert len({t.id for t in tasks}) == len(tasks), "duplicate task ids in round"
    gathered = await asyncio.gather(*coros, return_exceptions=True)
    outcomes: list[TaskOutcome] = []
    for item in gathered:
        if isinstance(item, BaseException):
            # 防御路径: _execute_single 重新抛出 (例如未来 asyncio.CancelledError)
            outcomes.append(
                TaskOutcome(
                    task_id="<gathered-exception>",
                    status="failed",
                    output=None,
                    error=f"gathered exception: {type(item).__name__}: {item}",
                )
            )
        else:
            outcomes.append(item)
    result.outcomes = outcomes
    result.finished_at = time.monotonic()

    # v2.2 Phase H: 跑 Gate (task 完成后), 写入 gate_results
    # v5.0 §B6.1: 按 stage 过滤
    if gates and project_root is not None:
        _mutate_gates_with_diff(gates, project_root, start_commit)
        result.gate_results = await _run_gates(gates, project_root, stage=stage)

    # v2.3 Phase G (P1.3): 末尾构造 RoundHistory 写入 round_result.history
    await _attach_round_history(result, tasks, project_root, stage, channel_versions, start_commit)
    return result


async def _attach_round_history(
    result: RoundResult,
    tasks: list[Task],
    project_root: Path | None,
    stage: str = "",
    channel_versions: dict[str, int] | None = None,
    start_commit: str | None = None,
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
        channel_versions: 当前 state channel 版本号 (供停滞检测)
    """
    from auto_engineering.loop.convergence import RoundHistory

    # v2.5 P2-D-1: _parse_git_numstat 是同步 subprocess.run, 在 async
    # 上下文会阻塞 event loop. 通过 asyncio.to_thread 移到 thread pool.
    # 同 P0-1 asyncio.to_thread 模式.
    lines_added, lines_removed = await asyncio.to_thread(
        _parse_git_numstat, project_root, start_commit
    )
    history = RoundHistory(
        round_id=result.round_id,
        stage=stage,
        files_changed=result.completed_count,
        lines_added=lines_added,
        lines_removed=lines_removed,
        gate_results=dict(result.gate_results),
        guardrail_result=None,
        semantic_satisfied=None,
        tasks_run=[t.id for t in tasks],
        task_outcomes={o.task_id: o.status for o in result.outcomes},
        channel_versions=channel_versions or {},
    )
    result.history = [history]


def _parse_git_numstat(
    project_root: Path | None, start_commit: str | None = None,
) -> tuple[int, int]:
    """解析 git diff 输出 → (lines_added, lines_removed).

    优先使用 start_commit (缓存的上轮 HEAD hash), 若 diff 为空则降级到 HEAD~1.
    start_commit 避免 rebase/squash 后 HEAD~1 指向错误基准.

    仓库无 HEAD / git 不可用 → (0, 0)
    """

    cwd = str(project_root) if project_root is not None else "."

    def _run_diff(args: list[str]) -> subprocess.CompletedProcess | None:
        try:
            return subprocess.run(
                ["git", "diff", "--numstat", *args],
                cwd=cwd, capture_output=True, text=True, timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            _logger.debug("git diff 执行失败 (文件缺失/超时)")
            return None

    result_run = None
    if start_commit:
        result_run = _run_diff([start_commit, "HEAD"])
        # 降级: start_commit diff 为空时回退到 HEAD~1 (如 round 中无新 commit)
        if result_run and result_run.returncode == 0 and not result_run.stdout.strip():
            result_run = _run_diff(["HEAD~1", "HEAD"])
    if result_run is None:
        result_run = _run_diff(["HEAD~1", "HEAD"])

    if result_run is None or result_run.returncode != 0:
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
            _logger.debug("git diff 行解析失败: %s", line)
            continue
    return (total_added, total_removed)


def _parse_git_changed_files(
    project_root: Path | None, start_commit: str | None = None,
) -> list[str]:
    """v5.4: 获取 start_commit..HEAD 之间变更的文件列表 (相对路径).

    供 AuditGate 增量扫描 — 避免每轮扫描全项目文件.
    git 不可用或无变更 → 返回空列表.
    """
    cwd = str(project_root) if project_root is not None else "."
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", start_commit or "HEAD~1", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return [f.strip() for f in result.stdout.splitlines() if f.strip()]
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        _logger.debug("git diff 文件列表获取失败")
    return []


def _mutate_gates_with_diff(
    gates: list[Gate],
    project_root: Path,
    start_commit: str | None,
) -> None:
    """副作用: 把本轮 git diff 变更文件列表注入 gates[].contracts (原地修改).

    若 git 不可用或无变更 → 不修改 gate.contracts.
    供 AuditGate 增量扫描使用.
    """
    changed = _parse_git_changed_files(project_root, start_commit)
    if not changed:
        return
    enrichment = {"files_changed": changed}
    for g in gates:
        if g.contracts is None:
            g.contracts = enrichment
        else:
            g.contracts = {**g.contracts, "files_changed": changed}


async def _run_gates(
    gates: list[Gate],
    project_root: Path,
    stage: str = "",
) -> dict[str, GateVerdict]:
    """跑 Gate 列表, 返回 {gate_name: GateVerdict} dict.

    v5.0 §B6.1+§B6.2 — 按 stage 过滤 Gate:
        - 若 stage 非空, 仅跑 g.applies_to_stages 含 stage 的 Gate
        - 若 stage 为空, 跑所有 Gate (向后兼容, 默认行为)

    v5.5 P0-2: contracts 不再透传 — 调用方在 gate.contracts 实例属性上预设.

    Gate 异常被吞, 写入 GateVerdict(passed=False, message=str(exc)).
    始终写入 dict (含失败 entry), 让 RoundResult.all_gates_passed 能正确反映"有 Gate 失败".

    v2.5 P2-D-2: 之前串行跑 (test 60s + lint 30s + type_check 30s + safety 30s
    + coverage 60s + build 30s = ~4 分钟/round × 10 rounds = 40 分钟).
    改为 asyncio.gather + asyncio.to_thread 并行跑. 7 个 Gate 都是
    read-only (scan / run linter / type check), 无共享写状态, 适合并行.
    总时长 ≈ max(单个 gate 时长) 而非 sum.
    """
    results: dict[str, GateVerdict] = {}

    # v5.0 §B6.1+§B6.2: stage 过滤 — 按 applies_to_stages 决定哪些 Gate 跑
    if stage:
        gates_to_run = [g for g in gates if stage in g.applies_to_stages]
    else:
        gates_to_run = list(gates)

    async def _run_one(gate: Gate) -> tuple[str, GateVerdict]:
        try:
            verdict = await asyncio.to_thread(
                gate.run, project_root
            )
        except Exception as exc:
            verdict = GateVerdict.failed(
                f"Gate {gate.name} {type(exc).__name__}: {exc}",
                gate_name=gate.name,
            )
        return gate.name, verdict

    # 并行跑 (D-P2-3: return_exceptions=True 防御)
    if not gates_to_run:
        return results
    gathered = await asyncio.gather(
        *[_run_one(g) for g in gates_to_run], return_exceptions=True
    )
    for item in gathered:
        if isinstance(item, BaseException):
            # 防御路径 (理论不应发生, _run_one 已捕获所有 Exception)
            continue
        name, verdict = item
        results[name] = verdict
    return results


__all__ = [
    "RoundResult",
    "TaskExecutor",
    "TaskOutcome",
    "run_round",
]