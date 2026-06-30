"""v2.0 Phase 03 + v2.1 Phase B — Orchestrator 主循环.

设计来源:
    - design/v2.0-Analysis-Loop.md §4.2 两层 Loop + §4.5 多 Agent 并发
    - design/v2.0-Analysis-Loop.md §4.7 收敛判定 (4 级)

核心组件:
    OrchestratorConfig — 配置 (gates / semantic_evaluator / project_root / agent_runtime)
    Orchestrator       — 主循环: 启动 → run_round → 收敛判定 → 继续 / 停止

主循环流程:
    1. 构造时接收 requirement + tasks + executor + gates + semantic_evaluator
    2. run_round 第一轮 (asyncio.gather 并行执行)
    3. 每轮后跑 Gate (project_root) + LLM 语义评估
    4. 收集 RoundHistory → ConvergenceJudge.evaluate() → verdict
    5. 若 verdict.should_stop → 退出
    6. 否则 → 下一轮 (future 接 plan 更新逻辑)

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
    - v2.3 Phase G (P1.3): 删 _build_history, RoundResult.history 含 RoundHistory
      (run_round 末尾直接构造), Orchestrator 直接累加. 借鉴 LangGraph Pregel.tick()
      Packet 模式: 数据在生产方 (run_round) 直接打包, 调用方 (Orchestrator) 不再
      重复构造.
    - v2.3 Phase H (P1.4): OrchestratorConfig.agent_runtime 字段, Orchestrator
      按 task.role 查 Runtime.get(role).execute (替代单一 executor callback).
      借鉴 AutoGen GroupChat agent_selector: 用 task.role 路由到对应 agent.
      向后兼容: agent_runtime=None → 用构造参数 executor (旧行为).
"""

from __future__ import annotations

import os
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
from auto_engineering.runtime.context import TaskContext

