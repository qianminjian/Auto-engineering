"""Settings — 配置加载.

环境变量映射 (除 ANTHROPIC_API_KEY 之外):
    ANTHROPIC_MODEL         → anthropic_model (默认 claude-sonnet-4-6)
    AE_CHECKPOINT_DIR       → checkpoint_dir
    AE_MAX_STEPS            → max_steps
    AE_MAX_TOOL_CALLS       → max_tool_calls
    AE_RETRY_MAX_ATTEMPTS   → retry_max_attempts
    AE_RETRY_TIMEOUT        → retry_timeout

ANTHROPIC_API_KEY 不在 Settings:
    v5.0 是 Claude Code Plugin, 在 agent 中运行. Anthropic SDK 实际调用时
    自动从 env 读 key (由 Claude Code 注入, 不需用户单独 export).
    CLI 调试模式也直接用 SDK 默认 key 读取.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from auto_engineering.errors import AEError, ErrorCode


@dataclass
class Settings:
    anthropic_model: str = "claude-sonnet-4-6"
    checkpoint_dir: str = ".ae-state"
    max_steps: int = 50
    max_tool_calls: int = 10
    retry_max_attempts: int = 3
    retry_timeout: float = 120.0

    @classmethod
<<<<<<< HEAD
    def from_env(cls) -> Settings:
        """从环境变量加载 Settings.

        环境变量映射:
            ANTHROPIC_API_KEY         → anthropic_api_key (必填)
            ANTHROPIC_MODEL           → anthropic_model
            AE_CHECKPOINT_DIR         → checkpoint_dir
            AE_MAX_STEPS              → max_steps
            AE_MAX_TOOL_CALLS         → max_tool_calls
            AE_RETRY_MAX_ATTEMPTS     → retry_max_attempts
            AE_RETRY_TIMEOUT          → retry_timeout

        Returns:
            填充了环境变量值的 Settings 实例.

        Raises:
            AEError(CONFIG_MISSING_API_KEY): ANTHROPIC_API_KEY 未设置或为空.
        """
        # 2026-07-04 修复 (prismscan 真实 bug): 用 4 级 fallback detect_plugin_mode
        # + has_llm_credentials (检查 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN 任一).
        # 旧实现只检查 ANTHROPIC_API_KEY + 1 级 plugin mode (CLAUDE_CODE),
        # 漏 CLAUDE_CODE_ENTRYPOINT + ANTHROPIC_CLI + ANTHROPIC_AUTH_TOKEN
        # (prismscan 实际 env).
        from auto_engineering.utils.plugin_mode import detect_plugin_mode, has_llm_credentials
        # 2026-07-04 修复: Settings 加 anthropic_api_key 字段 (兼容 detect_plugin_mode 决策).
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip() or os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip()
        if not api_key and not detect_plugin_mode():
            raise AEError(
                ErrorCode.CONFIG_MISSING_API_KEY,
                "环境变量 ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN 未设置。Plugin mode (Claude Code agent 内) 应零配置, 由 Claude Code OAuth 自动注入 ANTHROPIC_AUTH_TOKEN. CLI 调试模式需手动 export ANTHROPIC_API_KEY=sk-...",
            )
=======
    def from_env(cls) -> "Settings":
        """从环境变量加载 Settings (除 ANTHROPIC_API_KEY 之外所有配置)."""
        anthropic_model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6").strip()
        checkpoint_dir = os.environ.get("AE_CHECKPOINT_DIR", ".ae-state").strip()
        max_steps = int(os.environ.get("AE_MAX_STEPS", "50").strip())
        max_tool_calls = int(os.environ.get("AE_MAX_TOOL_CALLS", "10").strip())
        retry_max_attempts = int(os.environ.get("AE_RETRY_MAX_ATTEMPTS", "3").strip())
        retry_timeout = float(os.environ.get("AE_RETRY_TIMEOUT", "120.0").strip())
>>>>>>> origin/main
        return cls(
            anthropic_model=anthropic_model,
            checkpoint_dir=checkpoint_dir,
            max_steps=max_steps,
            max_tool_calls=max_tool_calls,
            retry_max_attempts=retry_max_attempts,
            retry_timeout=retry_timeout,
        )
