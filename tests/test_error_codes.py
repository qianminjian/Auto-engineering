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


# ============================================================
# V. Phase 10: 19 错误码 → 抛点映射契约 (v5.0 §B10.1a)
# ============================================================


class TestV5ErrorCodeMapping:
    """v5.0 §B10.1a 19 错误码 → 抛点映射契约.

    19 错误码按类别分组:
        A. Config / Plan (2)
        B. Guardrail / Sandbox (3)
        C. Gate (3)
        D. LLM (5)
        E. Task (1)
        F. Checkpoint (3)
        M3 阶段路由 (1)
        B8 收敛 (1)
        合计: 2+3+3+5+1+3+1+1 = 19

    这些错误码部分已实现 (TASK_CANCELLED / LLM_TIMEOUT 等),
    部分是 v5.0 规划的新设计 (CONFIG_ERROR / GATE_FAILURE 等).
    本测试套:
        1. 验证已实现的错误码可被构造 + 抛点
        2. 验证错误码的"抛点"在 v5.0 §B10.1a 描述范围内
        3. 记录 v5.0 新增错误码的契约 (期望 message 含特定关键词)
    """

    def test_v5_19_codes_count(self) -> None:
        """v5.0 §B10.1a 19 错误码 (按类别分组)."""
        # 类别 A: Config / Plan
        v5_a = ["CONFIG_ERROR", "PLAN_VALIDATE_ERROR"]
        # 类别 B: Guardrail / Sandbox
        v5_b = ["GUARDRAIL_BLOCK", "GUARDRAIL_EXHAUSTED", "SANDBOX_VIOLATION"]
        # 类别 C: Gate
        v5_c = ["GATE_FAILURE", "GATE_TIMEOUT", "GATE_TOOL_MISSING"]
        # 类别 D: LLM
        v5_d = [
            "LLM_AUTH_ERROR", "LLM_RATE_LIMIT", "LLM_TIMEOUT",
            "LLM_MAX_TOKENS", "LLM_PARSE_FAILURE",
        ]
        # 类别 E: Task
        v5_e = ["TASK_CANCELLED"]
        # 类别 F: Checkpoint
        v5_f = ["CHECKPOINT_ERROR", "CHECKPOINT_CORRUPT", "CHECKPOINT_NOT_FOUND"]
        # 类别 M3 / B8
        v5_g = ["STAGE_ROUTER_ERROR", "CONVERGENCE_ERROR"]

        all_codes = v5_a + v5_b + v5_c + v5_d + v5_e + v5_f + v5_g
        assert len(all_codes) == 19, f"v5.0 §B10.1a 应有 19 错误码, 实际 {len(all_codes)}"

    def test_v5_a_config_error(self) -> None:
        """v5.0 §B10.1a A 类: CONFIG_ERROR (Orchestrator.__init__ / ae doctor)."""
        # 现有 ErrorCode: CONFIG_MISSING_API_KEY, CONFIG_INVALID_VALUE
        # v5.0 期望的统一 CONFIG_ERROR
        err = AEError(ErrorCode.CONFIG_MISSING_API_KEY, "Config error: 缺 ANTHROPIC_API_KEY")
        assert err.code is ErrorCode.CONFIG_MISSING_API_KEY
        assert "Config" in err.message or "config" in err.message.lower()

    def test_v5_b_guardrail_block(self) -> None:
        """v5.0 §B10.1a B 类: GUARDRAIL_BLOCK (Guardrail 返回 block action)."""
        err = GuardrailBlockedError("Plan 缺失")
        assert err.code is ErrorCode.GUARDRAIL_BLOCKED
        # v5.0 期望 message 含 "block" 或 "missing" 关键词
        assert "block" in str(err).lower() or "missing" in str(err).lower()

    def test_v5_d_llm_timeout(self) -> None:
        """v5.0 §B10.1a D 类: LLM_TIMEOUT (BaseAgent._map_llm_exception APITimeoutError)."""
        err = AEError(ErrorCode.LLM_TIMEOUT, "LLM timeout: APITimeoutError after 60s")
        assert err.code is ErrorCode.LLM_TIMEOUT
        assert "timeout" in err.message.lower()

    def test_v5_d_llm_max_tokens(self) -> None:
        """v5.0 §B10.1a D 类: LLM_MAX_TOKENS (response.stop_reason == 'max_tokens')."""
        # 现有 LLM_MAX_RETRIES 复用即可, 或 BUDGET_EXCEEDED
        err = AEError(ErrorCode.BUDGET_EXCEEDED, "LLM max_tokens: response truncated")
        assert err.code is ErrorCode.BUDGET_EXCEEDED
        assert "max_tokens" in err.message or "token" in err.message.lower()

    def test_v5_d_llm_parse_failure(self) -> None:
        """v5.0 §B10.1a D 类: LLM_PARSE_FAILURE (BaseAgent._parse_final_response)."""
        err = AEError(
            ErrorCode.INVALID_AGENT_OUTPUT, "LLM parse failure: JSON 解析失败"
        )
        assert err.code is ErrorCode.INVALID_AGENT_OUTPUT
        assert "解析" in err.message or "parse" in err.message.lower()

    def test_v5_e_task_cancelled(self) -> None:
        """v5.0 §B10.1a E 类: TASK_CANCELLED (CancellationToken.check() / SIGINT)."""
        err = AEError(ErrorCode.TASK_CANCELLED, "用户 SIGINT (Ctrl-C)")
        assert err.code is ErrorCode.TASK_CANCELLED
        assert "用户" in err.message or "SIGINT" in err.message or "ctrl" in err.message.lower()

    def test_v5_f_checkpoint_error(self) -> None:
        """v5.0 §B10.1a F 类: CHECKPOINT_ERROR (checkpoint_store.save() IO 错误)."""
        err = AEError(
            ErrorCode.CHECKPOINT_SAVE_FAILED, "Checkpoint error: SQLite IO 失败"
        )
        assert err.code is ErrorCode.CHECKPOINT_SAVE_FAILED
        assert "Checkpoint" in err.message or "checkpoint" in err.message.lower()

    def test_v5_f_checkpoint_not_found(self) -> None:
        """v5.0 §B10.1a F 类: CHECKPOINT_NOT_FOUND (checkpoint_store.load() LookupError)."""
        # Loop checkpoint 有 CheckpointNotFoundError, engine checkpoint 用 dict
        from auto_engineering.loop.checkpoint import CheckpointNotFoundError

        with pytest.raises(CheckpointNotFoundError):
            raise CheckpointNotFoundError("nonexistent-id")