if TYPE_CHECKING:
    from auto_engineering.engine.state import LoopState
    from auto_engineering.runtime.runtime import AgentRuntime

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
        semantic_evaluator: v2.1 Phase B — LLM 语义评估.
            None 时, **有 ANTHROPIC_API_KEY 且不在 LLM agent** (CLAUDE_CODE 未设置)
            自动启用 ClaudeSemanticEvaluator (v2.3 Phase J P1.6 — 内置 LLM evaluator).
            用户显式传值时不被覆盖.
            无 API key 或在 LLM agent 中时保持 None (graceful degradation,
            避免 Claude Code 自调 Claude 评估).
        project_root: v2.1 Phase B — Gate 运行的项目根目录 (None = 当前 cwd)
        agent_runtime: v2.3 Phase H (P1.4) — AgentRuntime 实例 (None = 用 self.executor).
            借鉴 AutoGen GroupChat agent_selector: 按 task.role 查 Runtime.get(role)
            调度到对应 Agent. 解决 P1.4 多 Agent 集成问题.
    """

    convergence_config: ConvergenceConfig | None = None
    gates: list[Gate] | None = None
    semantic_evaluator: SemanticEvaluator | None = None
    project_root: Path | None = None
    agent_runtime: AgentRuntime | None = None  # P1.4 — None = 旧行为 (用 executor)

    def __post_init__(self) -> None:
        """v2.3 Phase J (P1.6): 默认启用 ClaudeSemanticEvaluator (有 API key 时).

        行为契约:
            - semantic_evaluator 已是用户显式传入 (非 None) → 不覆盖
            - semantic_evaluator 为 None + 有 ANTHROPIC_API_KEY 且不在 LLM agent
              (CLAUDE_CODE 未设置) → 自动启用 ClaudeSemanticEvaluator (接 Claude API 真评估)
            - semantic_evaluator 为 None + 无 API key 或在 LLM agent → 保持 None
              (Orchestrator.run() 跳过语义评估, 避免 Claude Code 自调 Claude 评估)

        Why: 解决 P1.6 阻断 — 第 4 级语义收敛永远不触发 (生产环境无内置
        LLM evaluator, 用户需自己写). 默认启用让 LLM 评估开箱即用.
        借鉴 LangGraph ConditionalEdge: LLM 评估路由开箱即用.
        与 settings.py:49-50 LLM-agent skip 同模式 — Claude Code 运行时
        ANTHROPIC_API_KEY 由 agent 自带, 不应再触发自评估 (commit fae3255/7f12a70).
        """
        in_llm_agent = bool(os.environ.get("CLAUDE_CODE"))
        if (
            self.semantic_evaluator is None
            and os.environ.get("ANTHROPIC_API_KEY")
            and not in_llm_agent
        ):
            # 延迟 import 避免循环依赖 (semantic_evaluator → orchestrator 反向)
            from auto_engineering.loop.semantic_evaluator import (
                ClaudeSemanticEvaluator,
            )

            self.semantic_evaluator = ClaudeSemanticEvaluator()


@dataclass
class Orchestrator:
    """Orchestrator 主循环.

    Attributes:
        requirement: 原始需求描述
        tasks: 任务列表 (v2.0 由 Orchestrator 构造时传入, future 接 LLM 拆分)
        executor: 异步执行函数 (Task -> TaskOutcome)
        config: Orchestrator 配置
        plan: 构建后的 Plan (run() 时 validate)
        judge: 收敛判定器
        history: 历史轮次记录 (v2.3 Phase G P1.3: 累加自 round_result.history)
        round_results: 每轮的 RoundResult 列表 (v2.3 Phase G P1.3: history 在此内部)
        verdict: 最终判定
    """

    requirement: str
    tasks: list[Task]
    executor: TaskExecutor
    config: OrchestratorConfig = field(default_factory=OrchestratorConfig)
    plan: Plan | None = None
    judge: ConvergenceJudge | None = None
    # v2.5 P2-D-5: 用 deque(maxlen=50) 替换无界 list, 长 dev-loop 不爆内存.
    # Judge 只需最近 ~10 轮 (stagnation 阈值 2 + 留 buffer), 50 轮足够.
    history: deque[RoundHistory] = field(default_factory=lambda: deque(maxlen=50))
    round_results: deque[RoundResult] = field(
        default_factory=lambda: deque(maxlen=50)
    )
    verdict: ConvVerdict | None = None

    def __post_init__(self) -> None:
        """初始化 Plan + Judge + 选 executor (agent_runtime 优先).

        v2.3 Phase E (P1.1): 不再在 Orchestrator 自身存 max_rounds 字段,
        主循环从 self.judge.config.max_iterations 读 (单一来源).

        v2.3 Phase H (P1.4): 若 config.agent_runtime 提供, 用 _build_runtime_executor
        覆盖 self.executor. 借鉴 AutoGen GroupChat agent_selector 路由模式.
        向后兼容: agent_runtime=None → 保留构造参数 executor (旧行为).
        """
        self.plan = Plan(tasks=self.tasks, requirement=self.requirement)
        self.judge = ConvergenceJudge(config=self.config.convergence_config)
        # v2.3 Phase H (P1.4): agent_runtime 优先, 替代单一 executor callback
        if self.config.agent_runtime is not None:
            self.executor = self._build_runtime_executor(self.config.agent_runtime)

    def _build_runtime_executor(self, runtime: AgentRuntime) -> TaskExecutor:
        """构建从 AgentRuntime 调度的 executor.

        v2.3 Phase H (P1.4): 借鉴 AutoGen GroupChat agent_selector, 按 task.role
        查 Runtime.get(role).execute (懒实例化). task.role 在 Runtime 中未注册
        → 返回 failed TaskOutcome (graceful degradation, 不抛异常, 避免 round
        因单 task 错误完全失败).

        协议转换:
            loop.Task  →  runtime.Task (BaseAgent 期望的格式)
            ctx        →  TaskContext(state=LoopState(requirement=self.requirement))
            result.values → output=str(values)

        Args:
            runtime: AgentRuntime 实例 (已注册 architect/developer/critic 等)

        Returns:
            async (Task, ctx) -> TaskOutcome 函数 — 可被 run_round 直接调用
        """
        from auto_engineering.engine.state import LoopState
        from auto_engineering.runtime.task import Task as RuntimeTask

        async def runtime_executor(
            loop_task: Task, ctx: Any
        ) -> TaskOutcome:
            # 1. 按 role 查 Agent (懒实例化)
            agent = runtime.get(loop_task.role)
            if agent is None:
                # 未注册 → 失败 outcome (graceful degradation, 不抛)
                return TaskOutcome(
                    task_id=loop_task.id,
                    status="failed",
                    error=f"No agent registered for role: {loop_task.role}",
                )

            # 2. 构造 runtime.Task (BaseAgent 期望的格式)
            runtime_task = RuntimeTask(
                id=loop_task.id,
                description=loop_task.description,
                expected_output=loop_task.expected_output,
            )
            # 3. 构造 TaskContext (state 必填, 用 LoopState 默认值即可)
            state: LoopState = ctx if isinstance(ctx, LoopState) else LoopState(
                requirement=self.requirement
            )
            task_ctx = TaskContext(
                state=state,
                requirement=self.requirement,
            )

            # 4. 调 agent.execute (BaseAgent 协议)
            result = await agent.execute(runtime_task, task_ctx)
            # 5. 转 TaskOutcome (result.values -> output)
            return TaskOutcome(
                task_id=loop_task.id,
                status="completed",
                output=str(getattr(result, "values", result)),
            )

        return runtime_executor

    async def run(
        self,
        cancellation: CancellationToken | None = None,
    ) -> list[RoundHistory]:
        """主循环: 跑 Round 直到收敛或达到 max_iterations.

        流程:
            1. Plan.validate() — 校验 DAG + 文件隔离
            2. for round_id in 1..max_iterations:
                a. cancellation.check() (用户取消 → 抛 AEError)
                b. 选择本轮 task (v2.0 简化: 全部 task 在每轮都跑)
                c. 调 LLM 语义评估 (若提供) → semantic_satisfied
                d. run_round(tasks, executor, semantic_satisfied=semantic_satisfied)
                   → RoundResult (含 history[0]: RoundHistory, v2.3 Phase G P1.3)
                e. self.round_results.append(round_result)
                f. self.history.extend(round_result.history)  # 累加 (非 append)
                g. judge.evaluate(history) → verdict
                h. 若 should_stop → return history
            3. 达到 max_iterations → 构造硬上限 Verdict → return history

        v2.3 Phase G (P1.3): 删 _build_history, 借鉴 LangGraph Pregel.tick() Packet 模式.
            RoundHistory 在 run_round 末尾直接构造 (RoundResult.history 字段),
            Orchestrator 直接累加, 不再二次包装.

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

            # 2b. 选择本轮 task (v5.0 M4: 全部 task, v5.0 增量移到 plan.get_tasks_by_stage)
            round_tasks = list(self.tasks)

            # 2c. 执行 Round (v2.3 Phase G: run_round 末尾构造 RoundHistory,
            #     此时 semantic_satisfied=None, 2e 后会回填)
            round_result = await run_round(
                tasks=round_tasks,
                executor=self.executor,
                ctx=None,
                cancellation=cancellation,
                round_id=round_id,
                gates=self.config.gates,
                project_root=self.config.project_root,
            )

            # 2d. 调 LLM 语义评估 (旧契约: 喂 round_result) → 写回
            #     round_result.history[0].semantic_satisfied
            #     借鉴 LangGraph Pregel.tick() Packet 模式: 数据源头 (run_round) 构造
            #     RoundHistory, 调用方 (Orchestrator) 补充 semantic 后累加 history.
            semantic_satisfied = await self._evaluate_semantic(round_result)
            if round_result.history:
                round_result.history[0].semantic_satisfied = semantic_satisfied

            self.round_results.append(round_result)

            # 2e. 累加 round_result.history (v2.3 Phase G P1.3)
            self.history.extend(round_result.history)

            # 2f. 收敛判定
            assert self.judge is not None
            verdict = self.judge.evaluate(history=self.history)
            if verdict.should_stop:
                self.verdict = verdict
                return self.history

        # 3. 达到 max_iterations — 构造硬上限 verdict (P1.1: 单一来源)
        self.verdict = ConvVerdict.stop(
            level=4,  # LEVEL_HARD_LIMIT
            reason=f"达到最大轮次 {max_rounds} (硬上限)",
        )
        return self.history

    def _run_gates(self) -> dict[str, bool]:
        """跑 config.gates 列表中所有 Gate, 返回 {name: passed} dict.

        Gate 异常 / 不存在的 project_root → 跳过该 Gate (passed=False 不合理,
        改为不写入 dict, 让 ConvergenceJudge._check_quality_gates 不触发).

        Returns:
            dict[str, bool] — gate name → passed

        Note:
            v2.3 Phase G (P1.3): 此方法保留用于向后兼容 (可能被外部代码 import),
            但 Orchestrator 主循环已不调用 (Gate 在 run_round 内部跑).
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
        """调 LLM 语义评估 (若提供), 结果由 run() 写回 round_result.history[0].

        v2.3 Phase G (P1.3): 评估结果不直接构造 RoundHistory, 而是作为
        semantic_satisfied 字段写回 run_round 末尾构造的 RoundHistory.

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


__all__ = [
    "Orchestrator",
    "OrchestratorConfig",
    "SemanticEvaluator",
    "TaskExecutor",  # re-export
    "TaskOutcome",  # re-export
]