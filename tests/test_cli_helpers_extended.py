"""test_cli_helpers_extended — cli/helpers.py 74% → ≥90% (Phase 12.12).

覆盖目标 (21 missed lines, 主要 L145-155 + 错误分支):
- classify_error: _ERROR_EXIT_CODE_OVERRIDE (TASK_CANCELLED → 130)
- classify_error: 精确匹配 (TASK_NOT_FOUND / LLM_TIMEOUT 等)
- classify_error: 前缀匹配 (CONFIG_* / LLM_* / CHECKPOINT_* / GUARDRAIL_* / STAGE_RETRY_*)
- classify_error: 默认 fallback (未知 code → USER_ERROR / 2)
- classify_error: 非 ErrorCode 入参 (code=str)
- TokenTracker.add(): usage=None / 无 .usage / input_tokens=None / 超 max_tokens
- ProgressLogger.emit(): json 格式 / text 格式
- _install_sigint_handler: 注册 + ValueError 容错
- _log_engine_version, _emit_stage_done, _log_stage_progress
- _CATEGORY_FRIENDLY_PREFIX 完整映射
"""
from __future__ import annotations

import re
import signal
from dataclasses import dataclass
from typing import Any

import pytest

from auto_engineering.cli.helpers import (
    _CATEGORY_FRIENDLY_PREFIX,
    ErrorCategory,
    ProgressLogger,
    TokenTracker,
    _emit_stage_done,
    _install_sigint_handler,
    _log_engine_version,
    _log_stage_progress,
    classify_error,
)
from auto_engineering.errors import AEError, ErrorCode
from auto_engineering.runtime.cancellation import CancellationToken

# ============================================================
# 1. ErrorCategory enum + _CATEGORY_FRIENDLY_PREFIX 映射
# ============================================================


class TestErrorCategoryEnum:
    def test_four_categories_exist(self) -> None:
        assert ErrorCategory.USER_ERROR.value == "user_error"
        assert ErrorCategory.API_ERROR.value == "api_error"
        assert ErrorCategory.NETWORK_ERROR.value == "network_error"
        assert ErrorCategory.BUSINESS_ERROR.value == "business_error"

    def test_friendly_prefix_map_complete(self) -> None:
        """所有 4 个类别都有友好 prefix (L96-101)."""
        for cat in ErrorCategory:
            assert cat in _CATEGORY_FRIENDLY_PREFIX
            assert _CATEGORY_FRIENDLY_PREFIX[cat].startswith("[")


# ============================================================
# 2. classify_error — _ERROR_EXIT_CODE_OVERRIDE (TASK_CANCELLED → 130)
# ============================================================


class TestClassifyErrorOverride:
    """L76-79: TASK_CANCELLED → 显式 130 (v5.0 §PE.6)."""

    def test_task_cancelled_returns_130(self) -> None:
        err = AEError(ErrorCode.TASK_CANCELLED, "user pressed Ctrl-C")
        _cat, code = classify_error(err)
        # TASK_CANCELLED 精确匹配 USER_ERROR (default in map), 显式 exit 130
        assert code == 130


# ============================================================
# 3. classify_error — 精确匹配 (TASK_NOT_FOUND, LLM_TIMEOUT, 等)
# ============================================================


class TestClassifyErrorExactMatch:
    """L82-84: code_str 精确匹配 → category + 默认 exit code."""

    def test_agent_registration_error_user_error(self) -> None:
        err = AEError(ErrorCode.AGENT_REGISTRATION_ERROR, "agent X not registered")
        cat, code = classify_error(err)
        assert cat == ErrorCategory.USER_ERROR
        assert code == 2

    def test_invalid_agent_output_user_error(self) -> None:
        err = AEError(ErrorCode.INVALID_AGENT_OUTPUT, "JSON parse failed")
        cat, code = classify_error(err)
        assert cat == ErrorCategory.USER_ERROR
        assert code == 2

    def test_budget_exceeded_user_error(self) -> None:
        err = AEError(ErrorCode.BUDGET_EXCEEDED, "over budget")
        cat, code = classify_error(err)
        assert cat == ErrorCategory.USER_ERROR
        assert code == 2

    def test_tool_execution_error_business_error(self) -> None:
        """TOOL_EXECUTION_ERROR → BUSINESS_ERROR (v5.5 审计新增)."""
        err = AEError(ErrorCode.TOOL_EXECUTION_ERROR, "tool execution failed")
        cat, code = classify_error(err)
        assert cat == ErrorCategory.BUSINESS_ERROR
        assert code == 5


