"""v5.5 审计后 ErrorCode 全覆盖测试 — 13 ErrorCode + AEError 基类.

v5.5 审计 Round 1: 删除 3 个从未使用的 ErrorCode (GUARDRAIL_BLOCKED,
GUARDRAIL_RETRY, OUTPUT_DROPPED) + 新增 TOOL_EXECUTION_ERROR.

本文件验证剩余 13 ErrorCode + AEError 基类的构造/链式/序列化行为.
"""

from __future__ import annotations

import pytest

from auto_engineering.errors import AEError, ErrorCode

# ============================================================
# I. ErrorCode 枚举完整性 (防止重命名/删除)
# ============================================================


class TestErrorCodeEnum:
    """枚举完整性 — 13 ErrorCode (v5.5 审计后)."""

    def test_all_codes_defined(self) -> None:
        """13 个 ErrorCode 全存在."""
        expected = {
            # LLM / API (6)
            "LLM_TIMEOUT",
            "LLM_NETWORK_ERROR",
            "LLM_INVALID_RESPONSE",
            "LLM_AUTH_ERROR",
            "LLM_RATE_LIMIT",
            "LLM_UNKNOWN_ERROR",
            # Stage / Loop (3)
            "MAX_TOOL_CALLS_EXCEEDED",
            "INVALID_AGENT_OUTPUT",
            "TOOL_EXECUTION_ERROR",
            # Task / Cancellation (2)
            "TASK_CANCELLED",
            "AGENT_REGISTRATION_ERROR",
            # Configuration (1)
            "CONFIG_MISSING_API_KEY",
            # Budget (1)
            "BUDGET_EXCEEDED",
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
# II. AEError 构造 — 验证 code/message/original_error/suggestion 字段
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

    def test_suggestion_in_str(self) -> None:
        """suggestion 出现在 str(err) 中."""
        err = AEError(
            ErrorCode.CONFIG_MISSING_API_KEY,
            "缺 API key",
            suggestion="设置 ANTHROPIC_API_KEY 环境变量",
        )
        s = str(err)
        assert "建议" in s
        assert "ANTHROPIC_API_KEY" in s


# ============================================================
# III. 关键抛点 — 直接构造 AEError 模拟 raise, 验证 message 格式
# ============================================================


class TestActiveCodesRaisePoints:
    """13 active codes 的预期 message 形式 (v5.5 审计后).

    这些是 raise sites 的 contract — 如果上游调用方依赖
    特定 substring 来做错误处理, 改 message 会 break.
    """

    def test_llm_timeout_message(self) -> None:
        err = AEError(ErrorCode.LLM_TIMEOUT, "60s timeout")
        assert "timeout" in err.message.lower()

    def test_llm_network_error_message(self) -> None:
        err = AEError(ErrorCode.LLM_NETWORK_ERROR, "APIConnectionError: refused")
        assert "connection" in err.message.lower() or "api" in err.message.lower()

    def test_llm_invalid_response_message(self) -> None:
        err = AEError(ErrorCode.LLM_INVALID_RESPONSE, "APIStatusError: 500")
        assert "500" in err.message or "status" in err.message.lower()

    def test_llm_auth_error_message(self) -> None:
        err = AEError(ErrorCode.LLM_AUTH_ERROR, "AuthenticationError: bad key")
        assert "auth" in err.message.lower() or "key" in err.message.lower()

    def test_llm_rate_limit_message(self) -> None:
        err = AEError(ErrorCode.LLM_RATE_LIMIT, "RateLimitError: 429")
        assert "429" in err.message or "rate" in err.message.lower()

    def test_llm_unknown_error_message(self) -> None:
        err = AEError(ErrorCode.LLM_UNKNOWN_ERROR, "未知异常: unexpected EOF")
        assert "未知" in err.message or "unexpected" in err.message.lower()

    def test_max_tool_calls_exceeded(self) -> None:
        err = AEError(ErrorCode.MAX_TOOL_CALLS_EXCEEDED, "exceeded 5 tool calls")
        assert "tool" in err.message.lower()

    def test_invalid_agent_output(self) -> None:
        err = AEError(ErrorCode.INVALID_AGENT_OUTPUT, "JSON 解析失败: line 5")
        assert "json" in err.message.lower() or "解析" in err.message

    def test_tool_execution_error(self) -> None:
        """TOOL_EXECUTION_ERROR (BaseAgent.execute() → 工具业务失败)."""
        err = AEError(
            ErrorCode.TOOL_EXECUTION_ERROR,
            "Tool 'git_commit' error: nothing to commit",
            suggestion="检查工具 'git_commit' 的输入参数或运行环境",
        )
        assert err.code is ErrorCode.TOOL_EXECUTION_ERROR
        assert "git_commit" in err.message

    def test_task_cancelled(self) -> None:
        err = AEError(ErrorCode.TASK_CANCELLED, "用户 Ctrl-C")
        assert "用户" in err.message or "ctrl" in err.message.lower()

    def test_agent_registration_error(self) -> None:
        err = AEError(ErrorCode.AGENT_REGISTRATION_ERROR, "agent_type 'foo' 未注册")
        assert "未注册" in err.message or "registered" in err.message.lower()

    def test_config_missing_api_key(self) -> None:
        """CLI dev-loop 入口实际抛点."""
        err = AEError(
            ErrorCode.CONFIG_MISSING_API_KEY, "环境变量 ANTHROPIC_API_KEY 未设置"
        )
        assert "ANTHROPIC_API_KEY" in err.message

    def test_budget_exceeded(self) -> None:
        err = AEError(ErrorCode.BUDGET_EXCEEDED, "tokens 8192 > max 4096")
        assert "token" in err.message.lower()


# ============================================================
# IV. v5.0 错误码 → 抛点映射契约 (审计后 13 codes)
# ============================================================


class TestV5ErrorCodeMapping:
    """v5.0 错误码 → 抛点映射契约 (v5.5 审计后 13 codes).

    按类别分组:
        LLM (6): TIMEOUT, NETWORK_ERROR, INVALID_RESPONSE, AUTH_ERROR, RATE_LIMIT, UNKNOWN_ERROR
        Stage (3): MAX_TOOL_CALLS_EXCEEDED, INVALID_AGENT_OUTPUT, TOOL_EXECUTION_ERROR
        Task (2): CANCELLED, AGENT_REGISTRATION_ERROR
        Config (1): MISSING_API_KEY
        Budget (1): EXCEEDED
    """

    def test_error_code_total_count_is_13(self) -> None:
        """ErrorCode 总数 = 13 (v5.5 审计后)."""
        assert len(ErrorCode) == 13, (
            f"ErrorCode 总数应 13, 实际 {len(ErrorCode)}. "
            f"新增/删除需同步 test_all_codes_defined"
        )

    def test_category_llm_codes(self) -> None:
        codes = [
            ErrorCode.LLM_TIMEOUT,
            ErrorCode.LLM_NETWORK_ERROR,
            ErrorCode.LLM_INVALID_RESPONSE,
            ErrorCode.LLM_AUTH_ERROR,
            ErrorCode.LLM_RATE_LIMIT,
            ErrorCode.LLM_UNKNOWN_ERROR,
        ]
        for c in codes:
            assert c.name.startswith("LLM_"), f"{c.name} 不属于 LLM 类别"

    def test_category_stage_codes(self) -> None:
        codes = [
            ErrorCode.MAX_TOOL_CALLS_EXCEEDED,
            ErrorCode.INVALID_AGENT_OUTPUT,
            ErrorCode.TOOL_EXECUTION_ERROR,
        ]
        for c in codes:
            assert (
                c.name.endswith("_EXCEEDED")
                or c.name == "INVALID_AGENT_OUTPUT"
                or c.name == "TOOL_EXECUTION_ERROR"
            ), f"{c.name} 不符合 Stage 命名约定"

    def test_category_task_codes(self) -> None:
        codes = [
            ErrorCode.TASK_CANCELLED,
            ErrorCode.AGENT_REGISTRATION_ERROR,
        ]
        for c in codes:
            assert (
                c.name.startswith("TASK_") or c.name.startswith("AGENT_")
            ), f"{c.name} 不属于 Task 类别"

    def test_category_config_code(self) -> None:
        assert ErrorCode.CONFIG_MISSING_API_KEY.name.startswith("CONFIG_")

    def test_category_budget_code(self) -> None:
        assert ErrorCode.BUDGET_EXCEEDED.name == "BUDGET_EXCEEDED"

    def test_v5_a_config_error(self) -> None:
        """CONFIG_MISSING_API_KEY (settings.py CLI 模式)."""
        err = AEError(
            ErrorCode.CONFIG_MISSING_API_KEY, "Config error: 缺 ANTHROPIC_API_KEY"
        )
        assert err.code is ErrorCode.CONFIG_MISSING_API_KEY
        assert "ANTHROPIC_API_KEY" in err.message

    def test_v5_d_llm_timeout(self) -> None:
        """LLM_TIMEOUT (BaseAgent._map_llm_exception APITimeoutError)."""
        err = AEError(ErrorCode.LLM_TIMEOUT, "LLM timeout: APITimeoutError after 60s")
        assert err.code is ErrorCode.LLM_TIMEOUT
        assert "timeout" in err.message.lower()

    def test_v5_d_llm_parse_failure(self) -> None:
        """INVALID_AGENT_OUTPUT (BaseAgent._parse_final_response)."""
        err = AEError(
            ErrorCode.INVALID_AGENT_OUTPUT, "LLM parse failure: JSON 解析失败"
        )
        assert err.code is ErrorCode.INVALID_AGENT_OUTPUT
        assert "解析" in err.message or "parse" in err.message.lower()

    def test_v5_e_task_cancelled(self) -> None:
        """TASK_CANCELLED (CancellationToken.check() / SIGINT)."""
        err = AEError(ErrorCode.TASK_CANCELLED, "用户 SIGINT (Ctrl-C)")
        assert err.code is ErrorCode.TASK_CANCELLED
        assert "SIGINT" in err.message or "ctrl" in err.message.lower()

    def test_v5_f_checkpoint_not_found(self) -> None:
        """CheckpointNotFoundError (checkpoint_store.load() LookupError)."""
        from auto_engineering.loop.checkpoint import CheckpointNotFoundError

        with pytest.raises(CheckpointNotFoundError):
            raise CheckpointNotFoundError("nonexistent-id")

    def test_v5_d_llm_max_tokens(self) -> None:
        """BUDGET_EXCEEDED replaces LLM_MAX_RETRIES (response.stop_reason='max_tokens')."""
        err = AEError(ErrorCode.BUDGET_EXCEEDED, "LLM max_tokens: response truncated")
        assert err.code is ErrorCode.BUDGET_EXCEEDED
        assert "max_tokens" in err.message or "token" in err.message.lower()


# ============================================================
# V. AEError 异常链 + 序列化边界
# ============================================================


class TestAEErrorChainingAndPickle:
    """AEError 异常链 + 序列化边界."""

    def test_original_error_preserved_through_raise(self) -> None:
        """AEError 包原始异常 → 原始异常可访问."""
        original = ValueError("inner error")
        try:
            raise AEError(
                ErrorCode.LLM_INVALID_RESPONSE, "wrap", original_error=original
            )
        except AEError as caught:
            assert caught.original_error is original
            assert isinstance(caught.original_error, ValueError)
            assert "inner error" in str(caught.original_error)

    def test_aeerror_caught_by_base_exception(self) -> None:
        """AEError 是 Exception 子类, 可被 `except Exception` 捕获."""
        with pytest.raises(Exception) as exc_info:
            raise AEError(ErrorCode.LLM_TIMEOUT, "test")
        assert isinstance(exc_info.value, AEError)

    def test_aeerror_str_includes_code_value(self) -> None:
        """str(err) 含 [CODE_VALUE] 格式前缀."""
        err = AEError(ErrorCode.BUDGET_EXCEEDED, "tokens > max")
        s = str(err)
        assert s.startswith("[BUDGET_EXCEEDED]")
        assert "tokens > max" in s
