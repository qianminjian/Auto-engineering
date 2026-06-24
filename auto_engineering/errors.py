"""ErrorCode 体系 + AEError 异常族.

参考 LangGraph `errors.py` + AutoGen 异常分类。
Phase 1 实际触发: CHECKPOINT_*/GRAPH_RECURSION_LIMIT/AGENT_REGISTRATION_ERROR/TASK_CANCELLED
Phase 2-3 触发: GUARDRAIL_*/LLM_*/STAGE_RETRY_EXCEEDED/INVALID_AGENT_OUTPUT/OUTPUT_DROPPED
v3.0 §十一 过度设计降级: 保留全部枚举值,对应错误分支按 Phase 增量实现。
"""

from enum import Enum


class ErrorCode(Enum):
    """结构化错误码. 排查问题靠 grep 错误消息不可靠,改用 code + message 双字段."""

    CHECKPOINT_SAVE_FAILED = "CHECKPOINT_SAVE_FAILED"
    CHECKPOINT_LOAD_FAILED = "CHECKPOINT_LOAD_FAILED"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_MAX_RETRIES = "LLM_MAX_RETRIES"
    GUARDRAIL_BLOCKED = "GUARDRAIL_BLOCKED"
    GUARDRAIL_RETRY = "GUARDRAIL_RETRY"
    STAGE_RETRY_EXCEEDED = "STAGE_RETRY_EXCEEDED"
    MAX_TOOL_CALLS_EXCEEDED = "MAX_TOOL_CALLS_EXCEEDED"
    INVALID_AGENT_OUTPUT = "INVALID_AGENT_OUTPUT"
    GRAPH_RECURSION_LIMIT = "GRAPH_RECURSION_LIMIT"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    TASK_CANCELLED = "TASK_CANCELLED"
    AGENT_REGISTRATION_ERROR = "AGENT_REGISTRATION_ERROR"
    OUTPUT_DROPPED = "OUTPUT_DROPPED"
    # Configuration errors (Plan B Phase 01)
    CONFIG_MISSING_API_KEY = "CONFIG_MISSING_API_KEY"
    CONFIG_INVALID_VALUE = "CONFIG_INVALID_VALUE"
    # Budget tracking (Plan B Phase 02)
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"


class AEError(Exception):
    """Auto-Engineering 统一异常基类."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        original_error: Exception | None = None,
    ):
        self.code = code
        self.message = message
        self.original_error = original_error
        super().__init__(f"[{code.value}] {message}")


class GuardrailBlockedError(AEError):
    """Guardrail 返回 action='block' 时抛出 — 中止当前 Stage."""

    def __init__(self, reason: str):
        super().__init__(ErrorCode.GUARDRAIL_BLOCKED, reason)


class GuardrailRetrySignal(Exception):
    """Guardrail 返回 action='retry' 时抛出 — loop 重试当前 Stage(非致命异常).

    不继承 AEError 是因为 RetryPolicy 期望捕获后处理,不混入 fatal 流.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class OutputDropped(AEError):
    """Guardrail 返回 action='drop' 时抛出 — 静默丢弃当前 Stage 输出."""

    def __init__(self, reason: str = ""):
        super().__init__(
            ErrorCode.OUTPUT_DROPPED,
            reason or "Output dropped by guardrail",
        )
