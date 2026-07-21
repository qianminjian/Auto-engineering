"""TokenTracker — LLM token 消耗累加与预算控制.

2026-07-21 P1-6: 从 cli/helpers.py 提取, 消除 loop→CLI 依赖倒置.
TokenTracker 是共享引擎资源 (Agent/Standalone 双驱动均使用).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from auto_engineering.errors import AEError, ErrorCode


@dataclass
class TokenTracker:
    """累加 LLM 调用的 token 消耗, 超阈值抛 BUDGET_EXCEEDED.

    支持 input_tokens + output_tokens 累加; mock-friendly (duck-typing on .usage).
    """

    max_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, response: object) -> None:
        """累加 LLMResponse.usage 中的 token. 超阈值抛 AEError(BUDGET_EXCEEDED)."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return

        # Support both dict usage (providers.base.LLMResponse) and
        # object usage (legacy anthropic_provider.LLMResponse / LLMUsage).
        if isinstance(usage, dict):
            in_t = usage.get("input_tokens", 0) or 0
            out_t = usage.get("output_tokens", 0) or 0
        else:
            in_t = getattr(usage, "input_tokens", 0) or 0
            out_t = getattr(usage, "output_tokens", 0) or 0
        self.input_tokens += in_t
        self.output_tokens += out_t

        if self.max_tokens > 0 and self.total_tokens > self.max_tokens:
            raise AEError(
                ErrorCode.BUDGET_EXCEEDED,
                f"Token budget exceeded: {self.total_tokens} > {self.max_tokens}",
                suggestion="请增大 --max-tokens 参数或缩小需求范围",
            )
