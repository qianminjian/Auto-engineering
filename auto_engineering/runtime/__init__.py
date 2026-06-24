"""Agent 运行时 — 借鉴 AutoGen _single_threaded_agent_runtime.py.

核心类（Phase 2+ 实现）:
    AgentRuntime — Agent 注册 + 任务执行 + Guardrail 中间件
"""

from .runtime import AgentRuntime

__all__ = ["AgentRuntime"]
