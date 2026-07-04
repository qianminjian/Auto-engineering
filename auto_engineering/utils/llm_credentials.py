"""LLM 凭据统一抽象 (2026-07-04 深度设计, 解决 ANTHROPIC_API_KEY 反复问题).

设计动机:
    prismscan 集成反馈 (2026-07-04) — 用户反复报 "ANTHROPIC_API_KEY 未设置",
    实际上 ae 已正确实现 plugin mode 4 级 fallback (CLAUDE_CODE /
    CLAUDE_CODE_ENTRYPOINT / ANTHROPIC_CLI / ANTHROPIC_AUTH_TOKEN), 但
    错误信息、文档、跨层一致性仍残留 "ANTHROPIC_API_KEY" 单一检查的旧痕迹.

设计原则:
    1. 单一入口: 所有 LLM 凭据解析走 resolve_llm_credentials() 一个函数
    2. 4 级 fallback 与 plugin_mode 一致:
       - 0. 显式参数 (e.g. AnthropicProvider(api_key=...))
       - 1. ANTHROPIC_API_KEY (CLI 调试模式显式 set)
       - 2. ANTHROPIC_AUTH_TOKEN (Claude Code plugin OAuth 注入 / proxy)
       - 3. CLAUDECODE=1 + CLAUDE_CODE_SESSION_ID (Claude Code 子进程 wrapper)
    3. 详细信号名: 返回具体来源 (与 detect_plugin_mode_detail 同模式)
    4. 错误信息区分模式: plugin mode (OAuth 透传) vs CLI 模式 (export)

抽象层 (本模块):
    - LLMCredentials: dataclass 含 token / source / mode (API_KEY / AUTH_TOKEN / EXPLICIT)
    - resolve_llm_credentials(): 4 级 fallback, 返回 (credentials, signal_name)
    - has_llm_credentials(): 便捷 bool 检查 (与 has_llm_credentials(plugin_mode) 同名)
    - credential_source_name(): 信号名 → 可读字符串 (供错误信息)

与 anthropic SDK 对齐:
    - anthropic.Anthropic() 不传参时, SDK 自动读 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN
    - 显式传 auth_token=... 可避免 SDK 默认行为依赖
    - 详情: https://docs.anthropic.com/en/api/client-sdks#authentication
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

_logger = logging.getLogger(__name__)


# =============================================================================
# 常量
# =============================================================================

# 4 级 fallback 优先级 (与 utils/plugin_mode.detect_plugin_mode 对齐)
# 0: 显式参数 (调用方 AnthropicProvider(api_key=...) 传入)
# 1: ANTHROPIC_API_KEY (CLI 调试模式手动 set)
# 2: ANTHROPIC_AUTH_TOKEN (Claude Code plugin OAuth 注入 / 第三方 proxy)
# 3: CLAUDECODE=1 + CLAUDE_CODE_SESSION_ID (Claude Code 子进程 wrapper 标记)
LLM_CREDENTIAL_SOURCES: tuple[str, ...] = (
    "explicit",                  # 调用方显式传入 (api_key=...)
    "ANTHROPIC_API_KEY",         # CLI 调试模式
    "ANTHROPIC_AUTH_TOKEN",      # Plugin OAuth / proxy
    "CLAUDECODE_wrapper",        # Claude Code 子进程 wrapper
)


# =============================================================================
# 数据类
# =============================================================================


@dataclass
class LLMCredentials:
    """LLM 凭据封装.

    Attributes:
        token: 实际凭据值 (API key 或 OAuth token)
        source: 凭据来源 (LLM_CREDENTIAL_SOURCES 之一)
        mode: 运行模式 ("plugin" / "cli" / "wrapper")
    """

    token: str
    source: str
    mode: str = "cli"

    def is_valid(self) -> bool:
        """凭据是否有效 (token 非空)."""
        return bool(self.token and self.token.strip())

    def description(self) -> str:
        """人类可读描述 (供错误信息用)."""
        if self.source == "explicit":
            return f"显式传入 ({self.mode} mode)"
        if self.source == "ANTHROPIC_API_KEY":
            return f"env ANTHROPIC_API_KEY ({self.mode} mode)"
        if self.source == "ANTHROPIC_AUTH_TOKEN":
            return f"env ANTHROPIC_AUTH_TOKEN ({self.mode} mode, OAuth/proxy)"
        if self.source == "CLAUDECODE_wrapper":
            return f"Claude Code wrapper ({self.mode} mode)"
        return f"{self.source} ({self.mode} mode)"


# =============================================================================
# 凭据解析 (核心)
# =============================================================================


def resolve_llm_credentials(
    explicit_token: str | None = None,
) -> tuple[Optional[LLMCredentials], str]:
    """4 级 fallback 解析 LLM 凭据 (返回 (credentials, signal_name)).

    优先级:
        0. explicit_token 非空 → 显式 (api_key=... 调用方传入)
        1. ANTHROPIC_API_KEY env 非空 → CLI 调试模式
        2. ANTHROPIC_AUTH_TOKEN env 非空 → Plugin OAuth / proxy
        3. CLAUDECODE=1 + CLATHROPIC_AUTH_TOKEN → Claude Code wrapper

    Args:
        explicit_token: 调用方显式传入的 token (e.g. AnthropicProvider(api_key=...))
                       优先于所有 env var.

    Returns:
        (LLMCredentials, signal_name) - 找到凭据时, credentials 是 LLMCredentials 实例
                                          未找到凭据时, credentials 是 None, signal_name 是 "no_credential"
    """
    # 优先级 0: 显式参数
    if explicit_token and explicit_token.strip():
        return (
            LLMCredentials(
                token=explicit_token,
                source="explicit",
                mode=_detect_mode(),
            ),
            "explicit",
        )

    # 优先级 1: ANTHROPIC_API_KEY
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        return (
            LLMCredentials(
                token=api_key,
                source="ANTHROPIC_API_KEY",
                mode=_detect_mode(),
            ),
            "ANTHROPIC_API_KEY",
        )

    # 优先级 2: ANTHROPIC_AUTH_TOKEN
    auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip()
    if auth_token:
        return (
            LLMCredentials(
                token=auth_token,
                source="ANTHROPIC_AUTH_TOKEN",
                mode=_detect_mode(),
            ),
            "ANTHROPIC_AUTH_TOKEN",
        )

    # 优先级 3: CLAUDECODE wrapper (Claude Code 子进程, 通常不需)
    if os.environ.get("CLAUDECODE") == "1" and os.environ.get("CLAUDE_CODE_SESSION_ID"):
        # CLAUDECODE=1 但无 token, 表示 Claude Code 自身管理 token
        # 此分支不直接返回 token, 而是由 anthropic SDK 自动管理
        # 标记信号供诊断用
        return (None, "CLAUDECODE_wrapper (no explicit token)")

    # 无任何凭据
    return (None, "no_credential")


def _detect_mode() -> str:
    """检测当前运行模式 (plugin / cli / wrapper).

    Returns:
        "plugin" - Claude Code agent 内 (plugin mode)
        "wrapper" - Claude Code 子进程
        "cli" - 独立 CLI 调试模式 (默认)
    """
    if os.environ.get("CLAUDECODE") == "1" and os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return "wrapper"
    if (
        os.environ.get("CLAUDE_CODE")
        or os.environ.get("CLAUDE_CODE_ENTRYPOINT")
        or os.environ.get("ANTHROPIC_CLI")
    ):
        return "plugin"
    return "cli"


def has_llm_credentials(explicit_token: str | None = None) -> bool:
    """便捷检查: 是否有可用 LLM 凭据 (调用方显式 或 env 4 级 fallback).

    这是 plugin_mode.has_llm_credentials 的统一升级版本.
    优先 ANTHROPIC_API_KEY (CLI 模式), 但 plugin mode 下 ANTHROPIC_AUTH_TOKEN 也算.

    2026-07-04 修复 (深度设计): 之前 plugin_mode.has_llm_credentials() 只检测
    ANTHROPIC_API_KEY, 漏 ANTHROPIC_AUTH_TOKEN. 实际 plugin mode 下
    ANTHROPIC_AUTH_TOKEN 才是主要凭据 (OAuth 注入). 现统一到本模块.
    """
    creds, _ = resolve_llm_credentials(explicit_token=explicit_token)
    return creds is not None and creds.is_valid()


def credential_error_message(
    explicit_token: str | None = None,
    context: str = "agent",
) -> str:
    """生成准确的 LLM 凭据错误信息 (区分 plugin mode vs CLI 模式).

    2026-07-04 修复 (深度设计): 之前错误信息说 "Plugin 应自动注入" 矛盾
    (plugin mode 仍失败时), 实际 plugin mode 已正确处理.
    现按检测到的模式生成准确错误信息 + 修复步骤.
    """
    creds, signal = resolve_llm_credentials(explicit_token=explicit_token)
    mode = _detect_mode()

    if creds is not None:
        return f"LLM 凭据已解析 ({creds.description()})"  # 防御性: 不应走到这

    # 2026-07-04 深度设计 (用户洞察): Plugin mode 用户**零配置**原则.
    # 不要提示"在 ~/.zshrc export"误导, 改为"Plugin mode 应自动工作, 如失败检查 env".
    if mode == "plugin":
        return (
            f"{context} 无可用 LLM 凭据. "
            f"Plugin mode 已启用 (Claude Code agent 内), 应**零配置** — "
            f"ANTHROPIC_AUTH_TOKEN 由 Claude Code OAuth 自动注入. "
            f"如失败检查: `env | grep ANTHROPIC_AUTH_TOKEN` 确认 token 已注入. "
            f"CLI 调试模式 (独立跑) 才需手动 export ANTHROPIC_API_KEY=sk-..."
        )
    elif mode == "wrapper":
        return (
            f"{context} 无可用 LLM 凭据. "
            f"CLAUDECODE wrapper 模式应自动管理 token, 但当前未注入. "
            f"修复步骤:\n"
            f"  1. 确认 Claude Code 版本 ≥ 2.0 (支持 OAuth 透传)\n"
            f"  2. 在 Claude Code agent 内调用 {context}\n"
            f"  3. 或在 ~/.zshrc 中 export ANTHROPIC_API_KEY=sk-..."
        )
    else:  # cli
        return (
            f"{context} 无可用 LLM 凭据. CLI 调试模式需手动设置. "
            f"修复步骤:\n"
            f"  1. 在 ~/.zshrc 中 export ANTHROPIC_API_KEY=sk-...\n"
            f"  2. 或在 .env 中设置 (项目根)\n"
            f"  3. 或调用时传 api_key=... 参数"
        )


__all__ = [
    "LLMCredentials",
    "LLM_CREDENTIAL_SOURCES",
    "resolve_llm_credentials",
    "has_llm_credentials",
    "credential_error_message",
]