"""ArchitectAgent — 需求分析 → 实现计划.

设计: design/LOOP-DEVELOPMENT-PLAN.md Phase 3 文件 21.

P1-A: 原为 BaseAgent 子类, 现改为 factory function 返回 Agent 实例.
保持向后兼容: ArchitectAgent(llm=...) 仍可用, 返回 Agent(role='architect').
"""

from __future__ import annotations

from .base import Agent
from .prompts import ARCHITECT_SYSTEM_PROMPT


def ArchitectAgent(llm, **kwargs) -> Agent:
    """Factory: 返回配置为 architect role 的 Agent.

    Args:
        llm: AnthropicProvider
        **kwargs: 传给 Agent (tools, model, max_tokens, ...)

    Returns:
        Agent 实例 (role='architect', system_prompt=ARCHITECT_SYSTEM_PROMPT)
    """
    kwargs.setdefault("role", "architect")
    kwargs.setdefault("system_prompt", ARCHITECT_SYSTEM_PROMPT)
    kwargs.setdefault("tools", [])  # Architect 只读 — 工具在 AgentRuntime 层注入
    return Agent(llm=llm, **kwargs)
