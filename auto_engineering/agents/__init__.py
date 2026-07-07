"""Agent 实现 — Claude API 驱动的智能角色.

v2.0 真接: BaseAgent + 3 个 system_prompt (prompts.py).
"""

from .base import BaseAgent
from .prompts import ARCHITECT_SYSTEM_PROMPT, CRITIC_SYSTEM_PROMPT, DEVELOPER_SYSTEM_PROMPT

__all__ = [
    "ARCHITECT_SYSTEM_PROMPT",
    "BaseAgent",
    "CRITIC_SYSTEM_PROMPT",
    "DEVELOPER_SYSTEM_PROMPT",
]
