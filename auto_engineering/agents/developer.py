"""DeveloperAgent — TDD 三步循环实现.

设计: design/LOOP-DEVELOPMENT-PLAN.md v2.0 文件 22.

P1-A: 原为 BaseAgent 子类, 现改为 factory function 返回 Agent 实例.
"""

from __future__ import annotations

from .base import Agent
from .prompts import DEVELOPER_SYSTEM_PROMPT


def DeveloperAgent(llm, **kwargs) -> Agent:
    """Factory: 返回配置为 developer role 的 Agent."""
    kwargs.setdefault("role", "developer")
    kwargs.setdefault("system_prompt", DEVELOPER_SYSTEM_PROMPT)
    kwargs.setdefault("tools", [])  # 工具在 AgentRuntime 层注入
    return Agent(llm=llm, **kwargs)
