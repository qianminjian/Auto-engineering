"""AgentRuntime — Agent 注册 + 任务执行 + 延迟实例化.

参考 AutoGen _single_threaded_agent_runtime.py:
    - register_factory:886-914  (延迟实例化 + 类型检查)
    - _get_agent:976-986       (懒创建)
    - send_message:332         (消息分发)

v1.0 精简:
    - 不实现 Pub/Sub、消息队列、RoutedAgent(单一 Async 路径)
    - Agent 是 Protocol(duck typing),不依赖 BaseAgent 空类
    - 延迟实例化:首次 execute 时创建 Agent 实例

设计要点:
    - Agent Runtime 是 Layer 3(执行层),被 Layer 1(LoopEngine)调用
    - LoopEngine.run() 中 `await self.runtime.execute(stage, state)` 是主要入口
    - 实际 LLM 调用在 Phase 3 实现,Phase 2 用 ScriptedMockRuntime / MockAgent 验证
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from auto_engineering.engine.graph import Stage
from auto_engineering.engine.loop import StageResult
from auto_engineering.engine.state import LoopState
from auto_engineering.runtime.context import TaskContext
from auto_engineering.runtime.task import Task, TaskResult


@runtime_checkable
class Agent(Protocol):
    """Agent Protocol — 任何实现 execute() 的对象都视为 Agent.

    v1.0 BaseAgent 是空类,Phase 3 才有真实实现.
    通过 Protocol 实现 duck typing:
        - ScriptedMockRuntime (tests/conftest.py) 兼容
        - Phase 3 BaseAgent 兼容
        - 任何 user-defined Agent 兼容
    """

    async def execute(
        self,
        task: Task,
        ctx: TaskContext,
        cancellation: Any = None,
    ) -> TaskResult: ...


class AgentRuntime:
    """Agent 注册表 + 任务执行器.

    API:
        register(agent_type, factory, expected_class=None)
            → 注册 Agent 工厂(可指定期望类,运行时类型检查)

        async execute(stage, state, cancellation=None)
            → 执行 Stage 对应的 Agent,返回 StageResult

    内部状态:
        _factories: dict[agent_type, Callable[[], Agent]]
        _instances: dict[agent_type, Agent]  延迟实例化缓存
        _expected_class: dict[agent_type, type]  类型检查配置
    """

    def __init__(self):
        self._factories: dict[str, Callable[[], Agent]] = {}
        self._instances: dict[str, Agent] = {}
        self._expected_class: dict[str, type] = {}

    def register(
        self,
        agent_type: str,
        factory: Callable[[], Agent],
        *,
        expected_class: type | None = None,
    ) -> None:
        """注册 Agent factory.

        Args:
            agent_type: Agent 类型名(architect/developer/critic 等)
            factory: 无参工厂函数,返回 Agent-like 对象
            expected_class: 可选,期望的类。注册时实例化一次做类型检查(验证后销毁)。

        Raises:
            ValueError: agent_type 已注册
            TypeError: factory 返回的对象不是 expected_class 实例
        """
        if agent_type in self._factories:
            raise ValueError(f"Agent '{agent_type}' already registered")

        if expected_class is not None:
            # 注册时实例化一次做类型检查(验证后销毁)
            instance = factory()
            if not isinstance(instance, expected_class):
                raise TypeError(
                    f"Agent factory for '{agent_type}' returned "
                    f"{type(instance).__name__}, expected {expected_class.__name__}"
                )
            # 验证通过,延迟到首次 execute 再创建

        self._factories[agent_type] = factory
        if expected_class is not None:
            self._expected_class[agent_type] = expected_class

    def _get_or_create_agent(self, agent_type: str) -> Agent:
        """懒实例化 Agent. 已有实例则复用,否则 factory 创建.

        Raises:
            LookupError: agent_type 未注册
            TypeError: 实例与 expected_class 不匹配(运行时检查,防御性)
        """
        if agent_type in self._instances:
            return self._instances[agent_type]

        if agent_type not in self._factories:
            raise LookupError(
                f"Agent '{agent_type}' not registered. Available: {list(self._factories.keys())}"
            )

        instance = self._factories[agent_type]()

        # 运行时类型检查(防御性:工厂可能在 register 后变更)
        expected = self._expected_class.get(agent_type)
        if expected is not None and not isinstance(instance, expected):
            raise TypeError(
                f"Agent factory for '{agent_type}' returned "
                f"{type(instance).__name__}, expected {expected.__name__}"
            )

        self._instances[agent_type] = instance
        return instance

    async def execute(
        self,
        stage: Stage,
        state: LoopState,
        cancellation: Any = None,
    ) -> StageResult:
        """执行 Stage 对应的 Agent.

        流程:
            1. _get_or_create_agent(stage.agent_type)  → Agent 实例
            2. _build_task(stage, state)              → Task(描述已渲染)
            3. _build_context(stage, state)           → TaskContext(从 state 提取 inputs)
            4. agent.execute(task, ctx, cancellation)  → TaskResult
            5. 包装为 StageResult 返回

        Args:
            stage: 当前 Stage(定义 agent_type + 输入/输出 channels)
            state: 共享 LoopState
            cancellation: 可选 CancellationToken(Phase 2 暂不消费,Phase 3+ 接 Agent)

        Returns:
            StageResult(stage=stage.name, writes=TaskResult.values)

        Raises:
            LookupError: Agent 未注册
            TypeError: Agent 类型不匹配
            Agent 自定义异常(LLM_TIMEOUT 等)向上传播
        """
        agent = self._get_or_create_agent(stage.agent_type)
        task = self._build_task(stage, state)
        ctx = self._build_context(stage, state)

        result = await agent.execute(task, ctx, cancellation=cancellation)
        return StageResult(stage=stage.name, writes=result.values, raw=result)

    def _build_task(self, stage: Stage, state: LoopState) -> Task:
        """从 Stage + state 构造 Task. description 已渲染 input_channels."""
        return Task(
            id=stage.name,
            description=stage.render_description(state),
            expected_output=stage.expected_output,
            output_schema=stage.output_schema,
            tools=list(stage.tools),
            input_channels=list(stage.input_channels),
            output_channels=list(stage.output_channels),
        )

    def _build_context(self, stage: Stage, state: LoopState) -> TaskContext:
        """从 stage.input_channels 提取 channel 值作为 inputs."""
        return TaskContext(
            state=state,
            requirement=state.requirement,
            current_stage=stage.name,
            inputs=state.get_channels(stage.input_channels),
            outputs={},
        )
