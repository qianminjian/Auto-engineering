"""v2.0 Phase 03 + v2.1 Phase B — Orchestrator 主循环.

设计来源:
    - design/v2.0-Analysis-Loop.md §4.2 两层 Loop + §4.5 多 Agent 并发
    - design/v2.0-Analysis-Loop.md §4.7 收敛判定 (4 级)

核心组件:
    OrchestratorConfig — 配置 (gates / semantic_evaluator / project_root)
    Orchestrator       — 主循环: 启动 → run_round → 收敛判定 → 继续 / 停止

主循环流程:
    1. 构造时接收 requirement + tasks + executor + gates + semantic_evaluator
    2. run_round 第一轮 (asyncio.gather 并行执行)
    3. 每轮后跑 Gate (project_root) + LLM 语义评估
    4. 收集 RoundHistory → ConvergenceJudge.evaluate() → verdict
    5. 若 verdict.should_stop → 退出
    6. 否则 → 下一轮 (Phase 4+ 接 plan 更新逻辑)

收敛判定 4 级(复用 Phase 02):
    1. 硬上限: round >= max_iterations (单一来源: ConvergenceConfig)
    2. 质量门: 所有 Gate 通过 (v2.1 Phase B 集成)
    3. 停滞检测: 连续 N 轮无变化
    4. 语义收敛: LLM 评估通过 (v2.1 Phase B 集成)

设计决策:
    - 单 Agent 模式: 1 task / round
    - 多 Agent 模式: N tasks / round (asyncio.gather)
    - 统一接口: 不区分模式, 由输入 tasks 数量决定
    - Gate + semantic_evaluator 可选 (默认 None, 向后兼容)
    - v2.3 Phase E (P1.1): 删 OrchestratorConfig.max_rounds,
      复用 ConvergenceConfig.max_iterations 作为主循环上限的单一来源.
      借鉴 LangGraph Pregel.recursion_limit (单一字段多处引用).
"""

from __future__ import annotations

import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from auto_engineering.gates.base import Gate, Verdict
from auto_engineering.loop.convergence import (
    ConvergenceConfig,
    ConvergenceJudge,
    RoundHistory,
)
from auto_engineering.loop.convergence import (
    Verdict as ConvVerdict,
)
from auto_engineering.loop.plan import Plan, Task
from auto_engineering.loop.round import (
    RoundResult,
    TaskExecutor,
    TaskOutcome,
    run_round,
)
from auto_engineering.runtime.cancellation import CancellationToken

# Type alias: semantic_evaluator = async (round_result) -> bool
SemanticEvaluator = Callable[[RoundResult], Awaitable[bool]]


@dataclass
class OrchestratorConfig:
    """Orchestrator 配置.

    Attributes:
        convergence_config: 收敛判定配置 (None = 用默认).
            含 max_iterations 字段, 是主循环硬上限的**单一来源**
            (v2.3 Phase E P1.1, 借鉴 LangGraph Pregel.recursion_limit).
        gates: v2.1 Phase B — 验证 Gate 列表 (None = 跳过)
        semantic_evaluator: v2.1 Phase B — LLM 语义评估 (None = 跳过)
        project_root: v2.1 Phase B — Gate 运行的项目根目录 (None = 当前 cwd)
    """

    convergence_config: ConvergenceConfig | None = None
    gates: list[Gate] | None = None
    semantic_evaluator: SemanticEvaluator | None = None
    project_root: Path | None = None