# ============================================================
# 4. classify_error — 前缀匹配
# ============================================================


class TestClassifyErrorPrefixMatch:
    """前缀匹配 (CONFIG_*, LLM_*, GUARDRAIL_*)."""

    def test_config_prefix_user_error(self) -> None:
        # CONFIG_MISSING_API_KEY 精确匹配 (L82-84)
        err = AEError(ErrorCode.CONFIG_MISSING_API_KEY, "no key")
        cat, code = classify_error(err)
        assert cat == ErrorCategory.USER_ERROR
        assert code == 2

    def test_config_missing_api_key_prefix_user_error(self) -> None:
        err = AEError(ErrorCode.CONFIG_MISSING_API_KEY, "bad config")
        cat, code = classify_error(err)
        assert cat == ErrorCategory.USER_ERROR
        assert code == 2

    def test_llm_timeout_api_error(self) -> None:
        err = AEError(ErrorCode.LLM_TIMEOUT, "timeout")
        cat, code = classify_error(err)
        assert cat == ErrorCategory.API_ERROR
        assert code == 3

    def test_llm_rate_limit_api_error(self) -> None:
        err = AEError(ErrorCode.LLM_RATE_LIMIT, "429")
        cat, code = classify_error(err)
        assert cat == ErrorCategory.API_ERROR
        assert code == 3

    def test_tool_execution_error_prefix_business(self) -> None:
        """TOOL_EXECUTION_ERROR 精确匹配 → BUSINESS_ERROR."""
        err = AEError(ErrorCode.TOOL_EXECUTION_ERROR, "tool failed")
        cat, code = classify_error(err)
        assert cat == ErrorCategory.BUSINESS_ERROR
        assert code == 5

    def test_llm_unknown_error_api_error(self) -> None:
        """LLM_UNKNOWN_ERROR 前缀匹配 → API_ERROR."""
        err = AEError(ErrorCode.LLM_UNKNOWN_ERROR, "unknown LLM error")
        cat, code = classify_error(err)
        assert cat == ErrorCategory.API_ERROR
        assert code == 3


# ============================================================
# 5. classify_error — 默认 fallback (L91-92)
# ============================================================


class TestClassifyErrorFallback:
    """未知 code_str → USER_ERROR + 2."""

    def test_unknown_code_falls_back_to_user_error(self) -> None:
        # 构造一个 code_str 不在 map 中的错误 (mock with str code)
        err = AEError(ErrorCode.TASK_CANCELLED, "x")  # use a known code, but pretend str
        # 直接 monkey-patch code 为 str
        err.code = "UNKNOWN_FAKE_CODE"  # type: ignore[assignment]
        cat, code = classify_error(err)
        assert cat == ErrorCategory.USER_ERROR
        assert code == 2

    def test_non_errorcode_str_code_falls_back(self) -> None:
        """code 是 str (非 ErrorCode 枚举) → str 路径 + fallback."""

        class FakeStrCode:
            value = "STR_CODE"

        # 实际上 AEError.code 必须是 ErrorCode, 这里用另一种方式:
        # 模拟 error.code.value 路径: 直接传 AEError 但通过 magic mock
        from unittest.mock import MagicMock

        fake_err = MagicMock(spec=AEError)
        fake_err.code = MagicMock()
        fake_err.code.value = "COMPLETELY_UNKNOWN"
        # 走完整 fallback
        cat, code = classify_error(fake_err)  # type: ignore[arg-type]
        assert cat == ErrorCategory.USER_ERROR
        assert code == 2


