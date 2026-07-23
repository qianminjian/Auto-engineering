"""Provider package — LLM backend abstraction layer.

V8-3: Provider Protocol + AnthropicProvider adapter.
V8-4: OpenAIProvider (to be added).
"""

from auto_engineering.providers.base import LLMProvider, LLMResponse, ToolUseBlock

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "ToolUseBlock",
    # Concrete providers — available when optional deps installed
    "AnthropicProvider",
    "GLMProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "QwenProvider",
]

# Lazy imports for concrete providers (optional deps)
def __getattr__(name: str):
    if name == "AnthropicProvider":
        from auto_engineering.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider
    if name == "GLMProvider":
        from auto_engineering.providers.glm import GLMProvider
        return GLMProvider
    if name == "OllamaProvider":
        from auto_engineering.providers.ollama import OllamaProvider
        return OllamaProvider
    if name == "OpenAIProvider":
        from auto_engineering.providers.openai_provider import OpenAIProvider
        return OpenAIProvider
    if name == "QwenProvider":
        from auto_engineering.providers.qwen import QwenProvider
        return QwenProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
