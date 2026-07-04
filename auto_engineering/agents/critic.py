"""CriticAgent — 代码审查.

设计: design/LOOP-DEVELOPMENT-PLAN.md v2.0 文件 23.

P1-A: 原为 BaseAgent 子类, 现改为 factory function 返回 Agent 实例.

2026-07-04 修复 (Bug 2 prismscan 集成): critic agent 启动时 fail-fast 检查
LLM 凭据, 缺失时抛 CriticAuthError (不再静默 401 → 空 verdict → 0 代码改动退出).
"""

from __future__ import annotations

import logging

from .base import Agent
from .prompts import CRITIC_SYSTEM_PROMPT

_logger = logging.getLogger(__name__)


class CriticAuthError(RuntimeError):
    """Critic agent 启动时检测到无 LLM 凭据 (Bug 2 prismscan)."""


def CriticAgent(llm, **kwargs) -> Agent:
    """Factory: 返回配置为 critic role 的 Agent.

    2026-07-04 修复 (Bug 2):
        - 启动时 fail-fast 检查 LLM 凭据 (ANTHROPIC_API_KEY/AUTH_TOKEN)
        - 缺失且不在 plugin mode → 抛 CriticAuthError (显式失败, 不静默)
        - 记录 LLM 调用 env (debug 级别, 辅助事后诊断 401)
    """
    from auto_engineering.utils.plugin_mode import detect_plugin_mode, has_llm_credentials

    in_plugin = detect_plugin_mode()
    has_cred = has_llm_credentials()

    if not has_cred and not in_plugin:
        raise CriticAuthError(
            "critic agent 无 LLM 凭据: ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN 未设置, "
            "且不在 Claude Code plugin mode. plugin 模式应自动注入 OAuth token. "
            "(Bug 2 prismscan 集成 fail-fast)"
        )

    # Debug log: 记录 critic 实际看到的 env (辅助诊断 401 / 解析失败)
    import os

    base_url = os.environ.get("ANTHROPIC_BASE_URL", "(default api.anthropic.com)")
    auth_preview = ""
    for var in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
        v = os.environ.get(var, "")
        if v:
            auth_preview = f"{var}={v[:8]}...{v[-4:]}"
            break
    _logger.debug(
        "critic LLM env: BASE_URL=%s, AUTH=%s, plugin_mode=%s",
        base_url,
        auth_preview or "(none)",
        in_plugin,
    )

    kwargs.setdefault("role", "critic")
    kwargs.setdefault("system_prompt", CRITIC_SYSTEM_PROMPT)
    kwargs.setdefault("tools", [])  # 工具在 AgentRuntime 层注入
    return Agent(llm=llm, **kwargs)
