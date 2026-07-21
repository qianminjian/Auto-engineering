"""Provider factory — create LLM provider from name or environment.

V8-4: create_provider() with auto-detection from env vars.
Design ref: v5.6-Design-Loop.md appendix D §4.
"""

from __future__ import annotations

import logging
import os

from auto_engineering.providers.base import LLMProvider

_logger = logging.getLogger("ae.providers.factory")


def create_provider(provider: str = "", *, api_key: str = "") -> LLMProvider:
    """Create LLM provider from name or environment auto-detection.

    Priority:
    1. Explicit provider parameter ("anthropic" / "openai")
    2. AE_LLM_PROVIDER environment variable
    3. Auto-detect in order: OLLAMA_HOST → ZHIPUAI_API_KEY → DASHSCOPE_API_KEY
       → OPENAI_API_KEY → ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN
    4. Neither → raises ValueError

    Note: 多 key 同时设置时，OLLAMA_HOST 优先级最高。
    如需特定 provider，显式传参或用 AE_LLM_PROVIDER 覆盖。
    """
    from auto_engineering.config.runtime_config import get_default_config
    _cfg = get_default_config()

    resolved = provider or _cfg.llm_provider

    if not resolved:
        if _cfg.ollama_host:
            resolved = "ollama"
        elif _cfg.zhipu_api_key:
            resolved = "glm"
        elif _cfg.dashscope_api_key:
            resolved = "qwen"
        elif _cfg.openai_api_key:
            resolved = "openai"
        elif _cfg.anthropic_api_key or _cfg.anthropic_auth_token:
            resolved = "anthropic"
        else:
            raise ValueError(
                "Unknown provider: no provider specified and no API key found. "
                "Set OLLAMA_HOST, ZHIPUAI_API_KEY, DASHSCOPE_API_KEY, "
                "OPENAI_API_KEY, or ANTHROPIC_API_KEY."
            )

    if resolved == "openai":
        from auto_engineering.providers.openai_provider import OpenAIProvider

        key = api_key or _cfg.openai_api_key
        return OpenAIProvider(api_key=key)

    if resolved == "anthropic":
        from auto_engineering.llm.anthropic_provider import AnthropicProvider

        key = api_key or _cfg.anthropic_api_key
        return AnthropicProvider(api_key=key)  # type: ignore[return-value]  # param order differs from Protocol, structural compat at runtime

    if resolved == "ollama":
        from auto_engineering.providers.ollama import OllamaProvider

        return OllamaProvider()

    if resolved == "glm":
        from auto_engineering.providers.glm import GLMProvider

        key = api_key or _cfg.zhipu_api_key
        return GLMProvider(api_key=key)

    if resolved == "qwen":
        from auto_engineering.providers.qwen import QwenProvider

        key = api_key or _cfg.dashscope_api_key
        return QwenProvider(api_key=key)

    raise ValueError(f"Unknown provider: {resolved}")
