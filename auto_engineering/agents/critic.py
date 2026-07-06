"""CriticAgent — 代码审查.

设计: design/LOOP-DEVELOPMENT-PLAN.md v2.0 文件 23.

P1-A: 原为 BaseAgent 子类, 现改为 factory function 返回 Agent 实例.

2026-07-04 修复 (Bug 2 prismscan 集成): critic agent 启动时 fail-fast 检查
LLM 凭据, 缺失时抛 CriticAuthError (不再静默 401 → 空 verdict → 0 代码改动退出).
"""

from __future__ import annotations

import logging

from .base import BaseAgent
from .prompts import CRITIC_SYSTEM_PROMPT

_logger = logging.getLogger(__name__)


class CriticAuthError(RuntimeError):
    """Critic agent 启动时检测到无 LLM 凭据 (Bug 2 prismscan)."""


def CriticAgent(llm, **kwargs) -> BaseAgent:
    """Factory: 返回配置为 critic role 的 Agent.

    2026-07-04 修复 (Bug 2):
        - 启动时 fail-fast 检查 LLM 凭据 (ANTHROPIC_API_KEY/AUTH_TOKEN)
        - 缺失且不在 plugin mode → 抛 CriticAuthError (显式失败, 不静默)
        - 记录 LLM 调用 env (debug 级别, 辅助事后诊断 401)
    """
    from auto_engineering.utils.plugin_mode import detect_plugin_mode, is_llm_available

    in_plugin = detect_plugin_mode()

    if not is_llm_available():
        # 2026-07-04 深度设计 (用户洞察): plugin 在 Claude Code agent 内运行,
        # 应通过 ANTHROPIC_AUTH_TOKEN (OAuth) 自动注入. CLI 调试模式才需
        # 手动 export ANTHROPIC_API_KEY. 不应提示"plugin 模式应自动注入"
        # (这是矛盾说法), 改为"plugin mode 应自动工作, 如失败检查 env".
        raise CriticAuthError(
            "critic agent 无 LLM 凭据. "
            "Plugin mode (Claude Code agent 内) 应通过 ANTHROPIC_AUTH_TOKEN "
            "OAuth 自动注入, 用户**零配置**. 如失败检查 env: "
            "`env | grep ANTHROPIC_AUTH_TOKEN` 确认 token 已设. "
            "CLI 调试模式 (独立跑) 需手动 export ANTHROPIC_API_KEY."
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
    return BaseAgent(llm=llm, **kwargs)
