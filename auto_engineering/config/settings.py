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
    def from_env(cls) -> "Settings":
        """从环境变量加载 Settings (除 ANTHROPIC_API_KEY 之外所有配置)."""
        anthropic_model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6").strip()
        checkpoint_dir = os.environ.get("AE_CHECKPOINT_DIR", ".ae-state").strip()
        max_steps = int(os.environ.get("AE_MAX_STEPS", "50").strip())
        max_tool_calls = int(os.environ.get("AE_MAX_TOOL_CALLS", "10").strip())
        retry_max_attempts = int(os.environ.get("AE_RETRY_MAX_ATTEMPTS", "3").strip())
        retry_timeout = float(os.environ.get("AE_RETRY_TIMEOUT", "120.0").strip())
        return cls(
            anthropic_model=anthropic_model,
            checkpoint_dir=checkpoint_dir,
            max_steps=max_steps,
            max_tool_calls=max_tool_calls,
            retry_max_attempts=retry_max_attempts,
            retry_timeout=retry_timeout,
        )
