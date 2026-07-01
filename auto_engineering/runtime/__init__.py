"""Agent 运行时 — 借鉴 AutoGen _single_threaded_agent_runtime.py.

核心类（Phase 2+ 实现）:
    AgentRuntime — Agent 注册 + 任务执行 + Guardrail 中间件
    CancellationToken — 协作式取消令牌 (Phase 03 整合)
"""

from .cancellation import CancellationToken
from .runtime import AgentRuntime

__all__ = ["AgentRuntime", "CancellationToken"]