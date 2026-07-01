"""CriticAgent — 代码审查.

设计: design/LOOP-DEVELOPMENT-PLAN.md v2.0 文件 23.

P1-A: 原为 BaseAgent 子类, 现改为 factory function 返回 Agent 实例.
"""

from __future__ import annotations

from .base import Agent
from .prompts import CRITIC_SYSTEM_PROMPT


def CriticAgent(llm, **kwargs) -> Agent:
    """Factory: 返回配置为 critic role 的 Agent."""
    kwargs.setdefault("role", "critic")
    kwargs.setdefault("system_prompt", CRITIC_SYSTEM_PROMPT)
    kwargs.setdefault("tools", [])  # 工具在 AgentRuntime 层注入
    return Agent(llm=llm, **kwargs)
