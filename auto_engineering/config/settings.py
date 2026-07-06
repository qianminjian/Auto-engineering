"""Settings — 配置加载.

v5.0 final: 保留 main 分支的 Settings 设计 (不含 anthropic_api_key, SDK 自动从 env 读).
保留 v5.0-plugin-loop-final 的 plugin_mode 4 级 fallback 检查 (错误信息改进).

设计原则:
    Settings 存 6 个非敏感字段 (model, checkpoint_dir, max_steps, max_tool_calls,
    retry_*, path). ANTHROPIC_API_KEY/AUTH_TOKEN 不在 Settings (v5.0 §B11.3 文档),
    由 anthropic SDK 在实际 LLM 调用时从 env 自动读.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from auto_engineering.errors import AEError, ErrorCode


@dataclass
class Settings:
    """v5.0 6 字段配置 (除 ANTHROPIC_API_KEY 之外所有配置)."""

    anthropic_model: str = "claude-sonnet-4-6"
    checkpoint_dir: str = ".ae-state"
    max_steps: int = 50
    max_tool_calls: int = 10
    retry_max_attempts: int = 3
    retry_timeout: float = 120.0

    @classmethod
    def from_env(cls) -> "Settings":
        """从环境变量加载 Settings (除 ANTHROPIC_API_KEY 之外所有配置).

        2026-07-04 v5.0 final 整合: 4 级 fallback plugin_mode 检查
        (CLAUDE_CODE / CLAUDE_CODE_ENTRYPOINT / ANTHROPIC_CLI 含 'claude' /
        ANTHROPIC_AUTH_TOKEN), 错误信息 plugin mode 零配置原则.

        ANTHROPIC_API_KEY 不在 Settings, 由 anthropic SDK 自动从 env 读.
        """
        from auto_engineering.utils.plugin_mode import is_llm_available
        anthropic_model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6").strip()
        checkpoint_dir = os.environ.get("AE_CHECKPOINT_DIR", ".ae-state").strip()
        max_steps = int(os.environ.get("AE_MAX_STEPS", "50").strip())
        max_tool_calls = int(os.environ.get("AE_MAX_TOOL_CALLS", "10").strip())
        retry_max_attempts = int(os.environ.get("AE_RETRY_MAX_ATTEMPTS", "3").strip())
        retry_timeout = float(os.environ.get("AE_RETRY_TIMEOUT", "120.0").strip())

        if not is_llm_available():
            raise AEError(
                ErrorCode.CONFIG_MISSING_API_KEY,
                "环境变量 ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN 未设置。"
                "Plugin mode (Claude Code agent 内) 应零配置, 由 Claude Code OAuth 自动注入 ANTHROPIC_AUTH_TOKEN. "
                "CLI 调试模式需手动 export ANTHROPIC_API_KEY=sk-..."
            )

        return cls(
            anthropic_model=anthropic_model,
            checkpoint_dir=checkpoint_dir,
            max_steps=max_steps,
            max_tool_calls=max_tool_calls,
            retry_max_attempts=retry_max_attempts,
            retry_timeout=retry_timeout,
        )


__all__ = ["Settings"]
