"""v2.0 Phase 03 + v2.1 Phase B + v5.0 M4 — Orchestrator 主循环.

设计来源:
    - design/v2.0-Analysis-Loop.md §4.2 两层 Loop + §4.5 多 Agent 并发
    - design/v2.0-Analysis-Loop.md §4.7 收敛判定 (4 级)
    - design/v5.0-Design-Loop.md §B7.1 (12 步主循环) + §B7.4 (Checkpoint) + §B7.5 (Resume)

核心组件:
    OrchestratorConfig — 配置 (gates / semantic_evaluator / project_root / agent_runtime)
    Orchestrator       — 主循环: 启动 → run_round → 收敛判定 → 继续 / 停止

v5.0 M4 主循环流程 (12 步):
    step 1: Plan.validate() + state 初始化 + retry_ctr + router 初始化 + project_root 解析
    step 2: while round_id <= max_iter:
        2a cancellation check
        2b state.stage=="" → router.next 初始化
        2c 选 round_tasks (plan.get_tasks_by_stage)
        2d PRE Guardrail → _handle_guardrail_result
        2e run_round + _apply_outcome_to_state
        2f POST Guardrail → 同上 handler
        2g semantic_evaluator 写回 (仅 critic)
        2h MAJOR 计数更新 (critic)
        2i StageRouter.next + Judge.evaluate + 退出条件
    step 3: 退出块 (GOAL_ACHIEVED / max_iter / unexpected)

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
    - v5.0 M4: Orchestrator.__init__ 扩展 (checkpoint_store / guardrail_chain /
      stage_router), Orchestrator 内部用 EngineState channel 替代裸 history
      (v5.0 §B1.1 17 字段), 引入 _apply_outcome_to_state / _save_checkpoint /
      _derive_status / resume().
    - v5.0 M4: _select_round_tasks 删除 — 改为 plan.get_tasks_by_stage(stage)
      按 Stage 过滤 (architect/developer/critic), StageRouter 控制推进.
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
    from auto_engineering.engine.state import EngineState, LoopState
    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.guardrail import GuardrailChain
    from auto_engineering.loop.stage_router import StageRouter
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
        checkpoint_store: v5.0 M4 (B2.1) — Checkpoint 持久化 store.
            None 时, 主循环不调用 _save_checkpoint (向后兼容, 测试场景).
        guardrail_chain: v5.0 M4 (B2.1) — Guardrail 链.
            None 时, 等价空链 (全 pass). 主循环 step 2d/2f 检查.
        stage_router: v5.0 M4 (B2.1) — Stage 状态机路由器.
            None 时, 主循环用 StageRouter() 默认值 (max_majors_in_a_row=2,
            max_total_majors=3). 测试可注入 mock router.
    """

    convergence_config: ConvergenceConfig | None = None
    gates: list[Gate] | None = None
    semantic_evaluator: SemanticEvaluator | None = None
    project_root: Path | None = None
    agent_runtime: AgentRuntime | None = None  # P1.4 — None = 旧行为 (用 executor)
    # v5.0 M4: 3 个新字段 (B2.1)
    checkpoint_store: "SQLiteCheckpointStore | None" = None
    guardrail_chain: "GuardrailChain | None" = None
    stage_router: "StageRouter | None" = None

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
    # v5.0 M4 (B2.1): 内部状态 — 由 __post_init__ 初始化, 默认占位.
    # _state: EngineState 17 字段 Channel 容器 (v5.0 §B1.1)
    # _retry_counters: Guardrail retry 计数 (per-stage 隔离)
    # _router: StageRouter 引用 (从 config 拉, 避免每个 step 都访问 config)
    _state: "EngineState | None" = None
    _retry_counters: dict[str, int] = field(default_factory=dict)
    _router: "StageRouter | None" = None

    def __post_init__(self) -> None:
        """初始化 Plan + Judge + 选 executor (agent_runtime 优先).

        v2.3 Phase E (P1.1): 不再在 Orchestrator 自身存 max_rounds 字段,
        主循环从 self.judge.config.max_iterations 读 (单一来源).

        v2.3 Phase H (P1.4): 若 config.agent_runtime 提供, 用 _build_runtime_executor
        覆盖 self.executor. 借鉴 AutoGen GroupChat agent_selector 路由模式.
        向后兼容: agent_runtime=None → 保留构造参数 executor (旧行为).

        v5.0 M4 (B2.1): 初始化 _state (EngineState Channel 容器) + _retry_counters
        + _router (从 config 拉, 简化后续 step 访问).
        """
        self.plan = Plan(tasks=self.tasks, requirement=self.requirement)
        self.judge = ConvergenceJudge(config=self.config.convergence_config)
        # v2.3 Phase H (P1.4): agent_runtime 优先, 替代单一 executor callback
        if self.config.agent_runtime is not None:
            self.executor = self._build_runtime_executor(self.config.agent_runtime)
        # v5.0 M4: 内部状态初始化
        from auto_engineering.engine.state import EngineState
        from auto_engineering.loop.stage_router import StageRouter

        if self._state is None:
            self._state = EngineState(requirement=self.requirement)
        if self._router is None:
            self._router = (
                self.config.stage_router
                if self.config.stage_router is not None
                else StageRouter()
            )

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
        """v5.0 M4: 12 步主循环 (B7.1).

        流程:
            step 1: Plan.validate() + state 初始化 + retry_ctr + router 初始化
                   + project_root 运行时解析
            step 2: while round_id <= max_iter (while 不用 for: retry 不消耗 round_id):
                2a 取消检查
                2b state.current_stage=="" → router.next 初始化 → state.current_stage
                2c 选 round_tasks (plan.get_tasks_by_stage 或 auto_gen)
                2d PRE Guardrail → _handle_guardrail_result
                2e run_round + _apply_outcome_to_state
                2f POST Guardrail → 同上 handler
                2g semantic_evaluator 写回 (仅 critic)
                2h MAJOR 计数更新 (critic)
                2i StageRouter.next + Judge.evaluate + 退出条件
            step 3: 退出块 (GOAL_ACHIEVED / max_iter / unexpected)

        v5.0 设计决策:
            - while 而非 for: retry 不消耗 round_id, max_iter 边界在 step 3 显式判断
            - step 1 集中所有初始化: state 字段、retry_counters、router、project_root
            - step 2 顺序固定: PRE guardrail → run_round → POST guardrail →
              semantic → MAJOR → router.next → judge (前序失败短路后续)
            - 退出条件三层: dec.should_stop (T6) / verdict.should_stop (GOAL_ACHIEVED) /
              dec.next_stage is None (无 next)

        Args:
            cancellation: 可选 CancellationToken

        Returns:
            history 列表 (所有跑过的轮次)

        Raises:
            ConflictError: Plan 文件冲突 (validate 失败)
            AEError(TASK_CANCELLED): 用户取消
        """
        # ===== step 1: 初始化 =====
        assert self.plan is not None  # __post_init__ 保证
        self.plan.validate()  # DAG + 文件隔离
        assert self.judge is not None and self.judge.config is not None
        max_iter = self.judge.config.max_iterations
        # project_root 运行时解析 (B11.1): 优先用 config, fallback cwd
        project_root = self.config.project_root or Path.cwd()
        # state 由 __post_init__ 兜底初始化, 此处复用
        if self._state is None:
            from auto_engineering.engine.state import EngineState
            self._state = EngineState(requirement=self.requirement)
        if self._router is None:
            from auto_engineering.loop.stage_router import StageRouter
            self._router = StageRouter()
        # _retry_counters 已在 __post_init__ 初始化为 {} (per Orchestrator 实例)
        # 兼容外部注入: guardrail_chain / checkpoint_store 从 config 拉
        guardrail_chain = self.config.guardrail_chain

        # ===== step 2: 主循环 =====
        round_id = 0
        while round_id < max_iter:
            round_id += 1

            # 2a. 取消检查
            if cancellation is not None and cancellation.is_cancelled():
                self.verdict = ConvVerdict.stop(
                    level=3,  # 取消走停滞/异常分支
                    reason="用户取消 (CancellationToken)",
                )
                return list(self.history)

            # 2b. state.current_stage=="" → router.next 初始化
            if self._state.current_stage == "":
                decision = self._router.next(
                    current_stage="",
                    verdict="",
                    majors_in_a_row=self._state.majors_in_a_row,
                    total_majors=self._state.total_majors,
                )
                self._state.current_stage = decision.next_stage or ""

            # 2c. 选 round_tasks (按 stage 过滤 — 用 plan.get_tasks_by_stage)
            current_stage = self._state.current_stage or "developer"
            round_tasks = self.plan.get_tasks_by_stage(current_stage)
            if not round_tasks:
                # auto_gen 兜底: 当 stage 没有匹配 task 时, 跑 self.tasks 中 role 匹配的
                # (单 Agent 模式向后兼容: legacy developer task 列表)
                round_tasks = [
                    t for t in self.tasks
                    if (t.role or "developer") == current_stage
                ]
                if not round_tasks and self.tasks:
                    # 完全没有 role 匹配: 全部 task 兜底 (向后兼容旧用例)
                    round_tasks = list(self.tasks)

            # 2d. PRE Guardrail (本子目标 stub — 完整实现见子目标 5)
            if guardrail_chain is not None:
                pre_result = guardrail_chain.check(
                    "pre", current_stage, self._state, project_root
                )
                from auto_engineering.loop.guardrail import _handle_guardrail_result
                action = _handle_guardrail_result(
                    pre_result, current_stage, self._state, self._retry_counters
                )
                if action == "stop":
                    self.verdict = ConvVerdict.stop(
                        level=3,
                        reason=f"PRE guardrail stop: {pre_result.message}",
                    )
                    return list(self.history)
                if action == "retry":
                    # 重试不消耗 round_id (v5.0 §B7.1 step 2 注释)
                    continue

            # 2e. Agent 执行 (本子目标 stub — run_round + outcome → state 见子目标 5)
            round_result = await run_round(
                tasks=round_tasks,
                executor=self.executor,
                ctx=None,
                cancellation=cancellation,
                round_id=round_id,
                gates=self.config.gates,
                project_root=project_root,
            )
            # _apply_outcome_to_state: 按 task_role 分发 outcome.output → state
            from auto_engineering.loop.task_factory import _apply_outcome_to_state
            for outcome in round_result.outcomes:
                _apply_outcome_to_state(self._state, outcome)

            # 2f. POST Guardrail (本子目标 stub — 完整实现见子目标 5)
            if guardrail_chain is not None:
                post_result = guardrail_chain.check(
                    "post", current_stage, self._state, project_root
                )
                from auto_engineering.loop.guardrail import _handle_guardrail_result
                action = _handle_guardrail_result(
                    post_result, current_stage, self._state, self._retry_counters
                )
                if action == "stop":
                    self.verdict = ConvVerdict.stop(
                        level=3,
                        reason=f"POST guardrail stop: {post_result.message}",
                    )
                    return list(self.history)
                if action == "retry":
                    continue

            # 2g. semantic_evaluator 写回 (仅 critic 阶段)
            if current_stage == "critic":
                semantic_satisfied = await self._evaluate_semantic(round_result)
                if round_result.history:
                    round_result.history[0].semantic_satisfied = semantic_satisfied

            self.round_results.append(round_result)
            self.history.extend(round_result.history)

            # 2h. MAJOR 计数更新 (仅 critic 阶段)
            if current_stage == "critic":
                from auto_engineering.loop.stage_router import _update_majors_count
                _update_majors_count(self._state, self._state.verdict)

            # 2i. StageRouter.next + Judge.evaluate + 退出条件
            from auto_engineering.loop.stage_router import StageDecision
            decision = self._router.next(
                current_stage=current_stage,
                verdict=self._state.verdict if current_stage == "critic" else "",
                majors_in_a_row=self._state.majors_in_a_row,
                total_majors=self._state.total_majors,
            )
            # 退出条件 1: dec.should_stop (T6 MAJOR 超限)
            if decision.should_stop:
                self.verdict = ConvVerdict.stop(
                    level=3,
                    reason=decision.stop_reason or "StageRouter stop",
                )
                return list(self.history)
            # 推进 stage + 清旧字段
            if decision.next_stage is not None:
                from auto_engineering.loop.stage_router import _clear_stage_fields
                _clear_stage_fields(self._state, current_stage)
                self._state.current_stage = decision.next_stage
            else:
                # 退出条件 2: critic+APPROVE → Judge 触发 GOAL_ACHIEVED
                verdict = self.judge.evaluate(history=self.history)
                if verdict.should_stop:
                    self.verdict = verdict
                    return list(self.history)
                # 退出条件 3: dec.next_stage is None 且 judge 不 stop → unexpected
                # 兜底: 走 max_iter 退出块
                break

        # ===== step 3: 退出块 (max_iter 硬上限) =====
        self.verdict = ConvVerdict.stop(
            level=4,  # LEVEL_HARD_LIMIT
            reason=f"达到最大轮次 {max_iter} (硬上限)",
        )
        return list(self.history)

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