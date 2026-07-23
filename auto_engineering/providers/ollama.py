"""OllamaProvider — Ollama local LLM backend implementing LLMProvider Protocol.

Design ref: v5.6-Design-Loop.md appendix E §E.5.1 (T55).

Ollama exposes an OpenAI-compatible API at http://localhost:11434/v1.
This provider reuses the Anthropic↔OpenAI tool schema conversion from
_openai_adapters.py and targets the Ollama base URL by default.

Bank intranet P0: offline deployment without external API dependencies.
"""

from __future__ import annotations

from auto_engineering.providers._openai_compatible_base import OpenAICompatibleProvider

_OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434/v1"
_OLLAMA_DEFAULT_MODEL = "llama3"


class OllamaProvider(OpenAICompatibleProvider):
    """Ollama local LLM client implementing LLMProvider Protocol.

    Uses the OpenAI-compatible API exposed by Ollama at /v1.
    Anthropic↔OpenAI schema conversion is transparent.
    """

    _FINISH_REASON_MAP: dict[str, str] = {
        "stop": "end_turn",
        "tool_calls": "tool_use",
        "length": "max_tokens",
        "content_filter": "content_filter",
    }
    _DEFAULT_MODEL: str = _OLLAMA_DEFAULT_MODEL

    def __init__(
        self,
        api_key: str = "ollama",
        base_url: str = _OLLAMA_DEFAULT_BASE_URL,
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url)
