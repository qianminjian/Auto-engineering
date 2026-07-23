"""QwenProvider — Alibaba Qwen (通义千问) adapter implementing LLMProvider Protocol.

Design ref: v5.6-Design-Loop.md appendix E §E.5.2 (T58).

DashScope exposes an OpenAI-compatible API at
https://dashscope.aliyuncs.com/compatible-mode/v1.
信创合规 P0 — domestic model support for regulated environments.
"""

from __future__ import annotations

from auto_engineering.providers._openai_compatible_base import OpenAICompatibleProvider

_QWEN_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_QWEN_DEFAULT_MODEL = "qwen-turbo"


class QwenProvider(OpenAICompatibleProvider):
    """Alibaba Qwen (通义千问) client implementing LLMProvider Protocol."""

    _FINISH_REASON_MAP: dict[str, str] = {
        "stop": "end_turn",
        "tool_calls": "tool_use",
        "length": "max_tokens",
    }
    _DEFAULT_MODEL: str = _QWEN_DEFAULT_MODEL

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = _QWEN_DEFAULT_BASE_URL,
    ) -> None:
        from auto_engineering.config.runtime_config import get_default_config

        key = api_key or get_default_config().dashscope_api_key
        super().__init__(api_key=key, base_url=base_url)
