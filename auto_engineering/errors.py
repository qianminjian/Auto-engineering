"""ErrorCode 体系 + AEError 异常族.

参考 LangGraph `errors.py` + AutoGen 异常分类。
P2-B: 清理注释, 标注每个错误码"在何处抛出, 由谁触发".
"""

from __future__ import annotations
from enum import Enum


class ErrorCode(Enum):
    """结构化错误码 (P2-B: 16/22 实际抛出, 6 预留).

    格式: 错误码 = "ERROR_CODE"  # 抛出点 → 触发条件
    """

    # ── Checkpoint (engine/checkpoint.py, loop/checkpoint.py) ──
    CHECKPOINT_SAVE_FAILED = "CHECKPOINT_SAVE_FAILED"  # CheckpointStore.save() → SQLite write 失败
    CHECKPOINT_LOAD_FAILED = "CHECKPOINT_LOAD_FAILED"  # CheckpointStore.load() → SQLite read 失败

    # ── LLM / API (anthropic_provider.py, semantic_evaluator.py) ──
    LLM_TIMEOUT = "LLM_TIMEOUT"  # AnthropicProvider.create_message → 网络超时
    LLM_MAX_RETRIES = "LLM_MAX_RETRIES"  # AnthropicProvider.create_message → 超过 max_retries

    # ── Guardrail (gates/builtin.py, engine/loop.py) ──
    GUARDRAIL_BLOCKED = "GUARDRAIL_BLOCKED"  # Guardrail.check() action='block' → 中止 Stage
    GUARDRAIL_RETRY = "GUARDRAIL_RETRY"  # Guardrail.check() action='retry' → 重试 Stage

    # ── Stage / Loop (engine/loop.py) ──
    STAGE_RETRY_EXCEEDED = "STAGE_RETRY_EXCEEDED"  # LoopEngine.run() → Stage 重试超限
    MAX_TOOL_CALLS_EXCEEDED = "MAX_TOOL_CALLS_EXCEEDED"  # BaseAgent.execute() → 工具循环超限
    INVALID_AGENT_OUTPUT = "INVALID_AGENT_OUTPUT"  # BaseAgent._parse_final_response() → JSON 解析失败
    GRAPH_RECURSION_LIMIT = "GRAPH_RECURSION_LIMIT"  # StageGraph → 递归/无限循环

    # ── Task / Cancellation ──
    TASK_NOT_FOUND = "TASK_NOT_FOUND"  # StageGraph → task 不在 DAG 中
    TASK_CANCELLED = "TASK_CANCELLED"  # CancellationToken.check() → 用户 Ctrl-C
    AGENT_REGISTRATION_ERROR = "AGENT_REGISTRATION_ERROR"  # AgentRuntime → agent_type 未注册
    OUTPUT_DROPPED = "OUTPUT_DROPPED"  # Guardrail action='drop' → 静默丢弃输出

    # ── Configuration (config/settings.py, cli.py) ──
    CONFIG_MISSING_API_KEY = "CONFIG_MISSING_API_KEY"  # Settings.from_env() → 缺 ANTHROPIC_API_KEY
    CONFIG_INVALID_VALUE = "CONFIG_INVALID_VALUE"  # Settings 校验 → 非法配置值

    # ── Budget / Token tracking ──
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"  # TokenTracker.add() → 超 max_tokens

    # ── reserved: LLM errors (P1.3 规划, 尚未实际抛出) ──
    LLM_NETWORK_ERROR = "LLM_NETWORK_ERROR"  # 预留: AnthropicProvider.create_message → 网络断开
    LLM_INVALID_RESPONSE = "LLM_INVALID_RESPONSE"  # 预留: parser → 非 JSON 响应
    LLM_AUTH_ERROR = "LLM_AUTH_ERROR"  # 预留: AnthropicProvider.create_message → 401
    LLM_RATE_LIMIT = "LLM_RATE_LIMIT"  # 预留: AnthropicProvider.create_message → 429 (已由 retry 处理)
    LLM_UNKNOWN_ERROR = "LLM_UNKNOWN_ERROR"  # 预留: AnthropicProvider.create_message → 未知

    # ── v2.0 multi-agent ──
    CONTRACT_REJECTED = "CONTRACT_REJECTED"  # BaseAgent.contract_gate → Gate 拒绝 task


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
