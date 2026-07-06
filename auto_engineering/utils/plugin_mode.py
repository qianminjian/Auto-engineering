"""Plugin mode 4 级 fallback (v5.0 bug 修复, 2026-07-04).

prismscan 实际环境 CLAUDE_CODE_ENTRYPOINT=cli + ANTHROPIC_AUTH_TOKEN,
但 v5.0 preflight 只检查 CLAUDE_CODE + ANTHROPIC_CLI, 漏 2 级 fallback.
导致 plugin mode 用户误报 "ANTHROPIC_API_KEY 未设置".

修复: 4 级 fallback + ANTHROPIC_API_KEY/AUTH_TOKEN 任一即可.
"""
from __future__ import annotations

import os


def detect_plugin_mode() -> bool:
    if os.environ.get("CLAUDE_CODE"):
        return True
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT"):
        return True
    anthropic_cli = os.environ.get("ANTHROPIC_CLI", "").lower()
    if "claude" in anthropic_cli:
        return True
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return False


def detect_plugin_mode_detail():
    if os.environ.get("CLAUDE_CODE"):
        return (True, "CLAUDE_CODE")
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT"):
        return (True, "CLAUDE_CODE_ENTRYPOINT")
    anthropic_cli = os.environ.get("ANTHROPIC_CLI", "").lower()
    if "claude" in anthropic_cli:
        return (True, "ANTHROPIC_CLI (claude substring)")
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return (True, "ANTHROPIC_AUTH_TOKEN")
    return (False, "no plugin signal")


def has_llm_credentials() -> bool:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip()
    return bool(api_key or auth_token)


def is_llm_available() -> bool:
    """v5.4 审计 P1-9: LLM 是否可用 (agent 模式有 AUTH_TOKEN 或有 API KEY)."""
    return detect_plugin_mode() or has_llm_credentials()
