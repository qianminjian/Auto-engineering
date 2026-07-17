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
    3. Auto-detect: OPENAI_API_KEY → OpenAIProvider; ANTHROPIC_API_KEY → AnthropicProvider
    4. Neither → raises ValueError
    """
    resolved = provider or os.environ.get("AE_LLM_PROVIDER", "")

    if not resolved:
        if os.environ.get("OPENAI_API_KEY"):
            resolved = "openai"
        elif os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            resolved = "anthropic"
        else:
            raise ValueError(
                "Unknown provider: no provider specified and no API key found. "
                "Set OPENAI_API_KEY or ANTHROPIC_API_KEY."
            )

    if resolved == "openai":
        from auto_engineering.providers.openai_provider import OpenAIProvider

        key = api_key or os.environ.get("OPENAI_API_KEY", "")
        return OpenAIProvider(api_key=key)

    if resolved == "anthropic":
        from auto_engineering.llm.anthropic_provider import AnthropicProvider

        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        return AnthropicProvider(api_key=key)  # type: ignore[return-value]  # param order differs from Protocol, structural compat at runtime

    raise ValueError(f"Unknown provider: {resolved}")
