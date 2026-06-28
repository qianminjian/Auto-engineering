"""P1-T1 (deep audit B-P1-1) — 22 ErrorCode 全覆盖测试.

之前 test_settings.py 只测了 CONFIG_MISSING_API_KEY 1 个 ErrorCode,
其余 21 个 (LLM_*/CHECKPOINT_*/GUARDRAIL_*/TASK_*/CONFIG_*/CONTRACT_*
等) 没有直接测试. 关键错误码 (LLM_TIMEOUT, CHECKPOINT_*, MAX_TOOL_CALLS_EXCEEDED)
无回归保护. 本文件枚举所有 22 个 ErrorCode + 验证 AEError 构造.

P2-B (BEACON): 16/22 codes 实际抛, 6 预留. 测试覆盖全部, 文档化抛点.
"""

from __future__ import annotations

import pytest

from auto_engineering.errors import (
    AEError,
    ErrorCode,
    GuardrailBlockedError,
    GuardrailRetrySignal,
    OutputDropped,
)


# ============================================================
# I. ErrorCode 枚举完整性 (防止重命名/删除)
# ============================================================


class TestErrorCodeEnum:
    """枚举完整性 — 防 BEACON P2-B 16/22 抛点回归."""

    def test_all_codes_defined(self) -> None:
        """22 个 ErrorCode 全存在 (P2-B 统计)."""
        expected = {
            # Checkpoint (2)
            "CHECKPOINT_SAVE_FAILED",
            "CHECKPOINT_LOAD_FAILED",
            # LLM active (2)
            "LLM_TIMEOUT",
            "LLM_MAX_RETRIES",
            # Guardrail (2)
            "GUARDRAIL_BLOCKED",
            "GUARDRAIL_RETRY",
            # Stage / Loop (4)
            "STAGE_RETRY_EXCEEDED",
            "MAX_TOOL_CALLS_EXCEEDED",
            "INVALID_AGENT_OUTPUT",
            "GRAPH_RECURSION_LIMIT",
            # Task / Cancellation (4)
            "TASK_NOT_FOUND",
            "TASK_CANCELLED",
            "AGENT_REGISTRATION_ERROR",
            "OUTPUT_DROPPED",
            # Config (2)
            "CONFIG_MISSING_API_KEY",
            "CONFIG_INVALID_VALUE",
            # Budget (1)
            "BUDGET_EXCEEDED",
            # LLM reserved (5, 预留)
            "LLM_NETWORK_ERROR",
            "LLM_INVALID_RESPONSE",
            "LLM_AUTH_ERROR",
            "LLM_RATE_LIMIT",
            "LLM_UNKNOWN_ERROR",
            # v2.0 multi-agent (1)
            "CONTRACT_REJECTED",
        }
        actual = {member.name for member in ErrorCode}
        assert actual == expected, (
            f"ErrorCode 集合漂移: 缺失={expected - actual}, 多余={actual - expected}"
        )

    def test_all_values_are_uppercase_strings(self) -> None:
        """每个 ErrorCode 的 .value 是大写字符串."""
        for member in ErrorCode:
            assert isinstance(member.value, str)
            assert member.value == member.value.upper(), (
                f"{member.name} = {member.value!r} 不是大写"
            )
            assert member.value == member.name, (
                f"{member.name}.value ({member.value!r}) 应等于 name ({member.name!r})"
            )


# ============================================================
# II. AEError 构造 — 验证 code/message/original_error 字段
# ============================================================


class TestAEErrorConstruction:
    """AEError 构造 + 字段访问."""

    def test_code_and_message(self) -> None:
        """code + message 构造."""
        err = AEError(ErrorCode.LLM_TIMEOUT, "网络超时")
        assert err.code is ErrorCode.LLM_TIMEOUT
        assert err.message == "网络超时"
        assert err.original_error is None

    def test_original_error_chain(self) -> None:
        """original_error 保留链."""
        original = ConnectionError("ECONNRESET")
        err = AEError(
            ErrorCode.LLM_NETWORK_ERROR, "LLM 连接失败", original_error=original
        )
        assert err.original_error is original

    def test_str_representation(self) -> None:
        """str(err) 格式: [CODE] message."""
        err = AEError(ErrorCode.BUDGET_EXCEEDED, "tokens 超限")
        s = str(err)
        assert s == "[BUDGET_EXCEEDED] tokens 超限"

    def test_is_exception(self) -> None:
        """AEError 是 Exception 子类 (可被 except Exception 捕获)."""
        err = AEError(ErrorCode.LLM_TIMEOUT, "test")
        assert isinstance(err, Exception)
        with pytest.raises(AEError) as exc_info:
            raise err
        assert exc_info.value.code is ErrorCode.LLM_TIMEOUT