@dataclass
class Orchestrator:
    """Orchestrator 主循环.

    Attributes:
        requirement: 原始需求描述
        tasks: 任务列表 (Phase 3 由 Orchestrator 构造时传入, Phase 4+ 接 LLM 拆分)
        executor: 异步执行函数 (Task -> TaskOutcome)
        config: Orchestrator 配置
        plan: 构建后的 Plan (run() 时 validate)
        judge: 收敛判定器
        history: 历史轮次记录
        verdict: 最终判定
    """

    requirement: str
    tasks: list[Task]
    executor: TaskExecutor
    config: OrchestratorConfig = field(default_factory=OrchestratorConfig)
    plan: Plan | None = None
    judge: ConvergenceJudge | None = None
    history: list[RoundHistory] = field(default_factory=list)
    round_results: list[RoundResult] = field(default_factory=list)
    verdict: ConvVerdict | None = None

    def __post_init__(self) -> None:
        """初始化 Plan + Judge.

        v2.3 Phase E (P1.1): 不再在 Orchestrator 自身存 max_rounds 字段,
        主循环从 self.judge.config.max_iterations 读 (单一来源).
        """
        self.plan = Plan(tasks=self.tasks, requirement=self.requirement)
        self.judge = ConvergenceJudge(config=self.config.convergence_config)

    async def run(
        self,
        cancellation: CancellationToken | None = None,
    ) -> list[RoundHistory]:
        """主循环: 跑 Round 直到收敛或达到 max_iterations.

        流程:
            1. Plan.validate() — 校验 DAG + 文件隔离
            2. for round_id in 1..max_iterations:
                a. cancellation.check() (用户取消 → 抛 AEError)
                b. 选择本轮 task (Phase 3 简化: 全部 task 在每轮都跑)
                c. run_round(tasks, executor) → RoundResult
                d. _build_history(round_id, round_result) →
                   - 跑所有 Gate (真集成, 非 mock)
                   - 调 LLM 语义评估 (若提供)
                   - git diff --numstat → lines_added/removed
                e. judge.evaluate(state, history) → verdict
                f. 若 should_stop → return history
            3. 达到 max_iterations → 构造硬上限 Verdict → return history

        Args:
            cancellation: 可选 CancellationToken

        Returns:
            history 列表 (所有跑过的轮次)

        Raises:
            ConflictError: Plan 文件冲突 (validate 失败)
            AEError(TASK_CANCELLED): 用户取消
        """
        # 1. Plan 校验 (DAG + 文件隔离)
        assert self.plan is not None  # __post_init__ 保证
        self.plan.validate()

        # v2.3 Phase E (P1.1): 单一来源 — 从 judge.config.max_iterations 读
        assert self.judge is not None and self.judge.config is not None
        max_rounds = self.judge.config.max_iterations

        # 2. 主循环
        for round_id in range(1, max_rounds + 1):
            # 2a. 取消检查 (Round 边界检查, 不在 task 内中断)
            if cancellation is not None and cancellation.is_cancelled():
                break

            # 2b. 选择本轮 task (Phase 2.3-C: 增量选择)
            #     Round 1 跑所有 task, Round 2+ 仅跑 failed / 新增 task
            round_tasks = self._select_round_tasks(round_id, self.history)

            # 2c. 执行 Round (含 Gate 集成, v2.2 Phase H)
            round_result = await run_round(
                tasks=round_tasks,
                executor=self.executor,
                ctx=None,
                cancellation=cancellation,
                round_id=round_id,
                gates=self.config.gates,
                project_root=self.config.project_root,
            )
            self.round_results.append(round_result)

            # 2d. 构造 RoundHistory (从 RoundResult 读 gate_results, v2.2 Phase H)
            #     Phase 2.3-C: 传入 round_tasks, 让 RoundHistory.tasks_run 有值
            history = await self._build_history(round_id, round_result, round_tasks)
            self.history.append(history)

            # 2e. 收敛判定
            assert self.judge is not None
            verdict = self.judge.evaluate(state=None, history=self.history)
            if verdict.should_stop:
                self.verdict = verdict
                return self.history

        # 3. 达到 max_iterations — 构造硬上限 verdict (P1.1: 单一来源)
        self.verdict = ConvVerdict.stop(
            level=4,  # LEVEL_HARD_LIMIT
            reason=f"达到最大轮次 {max_rounds} (硬上限)",
        )
        return self.history

    def _select_round_tasks(
        self, round_id: int, history: list[RoundHistory]
    ) -> list[Task]:
        """选择本轮要执行的 task 列表.

        v2.3 Phase C: 增量选择 (避免每轮重跑所有 task 浪费 LLM token).

        规则:
            - Round 1: 跑所有 task (无历史可参考).
            - Round 2+: 仅跑 failed task (status="failed") 或
              新加 task (不在任何 history.tasks_run 中).

        Args:
            round_id: 当前轮次 (1-indexed)
            history: 历史轮次列表 (Round 2+ 时非空, Round 1 为空)

        Returns:
            本轮要跑的 task 列表

        Note:
            借鉴 LangGraph `Pregel._prepare_next_tasks` 用 channel_versions diff 找触发任务,
            简化版: 不引入 inverted index, 只看"failed + new" 两类 task.
        """
        if round_id == 1:
            return list(self.tasks)

        # 1. 收集历史所有 task ids (判断"新加")
        all_historical_task_ids: set[str] = set()
        for h in history:
            all_historical_task_ids.update(h.tasks_run)

        # 2. 收集历史最近一次"非 completed"的 task ids (判断"failed")
        #    逻辑: 对每个 task, 找其最近一轮的 outcome — 若非 completed 则重跑.
        last_outcome_per_task: dict[str, str] = {}
        for h in history:
            for tid, status in h.task_outcomes.items():
                last_outcome_per_task[tid] = status

        # 3. 选择: 新加 task + 最后一轮未 completed 的 task
        selected: list[Task] = []
        for t in self.tasks:
            if t.id not in all_historical_task_ids:
                # 新加 task — 必须跑
                selected.append(t)
            else:
                # 历史已跑过 — 看最后一轮 outcome
                last_status = last_outcome_per_task.get(t.id)
                if last_status != "completed":
                    # 未 completed (failed / cancelled / missing) → 重跑
                    selected.append(t)

        return selected

    async def _build_history(
        self,
        round_id: int,
        round_result: RoundResult,
        round_tasks: list[Task] | None = None,
    ) -> RoundHistory:
        """构造 RoundHistory (含 Gate + 语义 + git diff).

        v2.2 Phase H 重构:
            - Gate 不再由 Orchestrator 跑 (Phase B 实现绕开 RoundResult),
              改为从 round_result.gate_results (Run Round 时已跑) 读
            - 格式转换: dict[gate_name, Verdict] → dict[gate_name, bool]
            - LLM 语义评估 + git diff 仍在 Orchestrator (因为依赖 ctx / project_root)

        v2.3 Phase C:
            - 新增 round_tasks 参数, 写入 RoundHistory.tasks_run
              (供下一轮 _select_round_tasks 增量选择参考)
        """
        # 1. 从 RoundResult 读 gate_results (Phase H 真集成)
        #    v2.3 Phase D (P0.4): 直接传 Verdict, 不再降级为 bool (避免丢失 message)
        gate_results = dict(round_result.gate_results)

        # 2. 调 LLM 语义评估
        semantic_satisfied = await self._evaluate_semantic(round_result)

        # 3. git diff --numstat
        lines_added, lines_removed = _parse_git_numstat(self.config.project_root)

        # 4. Phase 2.3-C: 记录本轮跑的 task IDs + 每个 task 的 outcome
        tasks_run = [t.id for t in (round_tasks or [])]
        task_outcomes = {o.task_id: o.status for o in round_result.outcomes}

        return RoundHistory(
            round_id=round_id,
            files_changed=round_result.completed_count,
            lines_added=lines_added,
            lines_removed=lines_removed,
            gate_results=gate_results,
            semantic_satisfied=semantic_satisfied,
            tasks_run=tasks_run,
            task_outcomes=task_outcomes,
        )

    def _run_gates(self) -> dict[str, bool]:
        """跑 config.gates 列表中所有 Gate, 返回 {name: passed} dict.

        Gate 异常 / 不存在的 project_root → 跳过该 Gate (passed=False 不合理,
        改为不写入 dict, 让 ConvergenceJudge._check_quality_gates 不触发).

        Returns:
            dict[str, bool] — gate name → passed
        """
        if not self.config.gates:
            return {}

        project_root = self.config.project_root or Path.cwd()
        results: dict[str, bool] = {}
        for gate in self.config.gates:
            try:
                verdict: Verdict = gate.run(project_root)
                results[gate.name] = verdict.passed
            except Exception:
                # Gate 异常不传播, 跳过 (不写 dict → 不参与判定)
                continue
        return results

    async def _evaluate_semantic(
        self, round_result: RoundResult
    ) -> bool | None:
        """调 LLM 语义评估 (若提供).

        Returns:
            True/False — 评估器返回
            None — 未提供评估器 / 评估器异常
        """
        if self.config.semantic_evaluator is None:
            return None
        try:
            return await self.config.semantic_evaluator(round_result)
        except Exception:
            return None


def _parse_git_numstat(project_root: Path | None) -> tuple[int, int]:
    """解析 git diff --numstat HEAD~1 HEAD 输出.

    Args:
        project_root: 项目根目录 (None = 当前 cwd)

    Returns:
        (lines_added, lines_removed) 总和
        仓库无 HEAD / git 不可用 → (0, 0)
    """
    cwd = str(project_root) if project_root is not None else "."
    try:
        # HEAD~1..HEAD (若只有 1 个 commit, HEAD~1 不存在, 返回空)
        result = subprocess.run(
            ["git", "diff", "--numstat", "HEAD~1", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return (0, 0)

    if result.returncode != 0:
        return (0, 0)

    total_added = 0
    total_removed = 0
    for line in result.stdout.strip().splitlines():
        # numstat 格式: "<added>\t<removed>\t<file>"
        # 二进制文件: "-\t-\t<file>"
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


__all__ = [
    "Orchestrator",
    "OrchestratorConfig",
    "SemanticEvaluator",
    "TaskExecutor",  # re-export
    "TaskOutcome",  # re-export
]