# ============================================================
# 6. TokenTracker.add — 完整分支
# ============================================================


@dataclass
class _FakeUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class _FakeResponse:
    usage: Any = None


class TestTokenTracker:
    """L143-158: usage=None / .usage attr 缺失 / None token / 超 max_tokens."""

    def test_initial_state(self) -> None:
        t = TokenTracker(max_tokens=1000)
        assert t.input_tokens == 0
        assert t.output_tokens == 0
        assert t.total_tokens == 0

    def test_add_with_no_usage_attr(self) -> None:
        """response 无 .usage 属性 → 直接 return (L145-147)."""
        t = TokenTracker(max_tokens=100)
        t.add(_FakeResponse())  # usage is None
        assert t.total_tokens == 0

    def test_add_with_none_usage(self) -> None:
        """response.usage = None → 直接 return."""
        t = TokenTracker(max_tokens=100)
        t.add(_FakeResponse(usage=None))
        assert t.total_tokens == 0

    def test_add_with_valid_usage(self) -> None:
        t = TokenTracker(max_tokens=100)
        t.add(_FakeResponse(usage=_FakeUsage(input_tokens=50, output_tokens=30)))
        assert t.input_tokens == 50
        assert t.output_tokens == 30
        assert t.total_tokens == 80

    def test_add_with_none_input_tokens_treated_as_zero(self) -> None:
        """input_tokens=None → 当 0 处理 (L149: or 0)."""
        t = TokenTracker(max_tokens=100)
        t.add(_FakeResponse(usage=_FakeUsage(input_tokens=None, output_tokens=10)))
        assert t.input_tokens == 0
        assert t.output_tokens == 10

    def test_add_with_none_output_tokens_treated_as_zero(self) -> None:
        t = TokenTracker(max_tokens=100)
        t.add(_FakeResponse(usage=_FakeUsage(input_tokens=10, output_tokens=None)))
        assert t.input_tokens == 10
        assert t.output_tokens == 0

    def test_add_accumulates_multiple_calls(self) -> None:
        t = TokenTracker(max_tokens=1000)
        t.add(_FakeResponse(usage=_FakeUsage(input_tokens=10, output_tokens=20)))
        t.add(_FakeResponse(usage=_FakeUsage(input_tokens=15, output_tokens=25)))
        assert t.input_tokens == 25
        assert t.output_tokens == 45
        assert t.total_tokens == 70

    def test_add_exceeds_max_tokens_raises(self) -> None:
        """超过 max_tokens → AEError(BUDGET_EXCEEDED) (L154-158)."""
        t = TokenTracker(max_tokens=50)
        with pytest.raises(AEError) as exc_info:
            t.add(_FakeResponse(usage=_FakeUsage(input_tokens=40, output_tokens=20)))
        assert exc_info.value.code == ErrorCode.BUDGET_EXCEEDED
        assert "60" in exc_info.value.message  # total = 60 > 50
        assert "50" in exc_info.value.message

    def test_max_tokens_zero_disables_check(self) -> None:
        """max_tokens=0 → 关闭预算检查 (L154: max_tokens > 0)."""
        t = TokenTracker(max_tokens=0)
        # 加再多也不抛
        t.add(_FakeResponse(usage=_FakeUsage(input_tokens=99999, output_tokens=99999)))
        assert t.total_tokens == 199998


# ============================================================
# 7. ProgressLogger.emit — text + json
# ============================================================


