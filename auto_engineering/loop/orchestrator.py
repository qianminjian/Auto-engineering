"""v2.0 Phase 03 — Orchestrator 主循环: 需求 → 拆分 → Round Loop → 收敛.

设计来源: design/v2.0-Analysis-Loop.md §4.2 两层 Loop + §4.5 多 Agent 并发 + §4.7 收敛判定.

核心组件:
    OrchestratorConfig — 配置 (max_rounds 等)
    Orchestrator       — 主循环: 启动 → run_round → 收敛判定 → 继续 / 停止

主循环流程:
    1. 构造时接收 requirement + tasks + executor
    2. run_round 第一轮 (asyncio.gather 并行执行)
    3. 收集 RoundHistory → ConvergenceJudge.evaluate() → verdict
    4. 若 verdict.should_stop → 退出
    5. 否则 → 下一轮 (Phase 4+ 接 plan 更新逻辑)

收敛判定 4 级(复用 Phase 02):
    1. 硬上限: round >= max_rounds
    2. 质量门: 所有 Gate 通过
    3. 停滞检测: 连续 N 轮无变化
    4. 语义收敛: LLM 评估通过

设计决策:
    - 单 Agent 模式: 1 task / round
    - 多 Agent 模式: N tasks / round (asyncio.gather)
    - 统一接口: 不区分模式, 由输入 tasks 数量决定
"""

from __future__ import annotations

from dataclasses import dataclass, field

from auto_engineering.loop.convergence import (
    ConvergenceConfig,
    ConvergenceJudge,
    RoundHistory,
    Verdict,
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


@dataclass
class OrchestratorConfig:
    """Orchestrator 配置.

    Attributes:
        max_rounds: 最大 Round 数 (硬上限)
        convergence_config: 收敛判定配置 (None = 用默认)
    """

    max_rounds: int = DEFAULT_MAX_ROUNDS
    convergence_config: ConvergenceConfig | None = None


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
    verdict: Verdict | None = None

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
                d. 构造 RoundHistory → append history
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

            # 2d. 构造 RoundHistory
            history = self._build_history(round_id, round_result)
            self.history.append(history)

            # 2e. 收敛判定
            assert self.judge is not None
            verdict = self.judge.evaluate(state=None, history=self.history)
            if verdict.should_stop:
                self.verdict = verdict
                return self.history

        # 3. 达到 max_rounds — 构造硬上限 verdict
        self.verdict = Verdict.stop(
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

    def _build_history(
        self, round_id: int, round_result: RoundResult
    ) -> RoundHistory:
        """从 RoundResult 构造 RoundHistory (供 ConvergenceJudge 判定).

        Phase 3 简化:
            - files_changed = completed_count (粗略估算)
            - lines_added / removed = 0 (Phase 4+ 接真实 git diff)
            - gate_results = 空 (Phase 4+ 接 7 道 Gate)
            - semantic_satisfied = None (Phase 4+ 接 LLM 评估, Phase 3 不评估)

        Phase 4+ 实现:
            - git diff --numstat → lines_added / removed
            - Gate 0-6 结果汇总
            - LLM 评估 semantic_satisfied
        """
        return RoundHistory(
            round_id=round_id,
            files_changed=round_result.completed_count,
            lines_added=0,
            lines_removed=0,
            gate_results={},  # Phase 4+ 接 Gate 系统
            semantic_satisfied=None,  # Phase 3 mock 不评估, 让硬上限生效
        )


__all__ = [
    "DEFAULT_MAX_ROUNDS",
    "Orchestrator",
    "OrchestratorConfig",
    "TaskExecutor",  # re-export
    "TaskOutcome",  # re-export
]