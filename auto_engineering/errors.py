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
    CONFIG_INVALID_PROVIDER = "CONFIG_INVALID_PROVIDER"  # providers/factory.py: 无法确定 LLM provider

    # ── PII ──
    PII_DETECTED = "PII_DETECTED"  # pii/redactor.py: block_mode 下检测到 CRITICAL PII

    # ── Budget ──
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"  # TokenTracker.add() → 超 max_tokens

    # ── Gate ──
    # Phase 40: GATE_EXECUTION_ERROR removed — dead code, never raised
    # Gate errors use generic except Exception in gates/runner.py

# v5.4 审计 P1-2+P1-3 已删除 (2026-07-06):
#   异常类: GuardrailBlockedError, GuardrailRetrySignal, OutputDropped
#   ErrorCode: CHECKPOINT_SAVE_FAILED, CHECKPOINT_LOAD_FAILED, LLM_MAX_RETRIES,
#   CONFIG_INVALID_VALUE, CONTRACT_REJECTED, STAGE_RETRY_EXCEEDED,
#   GRAPH_RECURSION_LIMIT, TASK_NOT_FOUND
#   均为 v5.4 审计确认为从未 raise/使用的死代码.

# P2-12: ErrorCode → 默认建议映射 (AEError 构造时自动查阅)
_SUGGESTIONS: dict[str, str] = {
    "LLM_TIMEOUT": "检查网络连接或增大 API 超时时间",
    "LLM_NETWORK_ERROR": "检查网络连接，确认 API 端点可达",
    "LLM_INVALID_RESPONSE": "检查 API key 权限或降低请求复杂度",
    "LLM_AUTH_ERROR": "检查 ANTHROPIC_API_KEY 环境变量是否设置正确",
    "LLM_RATE_LIMIT": "等待 60 秒后重试，或联系 Anthropic 提升额度",
    "LLM_UNKNOWN_ERROR": "查看错误详情日志，联系 API 提供商",
    "MAX_TOOL_CALLS_EXCEEDED": "增大 AE_MAX_TOOL_CALLS 环境变量或简化需求",
    "INVALID_AGENT_OUTPUT": "降低 prompt 复杂度或明确指定输出格式",
    "TOOL_EXECUTION_ERROR": "检查工具执行日志，确认工具调用参数是否正确",
    "TASK_CANCELLED": "任务已被中断，重新提交即可",
    "AGENT_REGISTRATION_ERROR": "确认 Agent role 已在 AgentRuntime 中注册",
    "CONFIG_MISSING_API_KEY": "设置 ANTHROPIC_API_KEY 环境变量后重试",
    "CONFIG_INVALID_PROVIDER": "设置 OLLAMA_HOST 或 ANTHROPIC_API_KEY 等环境变量，或显式传 provider 参数",
    "PII_DETECTED": "检查输入内容中的敏感信息，脱敏后重试",
    "BUDGET_EXCEEDED": "增大 --max-tokens 参数或缩小需求范围",
}


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
        self.suggestion = suggestion if suggestion is not None else _SUGGESTIONS.get(code.value)
        suffix = f" — 建议: {self.suggestion}" if self.suggestion else ""
        super().__init__(f"[{code.value}] {message}{suffix}")


# Phase 40: GateExecutionError removed — dead code, never raised