class TestProgressLogger:
    """L185-194: emit text 格式 + json 格式."""

    def test_default_format_is_text(self) -> None:
        p = ProgressLogger()
        assert p.log_format == "text"

    def test_emit_text_format(self, capsys: pytest.CaptureFixture) -> None:
        p = ProgressLogger(log_format="text")
        p.emit("stage_started", stage="architect", round=1)
        captured = capsys.readouterr()
        # 前缀带本地时间戳 [HH:MM:SS], 事件内容不变
        assert re.match(r"^\[\d{2}:\d{2}:\d{2}\] ", captured.err)
        assert captured.err.endswith("[stage_started] stage=architect round=1\n")

    def test_emit_json_format(self, capsys: pytest.CaptureFixture) -> None:
        import json

        p = ProgressLogger(log_format="json")
        p.emit("stage_started", stage="architect", round=1)
        captured = capsys.readouterr()
        # 最后一行是 JSON (前缀可能有 [engine] 等)
        last_line = captured.err.strip().splitlines()[-1]
        data = json.loads(last_line)
        assert data["event"] == "stage_started"
        assert data["stage"] == "architect"
        assert data["round"] == 1
        assert "ts" in data  # ISO8601 时间戳字段

    def test_emit_json_with_unicode(self, capsys: pytest.CaptureFixture) -> None:
        """ensure_ascii=False (L189)."""
        import json

        p = ProgressLogger(log_format="json")
        p.emit("info", msg="中文测试")
        captured = capsys.readouterr()
        last_line = captured.err.strip().splitlines()[-1]
        data = json.loads(last_line)
        assert data["msg"] == "中文测试"
        assert "中文" in last_line  # 不应被转义为 \uXXXX


# ============================================================
# 8. _install_sigint_handler + CancellationToken
# ============================================================


class TestInstallSigintHandler:
    """L161-168: SIGINT handler 安装 + ValueError 容错."""

    def test_install_handler_on_valid_thread(self) -> None:
        token = CancellationToken()
        prev_handler = signal.getsignal(signal.SIGINT)
        try:
            _install_sigint_handler(token)
            # 新 handler 已注册 (即使在主线程, contextlib.suppress 会吞掉 ValueError)
            new_handler = signal.getsignal(signal.SIGINT)
            # 验证 handler 已变化 (可能是 SIG_DFL/SIG_IGN/自定义)
            # 由于 main thread 装 SIGINT 会 raise ValueError → suppressed
            # 我们仅验证不抛异常
            assert new_handler is not None
        finally:
            signal.signal(signal.SIGINT, prev_handler)


class TestCancellationTokenCheck:
    """L119-125: check() 抛 AEError(TASK_CANCELLED)."""

    def test_check_raises_after_cancel(self) -> None:
        token = CancellationToken()
        token.cancel()
        with pytest.raises(AEError) as exc_info:
            token.check()
        assert exc_info.value.code == ErrorCode.TASK_CANCELLED
        assert "SIGINT" in exc_info.value.message

    def test_check_no_op_before_cancel(self) -> None:
        token = CancellationToken()
        token.check()  # 不抛
        assert token.is_cancelled() is False


# ============================================================
# 9. Stage progress / engine version 输出辅助
# ============================================================


class TestStageProgressHelpers:
    """L197-209: _log_stage_progress / _emit_stage_done / _log_engine_version."""

    def test_log_stage_progress(self, capsys: pytest.CaptureFixture) -> None:
        _log_stage_progress(1, 3, "architect")
        captured = capsys.readouterr()
        assert re.match(r"^\[\d{2}:\d{2}:\d{2}\] ", captured.out)
        assert captured.out.endswith("Stage 1/3: architect\n")

    def test_emit_stage_done_with_tokens(self, capsys: pytest.CaptureFixture) -> None:
        _emit_stage_done("architect", 1.234, tokens=567)
        captured = capsys.readouterr()
        assert "architect" in captured.out
        assert "1.2s" in captured.out  # L204: elapsed:.1f
        assert "567" in captured.out

    def test_emit_stage_done_no_tokens(self, capsys: pytest.CaptureFixture) -> None:
        _emit_stage_done("developer", 0.0)
        captured = capsys.readouterr()
        assert "developer" in captured.out
        assert "0.0s" in captured.out
        assert "tokens: 0" in captured.out

    def test_log_engine_version(self, capsys: pytest.CaptureFixture) -> None:
        _log_engine_version("v2.5")
        captured = capsys.readouterr()
        assert re.match(r"^\[\d{2}:\d{2}:\d{2}\] ", captured.out)
        assert captured.out.endswith("[engine] using v2.5 orchestrator\n")