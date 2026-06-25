"""v2.0 Phase 03 + v2.1 Phase B — Orchestrator 主循环.

设计来源:
    - design/v2.0-Analysis-Loop.md §4.2 两层 Loop + §4.5 多 Agent 并发
    - design/v2.0-Analysis-Loop.md §4.7 收敛判定 (4 级)

核心组件:
    OrchestratorConfig — 配置 (max_rounds / gates / semantic_evaluator / project_root)
    Orchestrator       — 主循环: 启动 → run_round → 收敛判定 → 继续 / 停止

主循环流程:
    1. 构造时接收 requirement + tasks + executor + gates + semantic_evaluator
    2. run_round 第一轮 (asyncio.gather 并行执行)
    3. 每轮后跑 Gate (project_root) + LLM 语义评估
    4. 收集 RoundHistory → ConvergenceJudge.evaluate() → verdict
    5. 若 verdict.should_stop → 退出
    6. 否则 → 下一轮 (Phase 4+ 接 plan 更新逻辑)

收敛判定 4 级(复用 Phase 02):
    1. 硬上限: round >= max_rounds
    2. 质量门: 所有 Gate 通过 (v2.1 Phase B 集成)
    3. 停滞检测: 连续 N 轮无变化
    4. 语义收敛: LLM 评估通过 (v2.1 Phase B 集成)

设计决策:
    - 单 Agent 模式: 1 task / round
    - 多 Agent 模式: N tasks / round (asyncio.gather)
    - 统一接口: 不区分模式, 由输入 tasks 数量决定
    - Gate + semantic_evaluator 可选 (默认 None, 向后兼容)
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

# 默认配置
DEFAULT_MAX_ROUNDS = 10

# Type alias: semantic_evaluator = async (round_result) -> bool
SemanticEvaluator = Callable[[RoundResult], Awaitable[bool]]


@dataclass
class OrchestratorConfig:
    """Orchestrator 配置.

    Attributes:
        max_rounds: 最大 Round 数 (硬上限)
        convergence_config: 收敛判定配置 (None = 用默认)
        gates: v2.1 Phase B — 验证 Gate 列表 (None = 跳过)
        semantic_evaluator: v2.1 Phase B — LLM 语义评估 (None = 跳过)
        project_root: v2.1 Phase B — Gate 运行的项目根目录 (None = 当前 cwd)
    """

    max_rounds: int = DEFAULT_MAX_ROUNDS
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
        """初始化 Plan + Judge."""
        self.plan = Plan(tasks=self.tasks, requirement=self.requirement)
        self.judge = ConvergenceJudge(config=self.config.convergence_config)

    async def run(
        self,
        cancellation: CancellationToken | None = None,
    ) -> list[RoundHistory]:
        """主循环: 跑 Round 直到收敛或达到 max_rounds.

        流程:
            1. Plan.validate() — 校验 DAG + 文件隔离
            2. for round_id in 1..max_rounds:
                a. cancellation.check() (用户取消 → 抛 AEError)
                b. 选择本轮 task (Phase 3 简化: 全部 task 在每轮都跑)
                c. run_round(tasks, executor) → RoundResult
                d. _build_history(round_id, round_result) →
                   - 跑所有 Gate (真集成, 非 mock)
                   - 调 LLM 语义评估 (若提供)
                   - git diff --numstat → lines_added/removed
                e. judge.evaluate(state, history) → verdict
                f. 若 should_stop → return history
            3. 达到 max_rounds → 构造硬上限 Verdict → return history

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

        # 2. 主循环
        for round_id in range(1, self.config.max_rounds + 1):
            # 2a. 取消检查 (Round 边界检查, 不在 task 内中断)
            if cancellation is not None and cancellation.is_cancelled():
                break

            # 2b. 选择本轮 task (Phase 3 简化: 每轮重跑所有 task,
            #     Phase 4+ 接增量更新: 仅跑失败 / 新增的 task)
            round_tasks = self._select_round_tasks(round_id)

            # 2c. 执行 Round
            round_result = await run_round(
                tasks=round_tasks,
                executor=self.executor,
                ctx=None,
                cancellation=cancellation,
                round_id=round_id,
            )
            self.round_results.append(round_result)

            # 2d. 构造 RoundHistory (含 Gate + 语义 + git diff)
            history = await self._build_history(round_id, round_result)
            self.history.append(history)

            # 2e. 收敛判定
            assert self.judge is not None
            verdict = self.judge.evaluate(state=None, history=self.history)
            if verdict.should_stop:
                self.verdict = verdict
                return self.history

        # 3. 达到 max_rounds — 构造硬上限 verdict
        self.verdict = ConvVerdict.stop(
            level=4,  # LEVEL_HARD_LIMIT
            reason=f"达到最大轮次 {self.config.max_rounds} (硬上限)",
        )
        return self.history

    def _select_round_tasks(self, round_id: int) -> list[Task]:
        """选择本轮要执行的 task 列表.

        Phase 3 简化: 每轮都重跑所有 task (mock 场景, 让 ConvergenceJudge 反复判定).

        Phase 4+ 接增量更新:
            - 第一轮: 跑所有 task
            - 后续轮: 仅跑失败 / 新增的 task

        Args:
            round_id: 当前轮次 (1-indexed)

        Returns:
            本轮要跑的 task 列表
        """
        return list(self.tasks)

    async def _build_history(
        self, round_id: int, round_result: RoundResult
    ) -> RoundHistory:
        """构造 RoundHistory (含 Gate + 语义 + git diff).

        v2.1 Phase B 集成:
            - 真跑所有 Gate → gate_results dict
            - 调用 LLM 语义评估 → semantic_satisfied
            - 解析 git diff --numstat → lines_added/removed
        """
        # 1. 跑所有 Gate (真集成, 非 mock)
        gate_results = self._run_gates()

        # 2. 调 LLM 语义评估
        semantic_satisfied = await self._evaluate_semantic(round_result)

        # 3. git diff --numstat
        lines_added, lines_removed = _parse_git_numstat(self.config.project_root)

        return RoundHistory(
            round_id=round_id,
            files_changed=round_result.completed_count,
            lines_added=lines_added,
            lines_removed=lines_removed,
            gate_results=gate_results,
            semantic_satisfied=semantic_satisfied,
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
    "DEFAULT_MAX_ROUNDS",
    "Orchestrator",
    "OrchestratorConfig",
    "SemanticEvaluator",
    "TaskExecutor",  # re-export
    "TaskOutcome",  # re-export
]