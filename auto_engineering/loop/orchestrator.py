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
        2d PRE Guardrail → handle_guardrail_result
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
      restore_from_checkpoint().
    - v5.4: JSONL 协议已移除 (BEACON 决策 33/34), 所有 stage 统一走 run_round + AgentRuntime 路径.
"""

from __future__ import annotations

import logging
import os
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from auto_engineering.agents.schema import derive_output_schema
from auto_engineering.engine.state import EngineState
from auto_engineering.gates.base import Gate
from auto_engineering.loop.checkpoint.manager import CheckpointManager
from auto_engineering.loop.convergence import (
    ConvergenceConfig,
    ConvergenceJudge,
    RoundHistory,
)
from auto_engineering.loop.convergence import (
    ConvergenceVerdict,
)
from auto_engineering.loop.guardrail_facade import GuardrailFacade
from auto_engineering.loop.convergence_facade import all_gates_passed, evaluate as _evaluate_convergence
from auto_engineering.utils.git import capture_head
from auto_engineering.loop.plan import Plan, Task
from auto_engineering.loop.round import (
    RoundResult,
    TaskExecutor,
    TaskOutcome,
    run_round,
)

from auto_engineering.loop.semantic_evaluator import (
    ClaudeSemanticEvaluator,
    SemanticEvaluator,
)
from auto_engineering.loop.stage_router import (
    CriticVerdictInvalid,
    StageRouter,
    clear_stage_fields,
    update_majors_count,
)

if TYPE_CHECKING:
    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.guardrail import GuardrailChain
    from auto_engineering.loop.stage_router import StageDecision
from auto_engineering.loop.task_factory import apply_outcome_to_state, tasks_from_batch_plan
from auto_engineering.runtime.cancellation import CancellationToken
from auto_engineering.runtime.context import TaskContext
from auto_engineering.runtime.runtime import AgentRuntime
from auto_engineering.runtime.task import Task as RuntimeTask
from auto_engineering.utils.plugin_mode import detect_plugin_mode

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
    semantic_evaluator: SemanticEvaluator | None = None  # None="auto"(默认) 或实例(显式). False=强制禁用
    project_root: Path | None = None
    agent_runtime: AgentRuntime | None = None  # P1.4 — None = 旧行为 (用 executor)
    # v5.5 P2-7: 可注入 plugin_mode_detector 供测试 mock (默认 detect_plugin_mode)
    plugin_mode_detector: Callable[[], bool] | None = None
    # v5.0 M4: 3 个新字段 (B2.1)
    checkpoint_store: "SQLiteCheckpointStore | None" = None
    guardrail_chain: "GuardrailChain | None" = None
    stage_router: "StageRouter | None" = None

    @staticmethod
    def _detect_api_key() -> bool:
        """v5.4 审计 P2-12: 从 __post_init__ 提取 env var 读取为可测试静态方法."""
        return bool(
            os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )

    def __post_init__(self) -> None:
        """v2.3 Phase J (P1.6): 默认启用 ClaudeSemanticEvaluator (有 API key 时).

        行为契约 (v5.5 audit P0-7 改进):
            - semantic_evaluator 已是用户显式传入 (非 None/非 False) → 不覆盖
            - semantic_evaluator 为 False → 强制禁用 (用户显式 opt-out)
            - semantic_evaluator 为 None (默认) + 有 KEY 且不在 LLM agent → 自动启用
            - semantic_evaluator 为 None + 无 API key 或在 LLM agent → 保持 None

        2026-07-04 修复 (Bug 4 prismscan 集成): in_llm_agent 改用
        detect_plugin_mode() 共用函数 (4 级 fallback), 包含 ANTHROPIC_AUTH_TOKEN
        OAuth 注入信号 — 解决 plugin 模式下 plugin_mode 检测失败导致 LLM 评估
        误启用的反向问题.
        """
        # v5.5 audit P0-7: False = 显式禁用
        if self.semantic_evaluator is False:
            self.semantic_evaluator = None
            return

        detector = self.plugin_mode_detector or detect_plugin_mode
        in_llm_agent = detector()
        api_key_present = self._detect_api_key()
        if (
            self.semantic_evaluator is None
            and api_key_present
            and not in_llm_agent
        ):
            logging.getLogger(__name__).info(
                "auto-enabling ClaudeSemanticEvaluator (API key detected)"
            )
            self.semantic_evaluator = ClaudeSemanticEvaluator()
        elif self.semantic_evaluator is None:
            logging.getLogger(__name__).debug(
                "semantic_evaluator=None, API key present=%s, in_llm_agent=%s",
                api_key_present, in_llm_agent,
            )


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
    executor: TaskExecutor | None
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
    verdict: ConvergenceVerdict | None = None
    # v5.0 M4 (B2.1): 内部状态 — 由 __post_init__ 初始化, 默认占位.
    # _state: EngineState 17 字段 Channel 容器 (v5.0 §B1.1)
    # _router: StageRouter 引用 (从 config 拉, 避免每个 step 都访问 config)
    _state: "EngineState | None" = None
    _channel_versions: dict[str, int] = field(default_factory=dict)
    _channel_hashes: dict[str, int] = field(default_factory=dict)
    _router: "StageRouter | None" = None
    _checkpoint_mgr: "CheckpointManager | None" = None
    _guardrail_facade: "GuardrailFacade | None" = None
    # 2026-07-04 (Bug 2 prismscan 方案 A): critic 重试计数 (替代直接升级 HARD_LIMIT)
    _critic_retry_count: int = 0

    def __post_init__(self) -> None:
        """初始化 Plan + Judge + 选 executor (agent_runtime 优先).

        v2.3 Phase E (P1.1): 不再在 Orchestrator 自身存 max_rounds 字段,
        主循环从 self.judge.config.max_iterations 读 (单一来源).

        v2.3 Phase H (P1.4): 若 config.agent_runtime 提供, 用 _build_runtime_executor
        覆盖 self.executor. 借鉴 AutoGen GroupChat agent_selector 路由模式.
        向后兼容: agent_runtime=None → 保留构造参数 executor (旧行为).

        v5.0 M4 (B2.1): 初始化 _state (EngineState Channel 容器)
        + _router (从 config 拉, 简化后续 step 访问).
        """
        self.plan = Plan(tasks=self.tasks, requirement=self.requirement)
        self.judge = ConvergenceJudge(config=self.config.convergence_config)
        # v2.3 Phase H (P1.4): agent_runtime 优先, 替代单一 executor callback
        if self.config.agent_runtime is not None:
            self.executor = self._build_runtime_executor(self.config.agent_runtime)
        # v5.0 M4: 内部状态初始化
        if self._state is None:
            self._state = EngineState(requirement=self.requirement)
        if self._router is None:
            self._router = (
                self.config.stage_router
                if self.config.stage_router is not None
                else StageRouter()
            )
        # v5.4 审计 P0-1: CheckpointManager 协作策略
        if self._checkpoint_mgr is None:
            self._checkpoint_mgr = CheckpointManager(
                self.config.checkpoint_store
            )
        # v5.4 审计 P1-1: GuardrailFacade 协作策略
        if self._guardrail_facade is None:
            self._guardrail_facade = GuardrailFacade(
                self.config.guardrail_chain,
                self.config.project_root,
            )
        # 2026-07-05 修复 (对标审计 P0-4): 注入 requirement 到 semantic_evaluator,
        # 替代 "(see task outcomes)" 硬编码占位符.
        if (
            self.config.semantic_evaluator is not None
            and hasattr(self.config.semantic_evaluator, "requirement")
        ):
            self.config.semantic_evaluator.requirement = self.requirement

    def _build_runtime_executor(self, runtime: AgentRuntime) -> TaskExecutor:
        """构建从 AgentRuntime 调度的 executor.

        v2.3 Phase H (P1.4): 借鉴 AutoGen GroupChat agent_selector, 按 task.role
        查 Runtime.get(role).execute (懒实例化). task.role 在 Runtime 中未注册
        → 返回 failed TaskOutcome (graceful degradation, 不抛异常, 避免 round
        因单 task 错误完全失败).

        协议转换:
            loop.Task  →  runtime.Task (BaseAgent 期望的格式)
            ctx        →  TaskContext(state=EngineState(requirement=self.requirement))
            result.values → output=str(values)

        Args:
            runtime: AgentRuntime 实例 (已注册 architect/developer/critic 等)

        Returns:
            async (Task, ctx) -> TaskOutcome 函数 — 可被 run_round 直接调用
        """
        async def runtime_executor(
            loop_task: Task, ctx: Any
        ) -> TaskOutcome:
            # 1. 按 role 查 Agent (懒实例化)
            lookup = loop_task.role
            agent = runtime.get(lookup)
            if agent is None:
                # 未注册 → 失败 outcome (graceful degradation, 不抛)
                return TaskOutcome(
                    task_id=loop_task.id,
                    status="failed",
                    error=f"No agent registered for role: {lookup}",
                )

            # 2. 构造 runtime.Task (BaseAgent 期望的格式)
            runtime_task = RuntimeTask(
                id=loop_task.id,
                description=loop_task.description,
                expected_output=loop_task.expected_output,
            )
            if loop_task.expected_output:
                schema = derive_output_schema(loop_task.expected_output)
                if schema:
                    runtime_task.output_schema = schema
            # 3. 构造 TaskContext (state 必填, 用 EngineState 默认值即可)
            state: EngineState = ctx if isinstance(ctx, EngineState) else EngineState(
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
        """v5.1: 12 步主循环 — tick/after_tick 分离 (借鉴 LangGraph PregelLoop).

        借鉴 LangGraph PregelLoop.tick() / after_tick() 分离模式 (pregel/_loop.py:592-691):
          - tick():        任务准备 + 前置检查 + Agent 执行 (Steps 2a-2e)
          - after_tick():  后置检查 + 状态更新 + 收敛判定 + 持久化 (Steps 2f-2i)

        LangGraph 原文: tick() → check limit → prepare tasks → check done →
          apply writes → execute; after_tick() → collect writes → apply_writes →
          update channels → checkpoint.

        本实现映射:
          _tick()        → 2a cancel → 2b route → 2c select → 2d PRE → 2e execute
          _after_tick()  → 2f POST → 2g semantic → 2h MAJOR → 2i judge + checkpoint

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

        try:
            # ===== step 2: 主循环 — tick/after_tick =====
            round_id = 0
            while round_id < max_iter:
                round_id += 1
                self._state.write_field("round", round_id, "orchestrator")

                round_result, current_stage, action = await self._tick(
                    round_id, max_iter, cancellation, guardrail_chain, project_root,
                )
                if action == "break":
                    break
                if action == "advance":
                    round_id -= 1  # 空 stage 推进不消耗迭代配额
                    continue

                # action == "execute": proceed to after_tick
                if await self._after_tick(
                    round_result, current_stage, guardrail_chain, round_id,
                ):
                    break

            # ===== step 3: 退出块 =====
            if self.verdict is None or not self.verdict.should_stop:
                latest_gates = self._collect_latest_gates()
                _, final_verdict = self._step_3_exit_block(
                    self._state, self.history, latest_gates, max_iter, round_id,
                )
                self.verdict = final_verdict
            return list(self.history)
        finally:
            if self.config.checkpoint_store is not None:
                self.config.checkpoint_store.close()
            if self.config.agent_runtime is not None:
                self.config.agent_runtime.close()
            if self.config.semantic_evaluator is not None and hasattr(
                self.config.semantic_evaluator, "close"
            ):
                self.config.semantic_evaluator.close()

    # ========================================================================
    # v5.1 tick/after_tick — 借鉴 LangGraph PregelLoop (pregel/_loop.py:592-691)
    # ========================================================================
    # tick():      check limit → prepare tasks → check done → execute (Steps 2a-2e)
    # after_tick(): collect writes → apply_writes → update channels → checkpoint
    #              (Steps 2f-2i)
    # ========================================================================

    async def _tick(
        self,
        round_id: int,
        max_iter: int,
        cancellation: CancellationToken | None,
        guardrail_chain: "GuardrailChain | None",
        project_root: Path,
    ) -> tuple["RoundResult | None", str, str]:
        """tick 阶段: 准备任务 + 前置检查 + Agent 执行 (Steps 2a-2e).

        借鉴 LangGraph PregelLoop.tick() (pregel/_loop.py:592-691):
          1. check iteration limit → 2a cancel check
          2. prepare_next_tasks → 2b route init + 2c select tasks
          3. if no tasks → done (break/advance)
          4. apply pending writes → (本实现无 pending writes)
          5. check interrupt_before → 2d PRE Guardrail
          6. execute tasks → 2e run agent

        Returns:
            (round_result, current_stage, action):
            - "execute": round_result 有效, 进入 after_tick
            - "advance": 跳过 after_tick, while loop 继续 (空 stage 推送)
            - "break": 退出 while loop (cancel/guardrail stop/空 tasks)
        """
        # 2a 取消检查
        if self._step_2a_cancel(cancellation):
            return None, "", "break"

        # 2b 路由初始化
        self._step_2b_route_init(self._state, self._router)
        current_stage = self._state.current_stage or "architect"

        # 2c 选任务
        round_tasks, advance = self._step_2c_select_tasks(current_stage)
        if not round_tasks and current_stage == "architect" and advance and self.config.agent_runtime is not None:
            round_tasks = [self._make_architect_synthetic_task()]
            advance = False
        if not round_tasks and advance:
            return None, current_stage, "advance"
        if not round_tasks:
            return None, current_stage, "break"

        # 2d PRE Guardrail
        pre_action = self._step_2d_guardrail_pre(
            guardrail_chain, current_stage, self._state
        )
        if pre_action == "stop":
            self.verdict = ConvergenceVerdict.stop(level=4, reason="PRE guardrail stop")
            return None, current_stage, "break"
        if pre_action == "retry":
            return None, current_stage, "advance"

        # 2e Agent 执行
        round_result = await self._step_2e_run_agent(
            current_stage, round_tasks, self._state,
            project_root, cancellation, round_id,
        )
        return round_result, current_stage, "execute"

    async def _after_tick(
        self,
        round_result: "RoundResult | None",
        current_stage: str,
        guardrail_chain: "GuardrailChain | None",
        round_id: int,
    ) -> bool:
        """after_tick 阶段: 后置检查 + 状态更新 + 收敛判定 + 持久化 (Steps 2f-2i).

        借鉴 LangGraph PregelLoop.after_tick() (pregel/_loop.py:676-691):
          1. collect writes from tasks → 2f POST Guardrail + 2g semantic
          2. apply_writes → _apply_outcome_to_state (in _step_2e)
          3. update channels → history + round_results
          4. output values → 2h MAJOR count
          5. interrupt_after → 2i judge + checkpoint
          6. _put_checkpoint → _save_checkpoint

        Returns:
            True → break main loop, False → continue
        """
        if round_result is None:
            return True  # tick was skipped

        assert self._state is not None and self._router is not None

        # 2f POST Guardrail
        post_action = self._step_2f_guardrail_post(
            guardrail_chain, current_stage, self._state
        )
        if post_action == "stop":
            self.verdict = ConvergenceVerdict.stop(level=4, reason="POST guardrail stop")
            return True
        if post_action == "retry":
            return False  # continue

        # 2g semantic 评估 (critic 阶段)
        await self._step_2g_semantic(
            self.config.semantic_evaluator, current_stage, round_result,
        )
        self.round_results.append(round_result)
        self.history.extend(round_result.history)

        # v5.4 P1-5: architect 产出 batch_plan 后, 重建 Plan 供 developer 阶段使用
        if current_stage == "architect" and self._state.batch_plan:
            self.plan = tasks_from_batch_plan(
                self._state.batch_plan, self.requirement
            )

        # 2h MAJOR 计数 (critic 阶段)
        self._step_2h_major_count(self._state, self._state.verdict, current_stage)

        # v5.5 Phase 2: 步2i-2k (DocSync + DeepAudit + T9)
        gates_passed = all_gates_passed(
            round_result.history[0].gate_results if round_result.history else {}
        )
        is_critic_approve = (
            current_stage == "critic"
            and self._state.verdict == "APPROVE"
        )
        deep_audit_enabled = (
            self.judge is not None
            and self.judge.config is not None
            and self.judge.config.deep_audit_enabled
        )

        # 步2i: Design Doc Check (critic APPROVE + all gates passed)
        if is_critic_approve and gates_passed:
            design_docs_stale = self._warn_design_docs_update(self._state)
            if design_docs_stale:
                # v5.5 audit P0-3: Stage 4 强制步骤 — 设计文档过期时标记到 state,
                # 供收敛判定参考. 当前不硬阻断 (全自动同步尚未实现),
                # 但记录到 critic_feedback 供下一轮 architect 参考.
                self._state.write_field(
                    "critic_feedback",
                    self._state.critic_feedback
                    + "\n[Stage 4 Design Doc Sync] BEACON.md 可能过期, "
                    + "请在下一轮 architect PLAN-REFINE 中更新设计文档.",
                    "orchestrator",
                )

        # 步2j: DeepAuditGate (critic APPROVE + all gates passed + deep_audit_enabled)
        audit_found_issues = False
        if is_critic_approve and gates_passed and deep_audit_enabled:
            audit_found_issues, findings = self._run_deep_audit(
                self.config.project_root or Path.cwd()
            )
            if audit_found_issues:
                self._state.write_field("audit_findings", findings, "orchestrator")
            else:
                self._state.write_field("audit_findings", None, "orchestrator")

        # 步2k: StageRouter.next + T9 logic + Judge.evaluate
        if audit_found_issues and is_critic_approve and deep_audit_enabled:
            # T9: DeepAudit 发现问题 → PLAN-REFINE 回路, 跳过 ConvergenceJudge
            self._state.plan_refine_count += 1
            max_plan_refines = (
                self.judge.config.max_plan_refines
                if self.judge and self.judge.config
                else 3
            )
            decision = self._router.next(
                current_stage=current_stage,
                verdict=self._state.verdict,
                majors_in_a_row=self._state.majors_in_a_row,
                total_majors=self._state.total_majors,
                audit_found_issues=True,
                plan_refine_count=self._state.plan_refine_count,
                max_plan_refines=max_plan_refines,
            )
            if decision.should_stop:
                self.verdict = ConvergenceVerdict.stop(
                    level=4, reason=decision.stop_reason or "T9-LIMIT stop"
                )
                self._save_checkpoint(round_id=round_id, step=2, tag="after_tick_t9_stop")
                return True
            # T9: 回到 architect, 跳过 Judge
            clear_stage_fields(self._state, current_stage)
            self._state.write_field("current_stage", decision.next_stage or "architect", "orchestrator")
            self._save_checkpoint(round_id=round_id, step=2, tag="after_tick_t9")
            return False  # continue, 不调 Judge

        # 2k (正常路径): StageRouter.next + Judge.evaluate + 退出条件
        should_break = self._step_2i_route_and_judge(
            self._router, self.judge, current_stage, self._state,
        )
        self._save_checkpoint(round_id=round_id, step=2, tag="after_tick")
        return should_break

    # ========================================================================
    # v5.0 P1-1: run() 拆 8 子方法 (单一职责) — 由 tick/after_tick 调度
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
        # v5.5: auto_tune_max_iter — 从审计历史动态调整 max_iter (启用时)
        if self.judge.config.auto_tune:
            from auto_engineering.loop.audit_history import AuditHistory
            tuned = self.judge.auto_tune_max_iter(
                AuditHistory(self.config.project_root or Path.cwd())
            )
            if tuned is not None and tuned > 0:
                max_iter = tuned
                logging.getLogger("ae.loop.orchestrator").info(
                    "auto_tune_max_iter: %d (from audit history)", max_iter,
                )
        project_root = self.config.project_root or Path.cwd()
        if self._state is None:
            self._state = EngineState(requirement=self.requirement)
        if self._router is None:
            self._router = StageRouter()
        guardrail_chain = self.config.guardrail_chain
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
            self.verdict = ConvergenceVerdict.stop(
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
            max_plan_refines=(
                self.judge.config.max_plan_refines
                if self.judge and self.judge.config
                else 3
            ),
        )
        state.write_field("current_stage", decision.next_stage or "", "orchestrator")
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
        if round_tasks:
            return round_tasks, False

        # 仍为空: 推到下一 stage (避免空 stage 空转)
        assert self._router is not None and self._state is not None
        try:
            advance_decision = self._router.next(
                current_stage=current_stage,
                verdict="",
                majors_in_a_row=self._state.majors_in_a_row,
                total_majors=self._state.total_majors,
            )
        except CriticVerdictInvalid:
            # critic stage 无 task → 无 verdict → 自然结束 stage 流
            return [], False
        if advance_decision.next_stage is not None:
            clear_stage_fields(self._state, current_stage)
            self._state.write_field("current_stage", advance_decision.next_stage, "orchestrator")
            return [], True
        # stage 流终点: 跳出
        return [], False

    _ARCHITECT_SYNTHETIC_ID = "architect-synthetic"
    _ARCHITECT_SYNTHETIC_TITLE = "Generate implementation plan"
    _ARCHITECT_SYNTHETIC_OUTPUT = "batch_plan with developer tasks"

    def _make_architect_synthetic_task(self) -> Task:
        """当 plan 无 architect task 时, 合成一个默认 task 触发 LLM 规划."""
        return Task(
            id=self._ARCHITECT_SYNTHETIC_ID,
            title=self._ARCHITECT_SYNTHETIC_TITLE,
            description=f"Analyze requirement: {self.requirement}",
            expected_output=self._ARCHITECT_SYNTHETIC_OUTPUT,
            role="architect",
        )

    def _step_2d_guardrail_pre(
        self,
        guardrail_chain: "GuardrailChain | None",
        current_stage: str,
        state: "EngineState",
    ) -> str:
        """step 2d: PRE Guardrail 检查. 委托 GuardrailFacade (v5.4 审计 P1-1)."""
        assert self._guardrail_facade is not None
        return self._guardrail_facade.check_pre(current_stage, state)

    async def _step_2e_run_agent(
        self,
        current_stage: str,
        round_tasks: list[Task],
        state: "EngineState",
        project_root: Path,
        cancellation: CancellationToken | None,
        round_id: int,
    ) -> RoundResult:
        """step 2e: 调 run_round 执行 agent tasks (v5.4 Agent Tool 直接执行模式).

        architect/critic/developer 所有 stage 统一走 run_round → AgentRuntime 路径.
        把 outcomes 按 task_role 分发写入 state 字段 (B7.2).
        """
        # v5.4: JSONL 协议已移除 (BEACON 决策 33/34).
        # 所有 stage 统一走 run_round + AgentRuntime 路径.
        enhanced_tasks = _inject_self_refine_context(
            round_tasks, state, current_stage, self._collect_latest_gates(),
        )
        channel_versions = self._update_channel_versions(state)
        start_commit = capture_head(project_root)
        round_result = await run_round(
            tasks=enhanced_tasks,
            executor=self.executor,
            ctx=None,
            cancellation=cancellation,
            round_id=round_id,
            gates=self.config.gates,
            project_root=project_root,
            stage=current_stage,
            channel_versions=channel_versions,
            start_commit=start_commit,
        )
        for outcome in round_result.outcomes:
            apply_outcome_to_state(state, outcome)
        return round_result

    def _step_2f_guardrail_post(
        self,
        guardrail_chain: "GuardrailChain | None",
        current_stage: str,
        state: "EngineState",
    ) -> str:
        """step 2f: POST Guardrail 检查. 委托 GuardrailFacade (v5.4 审计 P1-1)."""
        assert self._guardrail_facade is not None
        return self._guardrail_facade.check_post(current_stage, state)

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
        update_majors_count(state, verdict)
        # v5.4 P1-8: reset critic retry count on any successful critic pass
        self._critic_retry_count = 0

    def _step_2i_route_and_judge(
        self,
        router: "StageRouter",
        judge: ConvergenceJudge,
        current_stage: str,
        state: "EngineState",
    ) -> bool:
        """step 2i: StageRouter.next + Judge.evaluate. 返回 should_break."""
        try:
            decision = router.next(
                current_stage=current_stage,
                verdict=state.verdict if current_stage == "critic" else "",
                majors_in_a_row=state.majors_in_a_row,
                total_majors=state.total_majors,
            )
        except CriticVerdictInvalid as exc:
            return self._handle_critic_verdict_invalid(exc, state)

        routing_result = self._apply_stage_decision(decision, state, current_stage)
        if routing_result is not None:
            return routing_result

        return self._judge_convergence(judge, state, current_stage)

    def _handle_critic_verdict_invalid(
        self, exc: CriticVerdictInvalid, state: "EngineState"
    ) -> bool:
        """CriticVerdictInvalid 重试/升级. 返回 should_break."""
        MAX_CRITIC_RETRIES = 2
        if self._critic_retry_count < MAX_CRITIC_RETRIES:
            self._critic_retry_count += 1
            state.write_field("current_stage", "critic", "orchestrator")
            logging.getLogger("ae.loop.orchestrator").warning(
                "Bug 2 方案 A: critic verdict 异常, 重试 (%d/%d): %r",
                self._critic_retry_count,
                MAX_CRITIC_RETRIES,
                exc.verdict,
            )
            return False
        self.verdict = ConvergenceVerdict.stop(
            level=4,
            reason=f"critic verdict 异常 (重试 {MAX_CRITIC_RETRIES} 次仍失败, Bug 3 升级到 HARD_LIMIT): {exc.verdict!r}",
        )
        return True

    def _apply_stage_decision(
        self,
        decision: "StageDecision",
        state: "EngineState",
        current_stage: str,
    ) -> bool | None:
        """应用 StageDecision: should_stop / next_stage / None→需要 judge.
        返回 True=break, False=continue, None=需 judge 评估.
        """
        if decision.should_stop:
            self.verdict = ConvergenceVerdict.stop(
                level=4, reason=decision.stop_reason or "StageRouter stop"
            )
            return True
        if decision.next_stage is not None:
            clear_stage_fields(state, current_stage)
            state.write_field("current_stage", decision.next_stage, "orchestrator")
            return False
        return None

    def _judge_convergence(
        self,
        judge: ConvergenceJudge,
        state: "EngineState",
        current_stage: str,
    ) -> bool:
        """ConvergenceJudge 评估 + gate 反向补丁 (v5.4 审计 P1-1: 委托 ConvergenceFacade)."""
        verdict = _evaluate_convergence(judge, list(self.history), current_stage)
        if verdict is not None:
            self.verdict = verdict
            return True
        return False

    def _collect_latest_gates(self) -> dict[str, GateVerdict]:
        """收集最近一轮 RoundHistory 的 gate_results (dict[str, GateVerdict]).

        2026-07-04 (Bug 3 方案 C): 用于 step 2i gate_summary 反向防御检查.
        2026-07-04 P0 修复: 唯一权威实现 (前 c2fd29e commit 误加同方法覆盖
        返回 dict[str, bool] 破坏 _gates_all_passed + _inject_self_refine_context).
        消费方期望 dict[str, GateVerdict] (有 .passed / .message 属性).
        """
        if not self.history:
            return {}
        last_round = self.history[-1]
        return last_round.gate_results or {}

    def _update_channel_versions(self, state: "EngineState") -> dict[str, int]:
        """更新并返回 channel_versions (基于 state 字段内容 hash).

        每次字段值变化时递增对应 channel 的 version.
        供 _get_new_channel_versions 做增量触发停滞检测.

        v5.4 审计 r2: channel_keys 从 ROLE_FIELD_MAP 派生 (单一真相源).
        """
        from auto_engineering.loop.task_factory import ROLE_FIELD_MAP

        channel_keys: list[str] = []
        for fields in ROLE_FIELD_MAP.values():
            channel_keys.extend(fields)
        for key in channel_keys:
            value = getattr(state, key, None)
            value_hash = hash(str(value))
            if key not in self._channel_hashes or self._channel_hashes[key] != value_hash:
                self._channel_versions[key] = self._channel_versions.get(key, 0) + 1
                self._channel_hashes[key] = value_hash
        return dict(self._channel_versions)

    # ========================================================================
    # v5.5 Phase 2: DeepAudit + DocSync + T9 methods
    # ========================================================================

    def _run_deep_audit(self, project_root: Path) -> tuple[bool, list[dict]]:
        """B7.1 步2j: 运行 DeepAudit 基线扫描 + counting/threshold 判定.

        流程:
            1. DeepAuditOrchestrator 调用 AuditGate 静态扫描
            2. 内联 counting: P0>0 或 P1>threshold → audit_found
            3. 写入审计历史 JSONL (供 ThresholdLearner 学习)

        Args:
            project_root: 项目根目录路径.

        Returns:
            (audit_found_issues, findings): audit_found_issues=True 表示
            发现问题需 T9 回路, findings 为 dict 列表.
        """
        from auto_engineering.loop.audit_history import AuditHistory
        from auto_engineering.loop.deep_audit import DeepAuditOrchestrator

        p1_threshold = self._get_p1_threshold()

        audit_orchestrator = DeepAuditOrchestrator(project_root)
        report = audit_orchestrator.run_audit()

        # 内联 counting (替代 DeepAuditGate 包装层)
        audit_found = report.p0_count > 0 or report.p1_count > p1_threshold

        findings_list: list[dict] = [
            {
                "severity": f.severity,
                "dimension": f.dimension,
                "file": f.file,
                "line": f.line,
                "description": f.description,
                "evidence": f.evidence,
                "suggested_fix": f.suggested_fix,
                "agent_source": f.agent_source,
            }
            for f in report.findings
        ]

        history = AuditHistory(project_root)
        history.append_entry(
            p0=report.p0_count,
            p1=report.p1_count,
            p2=report.p2_count,
            threshold=p1_threshold,
            total_files=report.total_audited_files,
            plan_refine_triggered=audit_found,
        )

        return audit_found, findings_list

    def _get_p1_threshold(self) -> int:
        """获取当前 P1 阈值 (从 ThresholdLearner 动态计算, 冷启动默认 6).

        Task 4.2: 接入 ThresholdLearner 从 JSONL 审计历史动态计算 p75 阈值.
        冷启动 (< MIN_SAMPLES=5 条目) 时返回硬编码默认值 6.

        Returns:
            int: 当前 P1 阈值.
        """
        from auto_engineering.loop.audit_history import AuditHistory
        from auto_engineering.loop.threshold_learner import ThresholdLearner

        project_root = self.config.project_root or Path.cwd()
        history = AuditHistory(project_root)
        learner = ThresholdLearner(history)
        return learner.compute_p1_threshold()



    def _warn_design_docs_update(self, state: "EngineState") -> bool:
        """B7.1 步2i (Stage 4 Design Doc Sync): 检查 BEACON.md 是否滞后于代码改动.

        强制步骤 (CLAUDE.md Stage 4): 若核心模块改动但 BEACON.md 在改动前最后修改,
        说明文档未同步 → 返回 True (需更新). 调用方应将此信息写入 state 供下一步决策.

        Returns:
            True 若 BEACON.md 需要更新, False 若已同步或无核心改动.
        """
        _logger = logging.getLogger(__name__)
        changed = state.files_changed if state.files_changed else []
        if not changed:
            return False

        project_root = self.config.project_root or Path.cwd()
        beacon_path = project_root / "design" / "BEACON.md"
        if not beacon_path.exists():
            return False

        core_dirs = {"loop/", "gates/", "agents/", "engine/", "cli/", "tools/"}
        core_changed = [
            f for f in changed
            if any(f.startswith(d) for d in core_dirs)
        ]
        if not core_changed:
            return False

        # 检查 BEACON.md 修改时间 vs 本轮改动时间
        beacon_mtime = beacon_path.stat().st_mtime
        stale = False
        for f in core_changed:
            fpath = project_root / f
            if fpath.exists() and fpath.stat().st_mtime > beacon_mtime:
                stale = True
                break

        if stale:
            _logger.error(
                "Stage 4 Design Doc Sync: 核心模块 %s 在 BEACON.md 之后修改 (%d 文件), "
                "设计文档可能过期. 请更新 BEACON.md 后重新运行.",
                core_changed[:5], len(core_changed),
            )
            return True

        _logger.info(
            "Stage 4 Design Doc Sync: BEACON.md 已是最新 (核心改动 %d 文件).",
            len(core_changed),
        )
        return False

    def _step_3_exit_block(
        self,
        state: "EngineState | None",
        history: deque[RoundHistory],
        latest_gates: dict[str, Any],
        max_iter: int,
        round_id: int,
    ) -> tuple[list[RoundHistory], ConvergenceVerdict]:
        """step 3: 退出块. 返回 (history, final_verdict).

        3 种退出原因:
          1. GOAL_ACHIEVED (verdict 已有 should_stop) → 上层 step 2i 已 return
          2. max_iter 硬上限 → level=4 LEVEL_HARD_LIMIT
          3. unexpected (dec.next_stage=None + judge 不 stop) → 兜底按 max_iter
        退出前 _save_checkpoint 一次 (兜底持久化).
        """
        self._save_checkpoint(round_id=round_id, step=2, tag="exit_block")
        final_verdict = ConvergenceVerdict.stop(
            level=4,
            reason=f"达到最大轮次 {max_iter} (硬上限)",
        )
        return list(history), final_verdict

    def _save_checkpoint(
        self,
        round_id: int,
        step: int = 0,
        tag: str | None = None,
    ) -> str | None:
        """保存 Checkpoint — 委托 CheckpointManager (v5.4 审计 P0-1)."""
        if self._checkpoint_mgr is None:
            return None
        return self._checkpoint_mgr.save(
            state=self._state,
            round_id=round_id,
            step=step,
            history=list(self.history),
            tag=tag,
        )

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
        except Exception as exc:
            logging.warning(
                "语义评估器异常 (round_id=%s): %s",
                getattr(round_result, "round_id", "?"), exc, exc_info=True,
            )
            return None