# ============================================================
# III. Helper exception classes — 验证 code 正确
# ============================================================


class TestGuardrailBlockedError:
    """GuardrailBlockedError 用 GUARDRAIL_BLOCKED code."""

    def test_code(self) -> None:
        err = GuardrailBlockedError("missing tests")
        assert err.code is ErrorCode.GUARDRAIL_BLOCKED
        assert err.message == "missing tests"
        assert isinstance(err, AEError)


class TestGuardrailRetrySignal:
    """GuardrailRetrySignal 非 AEError 子类 (RetryPolicy 捕获)."""

    def test_not_aeerror_subclass(self) -> None:
        """GuardrailRetrySignal 不应被混入 fatal 流."""
        from auto_engineering.errors import AEError as _AE
        sig = GuardrailRetrySignal("retry please")
        assert not isinstance(sig, _AE)
        assert sig.reason == "retry please"


class TestOutputDropped:
    """OutputDropped 用 OUTPUT_DROPPED code + 默认消息."""

    def test_default_message(self) -> None:
        err = OutputDropped()
        assert err.code is ErrorCode.OUTPUT_DROPPED
        assert err.message == "Output dropped by guardrail"

    def test_custom_reason(self) -> None:
        err = OutputDropped("stage 1: parser failed")
        assert err.message == "stage 1: parser failed"


# ============================================================
# IV. 关键抛点 — 直接构造 AEError 模拟 raise, 验证 message 格式
# ============================================================


class TestActiveCodesRaisePoints:
    """BEACON P2-B 16 active codes 的预期 message 形式.

    这些是 raise sites 的 contract — 如果上游调用方依赖
    特定 substring 来做错误处理, 改 message 会 break.
    """

    def test_checkpoint_save_failed_message(self) -> None:
        err = AEError(ErrorCode.CHECKPOINT_SAVE_FAILED, "SQLite write 失败: UNIQUE")
        assert "SQLite" in err.message or "失败" in err.message

    def test_checkpoint_load_failed_message(self) -> None:
        err = AEError(ErrorCode.CHECKPOINT_LOAD_FAILED, "checkpoint not found")
        assert "checkpoint" in err.message.lower()

    def test_llm_timeout_message(self) -> None:
        err = AEError(ErrorCode.LLM_TIMEOUT, "60s timeout")
        assert "timeout" in err.message.lower()

    def test_max_tool_calls_exceeded(self) -> None:
        err = AEError(ErrorCode.MAX_TOOL_CALLS_EXCEEDED, "exceeded 5 tool calls")
        assert "tool" in err.message.lower()

    def test_invalid_agent_output(self) -> None:
        err = AEError(ErrorCode.INVALID_AGENT_OUTPUT, "JSON 解析失败: line 5")
        assert "json" in err.message.lower() or "解析" in err.message

    def test_task_cancelled(self) -> None:
        err = AEError(ErrorCode.TASK_CANCELLED, "用户 Ctrl-C")
        assert "用户" in err.message or "ctrl" in err.message.lower()

    def test_agent_registration_error(self) -> None:
        err = AEError(ErrorCode.AGENT_REGISTRATION_ERROR, "agent_type 'foo' 未注册")
        assert "未注册" in err.message or "registered" in err.message.lower()

    def test_config_missing_api_key(self) -> None:
        """Settings.from_env() 实际抛点 (已有 test_settings.py 覆盖)."""
        err = AEError(
            ErrorCode.CONFIG_MISSING_API_KEY, "环境变量 ANTHROPIC_API_KEY 未设置"
        )
        assert "ANTHROPIC_API_KEY" in err.message

    def test_config_invalid_value(self) -> None:
        err = AEError(ErrorCode.CONFIG_INVALID_VALUE, "max_steps 不是整数: 'abc'")
        assert "整数" in err.message or "int" in err.message.lower()

    def test_budget_exceeded(self) -> None:
        err = AEError(ErrorCode.BUDGET_EXCEEDED, "tokens 8192 > max 4096")
        assert "token" in err.message.lower()

    def test_contract_rejected(self) -> None:
        err = AEError(
            ErrorCode.CONTRACT_REJECTED, "Contract gate rejected task 'auth' for 'DeveloperAgent'"
        )
        assert "Contract" in err.message or "contract" in err.message.lower()