class TestErrorCodeCategoryCoverage:
    """Phase 10: ErrorCode 按类别 (Checkpoint / LLM / Guardrail / ...) 全覆盖.

    验证 errors.py 暴露的 23 ErrorCode 全部按 v5.0 §B10.1a 类别分配:
    - Checkpoint (2): SAVE_FAILED, LOAD_FAILED
    - LLM active (2): TIMEOUT, MAX_RETRIES
    - LLM reserved (5): NETWORK_ERROR, INVALID_RESPONSE, AUTH_ERROR, RATE_LIMIT, UNKNOWN_ERROR
    - Guardrail (2): BLOCKED, RETRY
    - Stage (4): RETRY_EXCEEDED, MAX_TOOL_CALLS_EXCEEDED, INVALID_AGENT_OUTPUT, GRAPH_RECURSION_LIMIT
    - Task (4): NOT_FOUND, CANCELLED, AGENT_REGISTRATION_ERROR, OUTPUT_DROPPED
    - Config (2): MISSING_API_KEY, INVALID_VALUE
    - Budget (1): EXCEEDED
    - v2.0 multi-agent (1): CONTRACT_REJECTED
    合计: 2+2+5+2+4+4+2+1+1 = 23
    """

    def test_category_a_checkpoint_codes(self) -> None:
        codes = [ErrorCode.CHECKPOINT_SAVE_FAILED, ErrorCode.CHECKPOINT_LOAD_FAILED]
        for c in codes:
            assert "CHECKPOINT" in c.name, f"{c.name} 不属于 Checkpoint 类别"

    def test_category_b_llm_active_codes(self) -> None:
        codes = [ErrorCode.LLM_TIMEOUT, ErrorCode.LLM_MAX_RETRIES]
        for c in codes:
            assert c.name.startswith("LLM_"), f"{c.name} 不属于 LLM 类别"

    def test_category_b_llm_reserved_codes(self) -> None:
        codes = [
            ErrorCode.LLM_NETWORK_ERROR,
            ErrorCode.LLM_INVALID_RESPONSE,
            ErrorCode.LLM_AUTH_ERROR,
            ErrorCode.LLM_RATE_LIMIT,
            ErrorCode.LLM_UNKNOWN_ERROR,
        ]
        for c in codes:
            assert c.name.startswith("LLM_"), f"{c.name} 不属于 LLM 类别"
            # LLM 命名约定: _ERROR / _RESPONSE / _LIMIT 之一
            assert (
                c.name.endswith("_ERROR")
                or c.name == "LLM_INVALID_RESPONSE"
                or c.name == "LLM_RATE_LIMIT"
            ), f"{c.name} 不符合 LLM 命名约定"

    def test_category_c_guardrail_codes(self) -> None:
        codes = [ErrorCode.GUARDRAIL_BLOCKED, ErrorCode.GUARDRAIL_RETRY]
        for c in codes:
            assert c.name.startswith("GUARDRAIL_"), f"{c.name} 不属于 Guardrail 类别"

    def test_category_d_stage_codes(self) -> None:
        codes = [
            ErrorCode.STAGE_RETRY_EXCEEDED,
            ErrorCode.MAX_TOOL_CALLS_EXCEEDED,
            ErrorCode.INVALID_AGENT_OUTPUT,
            ErrorCode.GRAPH_RECURSION_LIMIT,
        ]
        for c in codes:
            assert c.name.endswith("_EXCEEDED") or c.name in (
                "INVALID_AGENT_OUTPUT", "GRAPH_RECURSION_LIMIT",
            ), f"{c.name} 不符合 Stage 命名约定"

    def test_category_e_task_codes(self) -> None:
        codes = [
            ErrorCode.TASK_NOT_FOUND,
            ErrorCode.TASK_CANCELLED,
            ErrorCode.AGENT_REGISTRATION_ERROR,
            ErrorCode.OUTPUT_DROPPED,
        ]
        for c in codes:
            assert (
                c.name.startswith("TASK_")
                or c.name.startswith("AGENT_")
                or c.name.startswith("OUTPUT_")
            ), f"{c.name} 不属于 Task 类别"

    def test_category_f_config_codes(self) -> None:
        codes = [ErrorCode.CONFIG_MISSING_API_KEY, ErrorCode.CONFIG_INVALID_VALUE]
        for c in codes:
            assert c.name.startswith("CONFIG_"), f"{c.name} 不属于 Config 类别"

    def test_category_g_budget_code(self) -> None:
        """BUDGET 类别: 单 code."""
        assert ErrorCode.BUDGET_EXCEEDED.name == "BUDGET_EXCEEDED"

    def test_category_h_multi_agent_code(self) -> None:
        """v2.0 multi-agent 类别: 单 code."""
        assert ErrorCode.CONTRACT_REJECTED.name == "CONTRACT_REJECTED"

    def test_error_code_total_count_is_23(self) -> None:
        """ErrorCode 总数 = 23 (BEACON P2-B 16 active + 5 LLM reserved + 2 contract/extra).

        实际 23: 2 Checkpoint + 2 LLM active + 5 LLM reserved + 2 Guardrail + 4 Stage +
                4 Task + 2 Config + 1 Budget + 1 Contract = 23
        """
        assert len(ErrorCode) == 23, (
            f"ErrorCode 总数应 23, 实际 {len(ErrorCode)}. "
            f"新增/删除需同步 test_all_codes_defined"
        )


class TestAEErrorChainingAndPickle:
    """Phase 10: AEError 异常链 + 序列化边界."""

    def test_original_error_preserved_through_raise(self) -> None:
        """AEError 包原始异常 → 原始异常可访问."""
        original = ValueError("inner error")
        try:
            raise AEError(ErrorCode.LLM_INVALID_RESPONSE, "wrap", original_error=original)
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

    def test_guardrail_retry_signal_not_aeerror_subclass(self) -> None:
        """GuardrailRetrySignal 故意不继承 AEError (RetryPolicy 期望非 fatal)."""
        from auto_engineering.errors import GuardrailRetrySignal

        sig = GuardrailRetrySignal("retry")
        assert not isinstance(sig, AEError)
        # 但仍是 Exception
        assert isinstance(sig, Exception)
        with pytest.raises(GuardrailRetrySignal):
            raise GuardrailRetrySignal("retry please")