def _inject_self_refine_context(
    round_tasks: list[Task],
    state: "EngineState",
    current_stage: str,
    latest_gates: dict[str, Any],
) -> list[Task]:
    """Self-Refine 反馈注入: 把 critic_feedback + findings + gate_results 拼接到 task.description.

    触发条件:
        - state.critic_feedback 非空 (上一轮 critic 给 MAJOR 反馈)
        - state.findings 非空 (P0/P1/P2 findings 列表)
        - latest_gates 非空 (lint/test/type_check 结果)
        - 当前 stage 是 developer / critic (architect 阶段无反馈意义)

    不修改原 round_tasks (返回新 list, 内部用 dataclasses.replace 复制 Task).
    """
    if current_stage == "architect":
        return round_tasks

    has_feedback = bool(state.critic_feedback)
    has_findings = bool(state.findings)
    has_gates = bool(latest_gates)

    if not (has_feedback or has_findings or has_gates):
        return round_tasks

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

    if state.suggested_fix:
        context_parts.append(
            f"\n\n## [Self-Refine suggested_fix] Critic 上一轮结构化 patch "
            f"(直接应用, 不重新解读):\n```diff\n{state.suggested_fix}\n```\n"
            f"**重要**: 这是 unified diff 格式, 可用 `git apply` 直接应用. "
            f"优先按此 patch 修复, 避免 LLM 自我理解偏差."
        )

    context_suffix = "".join(context_parts)
    enhanced: list[Task] = []
    for task in round_tasks:
        new_description = task.description + context_suffix
        enhanced.append(replace(task, description=new_description))
    return enhanced


__all__ = [
    "Orchestrator",
    "OrchestratorConfig",
]