"""Plugin mode 4 级 fallback (v5.0 bug 修复, 2026-07-04).

prismscan 实际环境 CLAUDE_CODE_ENTRYPOINT=cli + ANTHROPIC_AUTH_TOKEN,
但 v5.0 preflight 只检查 CLAUDE_CODE + ANTHROPIC_CLI, 漏 2 级 fallback.
导致 plugin mode 用户误报 "ANTHROPIC_API_KEY 未设置".

修复: 4 级 fallback + ANTHROPIC_API_KEY/AUTH_TOKEN 任一即可.

P0-6: 环境变量读取集中到 _get_environ() helper, 接受可选 environ dict.
"""
from __future__ import annotations

import os

from auto_engineering.host import HostPlatform, detect_host


def _get_environ(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Return environ dict for runtime detection queries.

    Args:
        environ: Optional injected dict (testing); defaults to os.environ.
    """
    if environ is not None:
        return environ
    # 有意绕过 RuntimeConfig: 本模块是底层工具, 引入 RuntimeConfig 会形成
    # 循环依赖 (RuntimeConfig → 各模块 → utils → RuntimeConfig)。
    # Runtime detection 必须读取真实进程环境, 不能走可注入的 RuntimeConfig。
    return dict(os.environ)


def detect_plugin_mode(environ: dict[str, str] | None = None) -> bool:
    env = _get_environ(environ)
    if detect_host(env).platform is not HostPlatform.UNKNOWN:
        return True
    # 向后兼容旧 Claude OAuth 子进程；凭据不能用于识别具体 HostPlatform。
    return bool(env.get("ANTHROPIC_AUTH_TOKEN"))


def detect_plugin_mode_detail(environ: dict[str, str] | None = None) -> tuple[bool, str]:
    env = _get_environ(environ)
    detection = detect_host(env)
    if detection.platform is not HostPlatform.UNKNOWN:
        return (True, detection.signal)
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
