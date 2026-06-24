"""Agent 实现 — Claude API 驱动的智能角色.

Phase 0.3 真接: 3 Agent(BaseAgent 子类)各带 system_prompt.
"""

from .architect import ARCHITECT_SYSTEM_PROMPT, ArchitectAgent
from .base import BaseAgent
from .critic import CRITIC_SYSTEM_PROMPT, CriticAgent
from .developer import DEVELOPER_SYSTEM_PROMPT, DeveloperAgent

__all__ = [
    "ARCHITECT_SYSTEM_PROMPT",
    "CRITIC_SYSTEM_PROMPT",
    "DEVELOPER_SYSTEM_PROMPT",
    "ArchitectAgent",
    "BaseAgent",
    "CriticAgent",
    "DeveloperAgent",
]
