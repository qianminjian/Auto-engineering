"""ErrorCode 体系 + AEError 异常族.

参考 LangGraph `errors.py` + AutoGen 异常分类。
P2-B: 清理注释, 标注每个错误码"在何处抛出, 由谁触发".
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(Enum):
    """结构化错误码 (v5.5: 14 个 ErrorCode).

    格式: 错误码 = "ERROR_CODE"  # 抛出点 → 触发条件
    """

    # ── LLM / API (anthropic_provider.py, semantic_evaluator.py, base.py) ──
    LLM_TIMEOUT = "LLM_TIMEOUT"  # base.py:_map_llm_exception → APITimeoutError
    LLM_NETWORK_ERROR = "LLM_NETWORK_ERROR"  # base.py:_map_llm_exception → APIConnectionError
    LLM_INVALID_RESPONSE = "LLM_INVALID_RESPONSE"  # base.py:_map_llm_exception → APIStatusError
    LLM_AUTH_ERROR = "LLM_AUTH_ERROR"  # base.py:_map_llm_exception → AuthenticationError
    LLM_RATE_LIMIT = "LLM_RATE_LIMIT"  # base.py:_map_llm_exception → RateLimitError
    LLM_UNKNOWN_ERROR = "LLM_UNKNOWN_ERROR"  # base.py:_map_llm_exception → 未知异常

    # ── Stage / Loop ──
    MAX_TOOL_CALLS_EXCEEDED = "MAX_TOOL_CALLS_EXCEEDED"  # BaseAgent.execute() → 工具循环超限
    INVALID_AGENT_OUTPUT = "INVALID_AGENT_OUTPUT"  # BaseAgent._parse_final_response() → JSON 解析失败
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"  # BaseAgent.execute() → 工具业务失败 (非 agent 输出问题)

    # ── Task / Cancellation ──
    TASK_CANCELLED = "TASK_CANCELLED"  # CancellationToken.check() → 用户 Ctrl-C
    AGENT_REGISTRATION_ERROR = "AGENT_REGISTRATION_ERROR"  # AgentRuntime → agent_type 未注册
    # ── Configuration ──
    CONFIG_MISSING_API_KEY = "CONFIG_MISSING_API_KEY"  # cli/__init__.py: CLI 模式缺 API key

    # ── Budget ──
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"  # TokenTracker.add() → 超 max_tokens

# v5.4 审计 P1-2+P1-3 已删除 (2026-07-06):
#   异常类: GuardrailBlockedError, GuardrailRetrySignal, OutputDropped
#   ErrorCode: CHECKPOINT_SAVE_FAILED, CHECKPOINT_LOAD_FAILED, LLM_MAX_RETRIES,
#   CONFIG_INVALID_VALUE, CONTRACT_REJECTED, STAGE_RETRY_EXCEEDED,
#   GRAPH_RECURSION_LIMIT, TASK_NOT_FOUND
#   均为 v5.4 审计确认为从未 raise/使用的死代码.


class AEError(Exception):
    """Auto-Engineering 统一异常基类."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        original_error: Exception | None = None,
        suggestion: str | None = None,
    ):
        self.code = code
        self.message = message
        self.original_error = original_error
        self.suggestion = suggestion
        suffix = f" — 建议: {suggestion}" if suggestion else ""
        super().__init__(f"[{code.value}] {message}{suffix}")
