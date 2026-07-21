"""Plugin mode 4 级 fallback (v5.0 bug 修复, 2026-07-04).

prismscan 实际环境 CLAUDE_CODE_ENTRYPOINT=cli + ANTHROPIC_AUTH_TOKEN,
但 v5.0 preflight 只检查 CLAUDE_CODE + ANTHROPIC_CLI, 漏 2 级 fallback.
导致 plugin mode 用户误报 "ANTHROPIC_API_KEY 未设置".

修复: 4 级 fallback + ANTHROPIC_API_KEY/AUTH_TOKEN 任一即可.

P0-6: 环境变量读取集中到 _get_environ() helper, 接受可选 environ dict.
"""
from __future__ import annotations

import os


def _get_environ(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Return environ dict for runtime detection queries.

    Args:
        environ: Optional injected dict (testing); defaults to os.environ.
    """
    if environ is not None:
        return environ
    # Avoid importing RuntimeConfig here to prevent circular imports in
    # low-level utility modules.  Runtime detection must read the real
    # process environment, not a test-injected config.
    return dict(os.environ)


def detect_plugin_mode(environ: dict[str, str] | None = None) -> bool:
    env = _get_environ(environ)
    if env.get("CLAUDE_CODE"):
        return True
    if env.get("CLAUDE_CODE_ENTRYPOINT"):
        return True
    if "claude" in env.get("ANTHROPIC_CLI", "").lower():
        return True
    return bool(env.get("ANTHROPIC_AUTH_TOKEN"))


def detect_plugin_mode_detail(environ: dict[str, str] | None = None) -> tuple[bool, str]:
    env = _get_environ(environ)
    if env.get("CLAUDE_CODE"):
        return (True, "CLAUDE_CODE")
    if env.get("CLAUDE_CODE_ENTRYPOINT"):
        return (True, "CLAUDE_CODE_ENTRYPOINT")
    if "claude" in env.get("ANTHROPIC_CLI", "").lower():
        return (True, "ANTHROPIC_CLI (claude substring)")
    if env.get("ANTHROPIC_AUTH_TOKEN"):
        return (True, "ANTHROPIC_AUTH_TOKEN")
    return (False, "no plugin signal")


def has_llm_credentials(environ: dict[str, str] | None = None) -> bool:
    env = _get_environ(environ)
    api_key = env.get("ANTHROPIC_API_KEY", "").strip()
    auth_token = env.get("ANTHROPIC_AUTH_TOKEN", "").strip()
    return bool(api_key or auth_token)


def is_llm_available(environ: dict[str, str] | None = None) -> bool:
    """v5.4 审计 P1-9: LLM 是否可用 (agent 模式有 AUTH_TOKEN 或有 API KEY)."""
    return detect_plugin_mode(environ) or has_llm_credentials(environ)
