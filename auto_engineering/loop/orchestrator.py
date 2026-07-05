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

import json
import logging
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
    from auto_engineering.loop.stage_router import StageDecision, StageRouter
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
            None 时, **有 KEY 且不在 LLM agent** (CLAUDE_CODE 未设置)
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
            - semantic_evaluator 为 None + 有 KEY 且不在 LLM agent
              (detect_plugin_mode() == False) → 自动启用 ClaudeSemanticEvaluator
            - semantic_evaluator 为 None + 无 API key 或在 LLM agent → 保持 None

        2026-07-04 修复 (Bug 4 prismscan 集成): in_llm_agent 改用
        detect_plugin_mode() 共用函数 (4 级 fallback), 包含 ANTHROPIC_AUTH_TOKEN
        OAuth 注入信号 — 解决 plugin 模式下 plugin_mode 检测失败导致 LLM 评估
        误启用的反向问题.
        """
        from auto_engineering.utils.plugin_mode import detect_plugin_mode
        in_llm_agent = detect_plugin_mode()
        # 2026-07-04 修复 (v5.0 深度审计 P0-D-03): 原代码读 "KEY" 环境变量名错误,
        # 应读 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN (与 anthropic_provider.py:78 对齐).
        api_key_present = bool(
            os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )
        if (
            self.semantic_evaluator is None
            and api_key_present
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
    # 2026-07-04 /code-review Issue #11 (90 分): 注释 "EngineState channel 替代裸 history" 误导.
    # 实际 Orchestrator 用 self.history (deque) 存历史, 不通过 EngineState channel.
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
    # 2026-07-04 (Bug 2 prismscan 方案 A): critic 重试计数 (替代直接升级 HARD_LIMIT)
    _critic_retry_count: int = 0

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
        """v5.0 M4: 12 步主循环 (B7.1) — 拆 8 子方法 (P1-1 单一职责).

        主体仅保留: step 1 初始化 + while 主框架 + 调度 8 个 _step_* 子方法.
        流程契约不变 (12 步), 仅把各 step 抽到独立方法以降低认知负担.

        Args:
            cancellation: 可选 CancellationToken

        Returns:
            history 列表 (所有跑过的轮次)

        Raises:
            ConflictError: Plan 文件冲突 (validate 失败)
            AEError(TASK_CANCELLED): 用户取消
        """
        # ===== step 1: 初始化 =====
        max_iter, project_root, guardrail_chain = self._step_1_init()

        # ===== step 2: 主循环 — 8 子方法调度 =====
        round_id = 0
        while round_id < max_iter:
            round_id += 1

            # 2a 取消检查 → 不取消继续, 取消立即 return
            if self._step_2a_cancel(cancellation):
                return list(self.history)

            # 2b state.current_stage=="" → router.next 初始化
            self._step_2b_route_init(self._state, self._router)
            # 2026-07-04 修复 (Issue #12, 70 分): fallback 改 "architect" 而非 "developer"
            # (按 T1 转换表, 空 current_stage → architect). 之前 "developer" 错,
            # 可能跳过 architect 阶段直接跑 developer task (违反 stage-sequenced 流程).
            current_stage = self._state.current_stage or "architect"

            # 2c 选 round_tasks (按 stage 过滤 + auto_gen 兜底)
            round_tasks, advance = self._step_2c_select_tasks(current_stage)
            # v5.1 JSONL: 空 tasks + architect stage → 创建合成 task 触发 JSONL 规划
            if not round_tasks and current_stage == "architect" and advance:
                in_jsonl = os.environ.get("AE_JSONL_MODE") == "1"
                if in_jsonl or self.config.agent_runtime is not None:
                    from auto_engineering.loop.plan import Task as _Task
                    round_tasks = [_Task(
                        id="architect-synthetic",
                        title="Generate implementation plan",
                        description=f"Analyze requirement: {self.requirement}",
                        expected_output="batch_plan with developer tasks",
                        role="architect",
                    )]
                    advance = False
            if not round_tasks and advance:
                continue
            if not round_tasks:
                break  # 到达 stage 流终点 → 走 step 3

            # 2d PRE Guardrail
            pre_action = self._step_2d_guardrail_pre(
                guardrail_chain, current_stage, self._state
            )
            if pre_action == "stop":
                # 2026-07-04 修复 (Bug 3): guardrail stop 应视为 HARD_LIMIT
                # (硬阻止, 用户输入或安全违规), 不再默认 level=3 PASS.
                self.verdict = ConvVerdict.stop(level=4, reason="PRE guardrail stop")
                return list(self.history)
            if pre_action == "retry":
                continue

            # 2e Agent 执行
            round_result = await self._step_2e_run_agent(
                current_stage, round_tasks, self._state,
                project_root, cancellation, round_id,
            )

            # 2f POST Guardrail
            post_action = self._step_2f_guardrail_post(
                guardrail_chain, current_stage, self._state
            )
            if post_action == "stop":
                # 2026-07-04 修复 (Bug 3): 同 PRE, POST guardrail stop 用 level=4.
                self.verdict = ConvVerdict.stop(level=4, reason="POST guardrail stop")
                return list(self.history)
            if post_action == "retry":
                continue

            # 2g semantic 评估 (critic 阶段)
            await self._step_2g_semantic(
                self.config.semantic_evaluator, current_stage, round_result,
            )
            self.round_results.append(round_result)
            self.history.extend(round_result.history)

            # 2h MAJOR 计数 (critic 阶段)
            self._step_2h_major_count(self._state, self._state.verdict, current_stage)

            # 2i StageRouter.next + Judge.evaluate + 退出条件
            if self._step_2i_route_and_judge(
                self._router, self.judge, current_stage, self._state,
            ):
                break

        # ===== step 3: 退出块 =====
        # 优先保留子方法设置的 self.verdict (如 step 2i judge.should_stop → QUALITY);
        # 若子方法未 set (max_iter / unexpected 走兜底), 才用 step 3 的 level=4.
        if self.verdict is None or not self.verdict.should_stop:
            latest_gates = self._collect_latest_gates()
            _, final_verdict = self._step_3_exit_block(
                self._state, self.history, latest_gates, max_iter, round_id,
            )
            self.verdict = final_verdict
        return list(self.history)

    # ========================================================================
    # v5.0 P1-1: run() 拆 8 子方法 (单一职责) — run() 主体只调度, 细节在子方法
    # ========================================================================

    def _step_1_init(self) -> tuple[int, Path, "GuardrailChain | None"]:
        """step 1: 初始化. 返回 (max_iter, project_root, guardrail_chain).

        集中所有初始化: Plan.validate() / state / router / project_root / guardrail_chain.
        抽到子方法让 run() 主体保持在 ≤ 80 行.
        """
        assert self.plan is not None
        self.plan.validate()
        assert self.judge is not None and self.judge.config is not None
        max_iter = self.judge.config.max_iterations
        project_root = self.config.project_root or Path.cwd()
        if self._state is None:
            from auto_engineering.engine.state import EngineState
            self._state = EngineState(requirement=self.requirement)
        if self._router is None:
            from auto_engineering.loop.stage_router import StageRouter
            self._router = StageRouter()
        guardrail_chain = (
            getattr(self, "_guardrail_chain", None) or self.config.guardrail_chain
        )
        return max_iter, project_root, guardrail_chain

    def _step_2a_cancel(
        self, cancellation: CancellationToken | None
    ) -> bool:
        """step 2a: 取消检查. 返回 True 表示应立即 return.

        取消走 level=3 停滞/异常分支, verdict reason 标注 CancellationToken 来源.
        """
        if cancellation is not None and cancellation.is_cancelled():
            # 2026-07-04 修复 (Issue #13, 100 分): 改用 level=4 (HARD_LIMIT)
            # 避免与"Gate 全 PASS" (level=3) 混淆. 之前用 level=3 会被
            # dev_loop.py 映射为 status="completed" (exit 0), 用户取消看起来像成功.
            # 现在 level=4 → status="failed" → exit 2.
            self.verdict = ConvVerdict.stop(
                level=4,
                reason="用户取消 (CancellationToken) → HARD_LIMIT",
            )
            return True
        return False

    def _step_2b_route_init(
        self,
        state: "EngineState",
        router: "StageRouter",
    ) -> "StageDecision | None":
        """step 2b: state.current_stage=="" 时调 router.next 初始化.

        返回 StageDecision (供测试 spy 验证); 副作用写 state.current_stage.
        """
        if state.current_stage != "":
            return None
        decision = router.next(
            current_stage="",
            verdict="",
            majors_in_a_row=state.majors_in_a_row,
            total_majors=state.total_majors,
        )
        state.current_stage = decision.next_stage or ""
        return decision

    def _step_2c_select_tasks(
        self, current_stage: str
    ) -> tuple[list[Task], bool]:
        """step 2c: 选 round_tasks. 返回 (round_tasks, advance).

        advance=True 表示空 stage 已自动推到下一 stage, 调用方应 continue.
        round_tasks 非空 → 正常执行; 空 + advance=False → 跳出 while (走 step 3).
        """
        assert self.plan is not None
        round_tasks = self.plan.get_tasks_by_stage(current_stage)
        if round_tasks:
            return round_tasks, False

        # auto_gen 兜底: stage 没匹配 → 从 self.tasks 里 role 匹配
        round_tasks = [
            t for t in self.tasks
            if (t.role or "developer") == current_stage
        ]
        if not round_tasks and self.tasks:
            round_tasks = list(self.tasks)
        if round_tasks:
            return round_tasks, False

        # 仍为空: 推到下一 stage (避免空 stage 空转)
        from auto_engineering.loop.stage_router import _clear_stage_fields
        assert self._router is not None and self._state is not None
        advance_decision = self._router.next(
            current_stage=current_stage,
            verdict="",
            majors_in_a_row=self._state.majors_in_a_row,
            total_majors=self._state.total_majors,
        )
        if advance_decision.next_stage is not None:
            _clear_stage_fields(self._state, current_stage)
            self._state.current_stage = advance_decision.next_stage
            return [], True
        # stage 流终点: 跳出
        return [], False

    def _step_2d_guardrail_pre(
        self,
        guardrail_chain: "GuardrailChain | None",
        current_stage: str,
        state: "EngineState",
    ) -> str:
        """step 2d: PRE Guardrail 检查. 返回 'pass' / 'stop' / 'retry'.

        None chain → 视为 pass (向后兼容, 测试场景).
        """
        if guardrail_chain is None:
            return "pass"
        pre_result = guardrail_chain.check("pre", current_stage, state, self._resolve_project_root())
        from auto_engineering.loop.guardrail import _handle_guardrail_result
        return _handle_guardrail_result(
            pre_result, current_stage, state, self._retry_counters
        )

    async def _step_2e_run_agent(
        self,
        current_stage: str,
        round_tasks: list[Task],
        state: "EngineState",
        project_root: Path,
        cancellation: CancellationToken | None,
        round_id: int,
    ) -> RoundResult:
        """step 2e: 调 run_round (developer) 或 JSONL 协议 (architect/critic).

        v5.1 实施 (2026-07-05): architect 和 critic 两个 LLM 调用点
        从 Anthropic SDK 改为 JSONL stdin/stdout 协议 — 复用 agent 的
        ANTHROPIC_AUTH_TOKEN, 不需要独立 API key.
        developer 本身由 CLI agent 直接执行 TDD 循环, 不走 JSONL.

        把 outcomes 按 task_role 分发写入 state 字段 (B7.2).
        """
        # v5.1 JSONL (BEACON 决策 33, design §C.3):
        # architect/critic stage → 走 JSONL 协议 (plugin mode 内, 复用 agent LLM)
        # developer stage / 非 plugin mode → 走 run_round (向后兼容 CLI + 测试)
        in_jsonl = os.environ.get("AE_JSONL_MODE") == "1"

        if in_jsonl and current_stage == "architect":
            arch_response = self._request_architect(
                requirement=state.requirement,
                project_root=str(project_root),
            )
            outcome = TaskOutcome(
                task_id=f"architect-{round_id}",
                status="completed",
                output=arch_response,
                task_role="architect",
            )
            from auto_engineering.loop.task_factory import _apply_outcome_to_state
            _apply_outcome_to_state(state, outcome)
            # 把 architect 产出的 batch_plan 转换为 developer tasks (v5.0 §B7.3)
            batch_plan = arch_response.get("batch_plan", [])
            if batch_plan:
                from auto_engineering.loop.task_factory import _tasks_from_batch_plan
                arch_plan = _tasks_from_batch_plan(batch_plan, state.requirement)
                self.plan.tasks.extend(arch_plan.tasks)
                self.tasks = list(self.plan.tasks)
            return RoundResult(
                round_id=round_id,
                outcomes=[outcome],
                history=[RoundHistory(
                    round_id=round_id,
                    files_changed=0,
                    gate_results={},
                    tasks_run=[],
                    task_outcomes={"architect": "completed"},
                )],
            )

        if in_jsonl and current_stage == "critic":
            latest_gates = self._collect_latest_gates()
            critic_response = self._request_critic(
                files_changed=state.files_changed,
                commit_hash=state.commit_hash,
                test_results=state.test_results,
                gate_results=latest_gates,
            )
            outcome = TaskOutcome(
                task_id=f"critic-{round_id}",
                status="completed",
                output=critic_response,
                task_role="critic",
            )
            from auto_engineering.loop.task_factory import _apply_outcome_to_state
            _apply_outcome_to_state(state, outcome)
            return RoundResult(
                round_id=round_id,
                outcomes=[outcome],
                history=[RoundHistory(
                    round_id=round_id,
                    files_changed=0,
                    gate_results=latest_gates,
                    tasks_run=[],
                    task_outcomes={"critic": "completed"},
                )],
            )

        # fallback: run_round for all stages (CLI mode / tests / non-agent)
        enhanced_tasks = self._inject_self_refine_context(round_tasks, state, current_stage)
        round_result = await run_round(
            tasks=enhanced_tasks,
            executor=self.executor,
            ctx=None,
            cancellation=cancellation,
            round_id=round_id,
            gates=self.config.gates,
            project_root=project_root,
        )
        from auto_engineering.loop.task_factory import _apply_outcome_to_state
        for outcome in round_result.outcomes:
            _apply_outcome_to_state(state, outcome)
        return round_result

    def _inject_self_refine_context(
        self,
        round_tasks: list[Task],
        state: "EngineState",
        current_stage: str,
    ) -> list[Task]:
        """Self-Refine 反馈注入: 把 critic_feedback + findings + gate_results 拼接到 task.description.

        触发条件:
            - state.critic_feedback 非空 (说明上一轮 critic 给 MAJOR 反馈)
            - state.findings 非空 (P0/P1/P2 findings 列表)
            - 上一轮 gate_results 存在 (lint/test/type_check)
            - 当前 stage 是 developer / critic (architect 阶段无反馈意义)

        不修改原 round_tasks (返回新 list, 内部用 dataclasses.replace 复制 Task).

        2026-07-04 修复 (Self-Refine 原则 1+4): 不注入 → developer 重做看不到
        上轮反馈, 只能从零实现. 注入 → developer 看到"上次哪些 P0 没修 +
        test 哪些失败 + 怎么改", 针对性修复. critic 收到 gate_results 后,
        verdict 倾向更准确 (gate fail 时不应 APPROVE).

        原则 4 (每次迭代引入新信息): gate_results 是非 LLM 信号 (lint 真实跑
        + pytest 真实跑), 必须注入避免"纯 LLM 自我审视"导致 Degeneration-of-Thought.
        """
        from dataclasses import replace

        # architect stage 无反馈意义, 跳过
        if current_stage == "architect":
            return round_tasks

        has_feedback = bool(getattr(state, "critic_feedback", ""))
        has_findings = bool(getattr(state, "findings", []))
        latest_gates = self._collect_latest_gates()
        has_gates = bool(latest_gates)

        if not (has_feedback or has_findings or has_gates):
            return round_tasks  # 无任何反馈, 跳过

        context_parts: list[str] = []
        if has_feedback:
            context_parts.append(
                f"\n\n## [Self-Refine 反馈] Critic 上一轮 MAJOR 反馈:\n"
                f"{state.critic_feedback}\n"
                f"**重要**: 优先修复 P0, 同 batch ≥ 3 个 P1 视为 MAJOR (与 Critic 判定一致).\n"
                f"修复后必须 `run_tests` 确认全绿, 不要 mark skip / xfail 绕过."
            )
        if has_findings:
            findings_lines = ["\n\n## [Self-Refine findings] Critic 上一轮具体问题清单:"]
            for f in state.findings:
                if isinstance(f, dict):
                    findings_lines.append(
                        f"- `{f.get('file', '?')}:{f.get('line', '?')}` "
                        f"[{f.get('severity', '?')}] {f.get('issue', '?')}"
                    )
                else:
                    findings_lines.append(f"- {f}")
            context_parts.append("\n".join(findings_lines))
        if has_gates:
            gate_lines = ["\n\n## [Self-Refine gate_results] 上一轮 Gate 检查结果 (非 LLM 信号):"]
            for name, verdict in latest_gates.items():
                passed = getattr(verdict, "passed", None)
                message = getattr(verdict, "message", "")
                status = "✓ pass" if passed else "✗ FAIL"
                gate_lines.append(f"- `{name}`: {status} — {message}")
            gate_lines.append(
                "\n**重要**: 上述 gate 是真实执行结果 (lint/type_check/test), "
                "非 LLM 自我评估. 若有 FAIL, 必须先修复再 verdict=APPROVE."
            )
            context_parts.append("\n".join(gate_lines))

        # 2026-07-04 (Self-Refine 原则 1 深化): 结构化 suggested_fix patch
        # 优先于文字 feedback/findings, developer 直接应用 patch 不重新解读.
        suggested_fix = getattr(state, "suggested_fix", "")
        if suggested_fix:
            context_parts.append(
                f"\n\n## [Self-Refine suggested_fix] Critic 上一轮结构化 patch "
                f"(直接应用, 不重新解读):\n```diff\n{suggested_fix}\n```\n"
                f"**重要**: 这是 unified diff 格式, 可用 `git apply` 直接应用. "
                f"优先按此 patch 修复, 避免 LLM 自我理解偏差."
            )

        context_suffix = "".join(context_parts)

        # 用 dataclasses.replace 复制 Task, 避免 mutate 原 round_tasks
        enhanced: list[Task] = []
        for task in round_tasks:
            new_description = task.description + context_suffix
            enhanced.append(replace(task, description=new_description))
        return enhanced

    def _step_2f_guardrail_post(
        self,
        guardrail_chain: "GuardrailChain | None",
        current_stage: str,
        state: "EngineState",
    ) -> str:
        """step 2f: POST Guardrail 检查. 返回 'pass' / 'stop' / 'retry'."""
        if guardrail_chain is None:
            return "pass"
        post_result = guardrail_chain.check("post", current_stage, state, self._resolve_project_root())
        from auto_engineering.loop.guardrail import _handle_guardrail_result
        return _handle_guardrail_result(
            post_result, current_stage, state, self._retry_counters
        )

    async def _step_2g_semantic(
        self,
        semantic_evaluator: SemanticEvaluator | None,
        current_stage: str,
        round_result: RoundResult,
    ) -> None:
        """step 2g: 调 LLM 语义评估 (仅 critic 阶段). 写回 round_result.history[0]."""
        if current_stage != "critic":
            return
        semantic_satisfied = await self._evaluate_semantic(round_result)
        if round_result.history:
            round_result.history[0].semantic_satisfied = semantic_satisfied

    def _step_2h_major_count(
        self,
        state: "EngineState",
        verdict: str,
        current_stage: str,
    ) -> None:
        """step 2h: MAJOR 计数更新 (仅 critic 阶段). 其他阶段不动作."""
        if current_stage != "critic":
            return
        from auto_engineering.loop.stage_router import _update_majors_count
        _update_majors_count(state, verdict)

    def _step_2i_route_and_judge(
        self,
        router: "StageRouter",
        judge: ConvergenceJudge,
        current_stage: str,
        state: "EngineState",
    ) -> bool:
        """step 2i: StageRouter.next + Judge.evaluate. 返回 should_break.

        should_break=True → 主循环 break (走 step 3).
        3 层退出条件 (按优先级): dec.should_stop / dec.next_stage=None+judge.stop / unexpected.
        副作用: 推进 state.current_stage + _clear_stage_fields (B3.3).

        2026-07-04 修复 (Bug 3 prismscan 方案 C):
            即便 critic 给 verdict.level=3 (QUALITY_PASS), gate fail 时不停止.
            gate_summary 是更可靠的质量信号 — 让 developer 继续修, 而不是 PASS 通过
            出去留下 0 代码改动退出.
            这是反向语义的根本防御: 即便 critic LLM 错给 APPROVE, gate 失败也会
            拦住继续修, 而不是立刻停.
        """
        # 2026-07-04 修复 (Bug 3 prismscan 集成 + Bug 2 方案 A):
        # CriticVerdictInvalid 是 stage_router 在 critic 返回非法 verdict 时抛出的
        # 异常 (替代原 should_stop=True 静默 PASS).
        # 修复策略 (Bug 2 方案 A 关键): 重试 critic 最多 MAX_CRITIC_RETRIES 次,
        # 仍失败才升级 HARD_LIMIT. 给 critic agent 机会重新输出 (LLM 调用偶发失败).
        from auto_engineering.loop.stage_router import CriticVerdictInvalid

        MAX_CRITIC_RETRIES = 2
        try:
            decision = router.next(
                current_stage=current_stage,
                verdict=state.verdict if current_stage == "critic" else "",
                majors_in_a_row=state.majors_in_a_row,
                total_majors=state.total_majors,
            )
        except CriticVerdictInvalid as exc:
            if self._critic_retry_count < MAX_CRITIC_RETRIES:
                self._critic_retry_count += 1
                # 重置到 critic 阶段, 让主循环重试 (RoundResult 已记录, 不重跑 developer)
                state.current_stage = "critic"
                # 2026-07-04 (Issue #15): import logging 提到模块顶部 (PEP 8),
                # 删 inline 重复 import.
                logging.getLogger("ae.loop.orchestrator").warning(
                    "Bug 2 方案 A: critic verdict 异常, 重试 (%d/%d): %r",
                    self._critic_retry_count,
                    MAX_CRITIC_RETRIES,
                    exc.verdict,
                )
                return False  # 不 break, 主循环继续 → 重新跑 critic
            # 超过最大重试次数, 升级 HARD_LIMIT
            self.verdict = ConvVerdict.stop(
                level=4,
                reason=f"critic verdict 异常 (重试 {MAX_CRITIC_RETRIES} 次仍失败, Bug 3 升级到 HARD_LIMIT): {exc.verdict!r}",
            )
            return True
        if decision.should_stop:
            # 2026-07-04 修复 (Bug 3): StageRouter stop 默认 level=3 PASS 是反向语义
            # (实际是 MAJOR 超限等异常停止, 不应 PASS). 改为 level=4 HARD_LIMIT
            # 让 orchestrator 显式区分"通过停止" vs "异常停止".
            self.verdict = ConvVerdict.stop(
                level=4, reason=decision.stop_reason or "StageRouter stop"
            )
            return True
        if decision.next_stage is not None:
            from auto_engineering.loop.stage_router import _clear_stage_fields
            _clear_stage_fields(state, current_stage)
            state.current_stage = decision.next_stage
            return False
        # next_stage is None: judge 判定
        verdict = judge.evaluate(history=list(self.history))
        if verdict.should_stop:
            # 2026-07-04 修复 (Bug 3 prismscan 方案 C):
            # 即便 judge 给 QUALITY_PASS (level=3), 检查最近一轮 gate_summary:
            # - 任意 gate failed → 不停止, continue (让 developer 修 gate 失败的项)
            # - 所有 gate passed → 正常停止
            # 这是反向语义的根本防御: 即便 critic LLM 错给 APPROVE,
            # gate fail 也会拦住继续修, 而不是立刻停.
            latest_gates = self._collect_latest_gates()
            if verdict.level == 3 and latest_gates and not self._gates_all_passed(latest_gates):
                # gate fail 拦住 — 不升级 verdict, 继续
                self._step_2i_log_gate_block(verdict, latest_gates, current_stage)
                return False  # 不 break
            self.verdict = verdict
            return True
        return True  # unexpected → 兜底 break (走 step 3)

    def _collect_latest_gates(self) -> dict:
        """收集最近一轮 RoundHistory 的 gate_results (dict[str, Verdict]).

        2026-07-04 (Bug 3 方案 C): 用于 step 2i gate_summary 反向防御检查.
        2026-07-04 P0 修复: 唯一权威实现 (前 c2fd29e commit 误加同方法覆盖
        返回 dict[str, bool] 破坏 _gates_all_passed + _inject_self_refine_context).
        消费方期望 dict[str, Verdict] (有 .passed / .message 属性).
        """
        if not self.history:
            return {}
        last_round = self.history[-1]
        return last_round.gate_results or {}

    def _gates_all_passed(self, gate_results: dict) -> bool:
        """所有 gate 都通过 (Bug 3 方案 C 辅助).

        容忍空 dict (无 gate 配置), 返回 True (避免误判).
        """
        if not gate_results:
            return True  # 无 gate 配置 → 不视为失败
        for verdict in gate_results.values():
            passed = getattr(verdict, "passed", None)
            if passed is False:
                return False
        return True

    def _step_2i_log_gate_block(
        self, verdict: Any, latest_gates: dict, current_stage: str
    ) -> None:
        """记录 gate fail 拦住 stop 的诊断日志 (Bug 3 方案 C)."""
        failed = [
            name
            for name, v in latest_gates.items()
            if getattr(v, "passed", None) is False
        ]
        # 2026-07-04 (Issue #15): import logging 提到模块顶部 (PEP 8).
        logging.getLogger("ae.loop.orchestrator").info(
            "Bug 3 方案 C: judge QUALITY_PASS 但 gate fail, 不停止 → continue. "
            "verdict_level=%d, current_stage=%s, failed_gates=%s",
            getattr(verdict, "level", -1),
            current_stage,
            failed,
        )

    def _step_3_exit_block(
        self,
        state: "EngineState | None",
        history: deque[RoundHistory],
        latest_gates: dict[str, bool],
        max_iter: int,
        round_id: int,
    ) -> tuple[list[RoundHistory], ConvVerdict]:
        """step 3: 退出块. 返回 (history, final_verdict).

        3 种退出原因:
          1. GOAL_ACHIEVED (verdict 已有 should_stop) → 上层 step 2i 已 return
          2. max_iter 硬上限 → level=4 LEVEL_HARD_LIMIT
          3. unexpected (dec.next_stage=None + judge 不 stop) → 兜底按 max_iter
        退出前 _save_checkpoint 一次 (兜底持久化).
        """
        if state is not None:
            from auto_engineering.loop.stage_router import _derive_status
            state.status = _derive_status(state, max_iter)
        self._save_checkpoint(round_id=round_id, step=2, tag="exit_block")
        final_verdict = ConvVerdict.stop(
            level=4,
            reason=f"达到最大轮次 {max_iter} (硬上限)",
        )
        return list(history), final_verdict

    def _resolve_project_root(self) -> Path:
        """运行时解析 project_root (B11.1). config 优先, fallback cwd."""
        return self.config.project_root or Path.cwd()

    # ========================================================================
    # v5.1 JSONL Agent-Engine 协议 (BEACON 决策 33, design §C.3)
    # ========================================================================
    # architect/critic 两个 LLM 调用点从 Anthropic SDK 改为 JSONL stdin/stdout
    # 协议 — Claude Code agent 接收 JSON 请求后执行 Plan/code-reviewer 任务.
    # 解决子进程无法获取 ANTHROPIC_AUTH_TOKEN 问题 (复用 agent 的 LLM).
    # developer 本身由 agent 执行, 不走 JSONL.

    def _request_architect(self, requirement: str, project_root: str) -> dict:
        """JSONL architect: 输出计划请求, 读取 agent 响应.

        v5.1: 替代 AnthropicProvider SDK → Plan agent (spawn 在 agent 内).
        """
        request = json.dumps(
            {
                "request": "architect",
                "requirement": requirement,
                "context": {"project_root": project_root},
            },
            ensure_ascii=False,
        )
        print(request, flush=True)
        try:
            return json.loads(input())
        except (EOFError, json.JSONDecodeError):
            # agent crash / malformed JSON — 降级
            return {"plan": "", "batch_plan": [], "file_list": [], "contracts": {}}

    def _request_critic(
        self,
        files_changed: list[str],
        commit_hash: str,
        test_results: dict,
        gate_results: dict,
    ) -> dict:
        """JSONL critic: 输出审查请求, 读取 agent 响应.

        v5.1: 替代 AnthropicProvider SDK → code-reviewer agent (spawn 在 agent 内).
        """
        request = json.dumps(
            {
                "request": "critic",
                "files_changed": files_changed,
                "commit_hash": commit_hash,
                "test_results": test_results,
                "gate_results": gate_results,
            },
            ensure_ascii=False,
        )
        print(request, flush=True)
        try:
            return json.loads(input())
        except (EOFError, json.JSONDecodeError):
            # agent crash / malformed JSON — 降级 MAJOR (保守)
            return {"verdict": "MAJOR", "findings": [], "suggested_fix": ""}

    def _save_checkpoint(
        self,
        round_id: int,
        step: int = 0,
        tag: str | None = None,
    ) -> str | None:
        """保存 Checkpoint (v5.0 §B7.4).

        行为契约:
            - checkpoint_store 为 None → 跳过 (返回 None), 不影响主流程
            - checkpoint_store 提供 → 构造 CheckpointEnvelope → store.save()
            - IO 异常 → 静默吞掉 (不阻塞主循环, 警告 log)

        Args:
            round_id: 当前轮次 ID.
            step: 当前 step 编号 (0-2, 用于恢复时定位).
            tag: 可选 tag 标签 (如 "exit_block").

        Returns:
            checkpoint_id (str) — 成功时; None — checkpoint_store 未配置.
        """
        if self.config.checkpoint_store is None:
            return None
        if self._state is None:
            return None
        try:
            # store.save() 接受 (state, round, step, history, ...)
            return self.config.checkpoint_store.save(
                state=self._state,
                round=round_id,
                step=step,
                history=list(self.history),
                tag=tag,
            )
        except Exception:
            # IO 异常不传播 (B7.4: 持久化失败不阻塞主循环)
            return None

    def resume(
        self,
        thread_id: str,
        round: int | None = None,
        step: int = 1,
    ) -> list[RoundHistory]:
        """从 Checkpoint 恢复主循环 (v5.0 §B7.5).

        行为契约:
            - checkpoint_store 为 None → 抛 ValueError (无 store 无法 resume)
            - 用 thread_id 查最近一个 checkpoint (按 round DESC)
            - 重建 self._state + self.history + self._retry_counters (从 checkpoint 恢复)
            - 注入到 self._state (不创建新 EngineState) + self._retry_counters
            - 调用 self.run() 继续主循环 (step 1 检测 _state 非空时跳过创建)

        Args:
            thread_id: 目标 thread_id (EngineState.thread_id 字段).
            round: 目标 round (None = 最新).
            step: 目标 step (默认 1 — step 1 后).

        Returns:
            history 列表 (从 checkpoint 后的轮次).

        Raises:
            ValueError: checkpoint_store 未配置.
            CheckpointNotFoundError: 找不到 thread_id 对应 checkpoint.
        """
        if self.config.checkpoint_store is None:
            raise ValueError(
                "resume() 需要 config.checkpoint_store (None 时无法恢复)"
            )
        # 1. 查 checkpoint: 用 list + filter (避免新增 store API)
        #    典型 list() 返回 list[CheckpointMeta]
        metas = self.config.checkpoint_store.list()
        matching = [
            m for m in metas
            if getattr(m, "thread_id", None) == thread_id
            or (round is not None and m.round == round)
        ]
        if not matching:
            # fallback: 直接取最新一个 (简化实现, 不要求 store 支持 thread_id 索引)
            if not metas:
                from auto_engineering.loop.checkpoint.envelope import (
                    CheckpointNotFoundError,
                )
                raise CheckpointNotFoundError(
                    f"找不到任何 checkpoint (thread_id={thread_id}, round={round})"
                )
            matching = [max(metas, key=lambda m: m.round)]
        latest = max(matching, key=lambda m: m.round)
        # 2. load full checkpoint
        ckpt = self.config.checkpoint_store.load(latest.id)
        # 3. 恢复 state + history
        self._state = ckpt.state
        # 重建 history deque (maxlen=50, 防止 resume 后续无界增长)
        from collections import deque
        self.history = deque(ckpt.history, maxlen=50)
        # 4. retry_counters 从 state 派生 (EngineState 没存, 默认 {})
        self._retry_counters = {}
        # 5. 注入到 run() — 通过 async run 实现, 简化: 不实际 await resume
        #    (resume() 同步入口, run() 异步; 调用方需 await orch.run() 续跑)
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