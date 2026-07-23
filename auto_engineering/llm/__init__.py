"""llm package — LLM provider 抽象."""

from auto_engineering.providers.base import LLMResponse, ToolUseBlock

from .anthropic_provider import AnthropicProvider

# P0-4: 旧 LLMResponse (anthropic_provider) 已废弃，统一使用 providers.base.LLMResponse
# 保留旧导出仅用于向后兼容，新代码应从 providers.base 导入
__all__ = ["AnthropicProvider", "LLMResponse", "ToolUseBlock"]
