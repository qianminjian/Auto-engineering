"""Plugin mode 检测共用模块 (Bug 4 修复, 2026-07-04).

v5.0 Plugin 在 Claude Code agent 内运行, 通过 OAuth 注入 ANTHROPIC_AUTH_TOKEN.
与 CLI 调试模式 (需要 ANTHROPIC_API_KEY) 不同.

修复前: doctor / agent.run_agent / (旧版) preflight 各有独立的 plugin mode
判定, 逻辑不同步 → doctor 通过但 dev-loop preflight 失败 / agent.run_agent
误判 → 0 代码改动退出.

修复后: 单一 detect_plugin_mode() 函数, 三处共用.

判定优先级 (任一为真即视为 plugin mode):
    0. CLAUDE_CODE 环境变量已设置 (Claude Code 主进程显式标记)
    1. CLAUDE_CODE_ENTRYPOINT 环境变量已设置 (Claude Code 子进程入口)
    2. ANTHROPIC_CLI 含 "claude" 子串 (Claude Code CLI 调用)
    3. ANTHROPIC_AUTH_TOKEN 已设置 (OAuth 注入, plugin 模式的最终判定信号)
"""

from __future__ import annotations

import os


def detect_plugin_mode() -> bool:
    """检测是否在 Claude Code Plugin 模式运行.

    Returns:
        True = plugin 模式 (Claude Code agent 内, OAuth 注入 key)
        False = CLI 调试模式 (需要 ANTHROPIC_API_KEY)

    4 级 fallback (任一为真即返回 True):
        0. CLAUDE_CODE 环境变量
        1. CLAUDE_CODE_ENTRYPOINT 环境变量
        2. ANTHROPIC_CLI 含 "claude"
        3. ANTHROPIC_AUTH_TOKEN 已设置
    """
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


def detect_plugin_mode_detail() -> tuple[bool, str]:
    """detect_plugin_mode() 详细版本, 返回触发的具体信号 (用于日志/debug).

    Returns:
        (True/False, 触发信号名 / "no plugin signal")
    """
    if os.environ.get("CLAUDE_CODE"):
        return True, "CLAUDE_CODE"
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT"):
        return True, "CLAUDE_CODE_ENTRYPOINT"
    anthropic_cli = os.environ.get("ANTHROPIC_CLI", "").lower()
    if "claude" in anthropic_cli:
        return True, "ANTHROPIC_CLI (claude substring)"
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True, "ANTHROPIC_AUTH_TOKEN"
    return False, "no plugin signal"


def has_llm_credentials() -> bool:
    """检查是否有可用的 LLM 凭据 (Plugin OAuth 或 CLI API key).

    用于 fail-fast: 无凭据时不调 LLM, 直接报失败结果.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    return bool(api_key)


__all__ = [
    "detect_plugin_mode",
    "detect_plugin_mode_detail",
    "has_llm_credentials",
]