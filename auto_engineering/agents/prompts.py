"""Agent system prompts — v5.6: 从中央 PromptRegistry 派生 (B12 单一源).

3 个 role prompt 正文已迁至 `auto_engineering/prompts/roles/*.md` (§B12.3),
B11 行为塑形片段 (Iron Law/合理化表) 由 registry 按 frontmatter 组合前置.
本模块保留常量名向后兼容 (cli/dev_loop.py / cli/agent.py / agents/__init__.py),
值从 registry 派生 —— 消除 v5.6 前"3 层 3 版本"提示词漂移 (§B12.0).
"""

from __future__ import annotations

from auto_engineering.prompts.registry import default_registry

__all__ = ["ARCHITECT_SYSTEM_PROMPT", "CRITIC_SYSTEM_PROMPT", "DEVELOPER_SYSTEM_PROMPT"]

_reg = default_registry()
ARCHITECT_SYSTEM_PROMPT = _reg.get("architect")
DEVELOPER_SYSTEM_PROMPT = _reg.get("developer")
CRITIC_SYSTEM_PROMPT = _reg.get("critic")
