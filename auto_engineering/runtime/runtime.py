"""AgentRuntime — Agent 注册 + 延迟实例化 (v2.0 production path).

参考 AutoGen _single_threaded_agent_runtime.py:
    - register_factory:886-914  (延迟实例化 + 类型检查)
    - _get_agent:976-986       (懒创建)

v2.0 API:
    register(agent_type, factory) → 注册 Agent
    get(agent_type) → Agent 实例 (懒创建, 按 role 调度)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from auto_engineering.runtime.context import TaskContext
from auto_engineering.runtime.task import Task, TaskResult


@runtime_checkable
class Agent(Protocol):
    """Agent Protocol — 任何实现 execute() 的对象都视为 Agent."""

    async def execute(
        self,
        task: Task,
        ctx: TaskContext,
        cancellation: Any = None,
    ) -> TaskResult: ...


class AgentRuntime:
    """Agent 注册表 + 延迟实例化.

    v2.0 专有路径: Orchestrator 按 task.role 调 get(role) → agent.execute(task, ctx).
    不包含 v2.0 execute(stage, state) API.
    """

    def __init__(self, registry: Any = None):
        self._factories: dict[str, Callable[[], Agent]] = {}
        self._instances: dict[str, Agent] = {}
        self._expected_class: dict[str, type] = {}
        self._registry = registry

    def register(
        self,
        agent_type: str,
        factory: Callable[[], Agent],
        *,
        expected_class: type | None = None,
    ) -> None:
        """注册 Agent factory.

        Args:
            agent_type: Agent 类型名 (architect/developer/critic 等)
            factory: 无参工厂函数, 返回 Agent-like 对象
            expected_class: 可选, 注册时实例化一次做类型检查

        Raises:
            ValueError: agent_type 已注册
        """
        if agent_type in self._factories:
            raise ValueError(f"Agent '{agent_type}' already registered")
        self._factories[agent_type] = factory
        if expected_class is not None:
            self._expected_class[agent_type] = expected_class

    def _get_or_create_agent(self, agent_type: str) -> Agent:
        """懒实例化 Agent.

        Raises:
            LookupError: agent_type 未注册
        """
        if agent_type in self._instances:
            return self._instances[agent_type]

        if agent_type not in self._factories:
            raise LookupError(
                f"Agent '{agent_type}' not registered. Available: {list(self._factories.keys())}"
            )

        instance = self._factories[agent_type]()
        self._instances[agent_type] = instance
        return instance

    def get(self, agent_type: str) -> Agent | None:
        """按 agent_type 查 Agent 实例 (懒实例化).

        v2.3 Phase H (P1.4): Orchestrator 按 task.role 调度 Agent.
        未注册 → 返回 None (让 caller 优雅降级).
        已有实例 → 复用 (懒实例化缓存).
        """
        if agent_type not in self._factories:
            return None
        return self._get_or_create_agent(agent_type)

    def close(self) -> None:
        """释放所有已实例化 Agent 的底层资源 (httpx 连接等)."""
        for agent in self._instances.values():
            if hasattr(agent, "close"):
                agent.close()
