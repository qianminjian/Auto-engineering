"""全局配置 — v3.0 §八 8.1 Settings dataclass.

核心类:
    Settings            — 全局配置 dataclass（10 字段）
    Settings.from_env() — 从环境变量加载;缺 API key 抛 CONFIG_MISSING_API_KEY
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from auto_engineering.errors import AEError, ErrorCode


@dataclass
class Settings:
    """项目级配置。从环境变量加载(v3.0 §八 8.1)."""

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    checkpoint_dir: str = ".ae-checkpoints"
    max_steps: int = 10
    max_tool_calls: int = 10
    retry_max_attempts: int = 3
    retry_timeout: float = 120.0

    @classmethod
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
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        # v2.5 修复: 在 Claude Code 等 LLM agent 环境下允许无 API key (agent 有自己的 auth)
        in_llm_agent = bool(os.environ.get("CLAUDE_CODE"))
        if not api_key and not in_llm_agent:
            raise AEError(
                ErrorCode.CONFIG_MISSING_API_KEY,
                "环境变量 ANTHROPIC_API_KEY 未设置。请在 ~/.zshrc 或 .env 中设置后再运行。",
            )
        return cls(
            anthropic_api_key=api_key,
            anthropic_model=os.environ.get("ANTHROPIC_MODEL", cls.anthropic_model),
            checkpoint_dir=os.environ.get("AE_CHECKPOINT_DIR", cls.checkpoint_dir),
            max_steps=_int_env("AE_MAX_STEPS", cls.max_steps),
            max_tool_calls=_int_env("AE_MAX_TOOL_CALLS", cls.max_tool_calls),
            retry_max_attempts=_int_env("AE_RETRY_MAX_ATTEMPTS", cls.retry_max_attempts),
            retry_timeout=_float_env("AE_RETRY_TIMEOUT", cls.retry_timeout),
        )


def _int_env(name: str, default: int) -> int:
    """读取整数环境变量，解析失败抛 CONFIG_INVALID_VALUE."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise AEError(
            ErrorCode.CONFIG_INVALID_VALUE,
            f"环境变量 {name}={raw!r} 不是合法整数",
        ) from e


def _float_env(name: str, default: float) -> float:
    """读取浮点环境变量，解析失败抛 CONFIG_INVALID_VALUE."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as e:
        raise AEError(
            ErrorCode.CONFIG_INVALID_VALUE,
            f"环境变量 {name}={raw!r} 不是合法浮点数",
        ) from e


# 全局单例 — 模块导入时用 from_env() 延迟初始化（避免 import 阶段就强依赖 API key）
# 调用方应在 main 入口显式调用 Settings.from_env() 填充
settings = Settings()
