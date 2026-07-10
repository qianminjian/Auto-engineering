"""CLI 辅助工具 — ErrorCategory / CancellationToken / TokenTracker / ProgressLogger.

从 cli.py 拆分 (Plan P1-B, 原 cli.py §1-217 + _log_engine_version).
"""

from __future__ import annotations

import contextlib
import enum
import json
import signal
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import click

from auto_engineering.errors import AEError, ErrorCode
from auto_engineering.runtime.cancellation import CancellationToken


def _ts() -> str:
    """本地时间 HH:MM:SS — 进度/日志行前缀 (人读, 便于判断卡死时刻)."""
    return datetime.now().strftime("%H:%M:%S")


# ============================================================
# Plan B Phase 02: 错误归类 + Cancellation + Token Tracker
# ============================================================


class ErrorCategory(enum.Enum):
    """AEError 归类 — 按 code 前缀分 4 类."""

    USER_ERROR = "user_error"  # 用户输入/配置错 (CONFIG_*, TASK_NOT_FOUND)
    API_ERROR = "api_error"  # API/LLM 错 (LLM_*)
    NETWORK_ERROR = "network_error"  # 网络/IO 错 (CHECKPOINT_*)
    BUSINESS_ERROR = "business_error"  # 业务规则错 (SANDBOX_*, STAGE_RETRY_*)


# 错误码 → 类别 映射(按 code 字符串前缀分类)
_ERROR_CATEGORY_MAP: dict[str, ErrorCategory] = {
    # USER_ERROR
    "CONFIG_": ErrorCategory.USER_ERROR,
    "INVALID_AGENT_OUTPUT": ErrorCategory.USER_ERROR,
    "TOOL_EXECUTION_ERROR": ErrorCategory.BUSINESS_ERROR,
    # API_ERROR
    "LLM_": ErrorCategory.API_ERROR,
    # BUSINESS_ERROR
    "AGENT_REGISTRATION_ERROR": ErrorCategory.USER_ERROR,
    "BUDGET_EXCEEDED": ErrorCategory.USER_ERROR,
}

# 错误码 → 显式退出码覆盖 (v5.0 §PE.6: 130 = SIGINT)
_ERROR_EXIT_CODE_OVERRIDE: dict[str, int] = {
    "TASK_CANCELLED": 130,  # v5.0: 用户 SIGINT 取消 → 130 (Unix 惯例)
}

# 错误类别 → 默认退出码
_CATEGORY_EXIT_CODE: dict[ErrorCategory, int] = {
    ErrorCategory.USER_ERROR: 2,  # v5.0 §PE.6: 1=config_error 留给 preflight, 2=gate_unrecoverable
    ErrorCategory.API_ERROR: 3,
    ErrorCategory.NETWORK_ERROR: 4,
    ErrorCategory.BUSINESS_ERROR: 5,
}


def classify_error(error: AEError) -> tuple[ErrorCategory, int]:
    """按 AEError.code 字符串前缀归类.

    Returns:
        (ErrorCategory, exit_code) 元组.
    """
    code_str = error.code.value if isinstance(error.code, ErrorCode) else str(error.code)

    # v5.0 §PE.6: 显式退出码覆盖 (优先级最高)
    if code_str in _ERROR_EXIT_CODE_OVERRIDE:
        # 用错误类别表 (无 → 默认 USER_ERROR) 仅用于分类
        category = _ERROR_CATEGORY_MAP.get(code_str, ErrorCategory.USER_ERROR)
        return category, _ERROR_EXIT_CODE_OVERRIDE[code_str]

    # 优先精确匹配(覆盖前缀)
    category = _ERROR_CATEGORY_MAP.get(code_str)
    if category is not None:
        return category, _CATEGORY_EXIT_CODE[category]

    # 前缀匹配
    for prefix, cat in _ERROR_CATEGORY_MAP.items():
        if prefix.endswith("_") and code_str.startswith(prefix):
            return cat, _CATEGORY_EXIT_CODE[cat]

    # 默认 USER_ERROR
    return ErrorCategory.USER_ERROR, _CATEGORY_EXIT_CODE[ErrorCategory.USER_ERROR]


# 类别 → 友好提示前缀
_CATEGORY_FRIENDLY_PREFIX: dict[ErrorCategory, str] = {
    ErrorCategory.USER_ERROR: "[配置/参数错]",
    ErrorCategory.API_ERROR: "[API/LLM 错]",
    ErrorCategory.NETWORK_ERROR: "[网络/IO 错]",
    ErrorCategory.BUSINESS_ERROR: "[业务规则错]",
}


# v5.4 审计 r3 P1-5: CancellationToken 已统一到 runtime/cancellation.py.
# cli/__init__.py 直接导入 runtime.cancellation.CancellationToken.



@dataclass
class TokenTracker:
    """累加 LLM 调用的 token 消耗,超阈值抛 BUDGET_EXCEEDED.

    支持 input_tokens + output_tokens 累加;mock-friendly(duck-typing on .usage).
    """

    max_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, response: Any) -> None:
        """累加 LLMResponse.usage 中的 token. 超阈值抛 AEError(BUDGET_EXCEEDED)."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return

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


def _install_sigint_handler(token: CancellationToken) -> None:
    """注册 SIGINT handler → token.cancel()."""

    def _handler(sig, frame):
        token.cancel()

    with contextlib.suppress(ValueError, OSError):
        signal.signal(signal.SIGINT, _handler)


# ============================================================
# 进度/日志辅助
# ============================================================


@dataclass
class ProgressLogger:
    """统一处理 text / json 格式日志输出.

    默认输出到 stderr(避免污染 stdout 用户输出).
    """

    log_format: str = "text"  # 'text' | 'json'

    def emit(self, event: str, **fields: Any) -> None:
        """输出一行日志.text 格式: '[ts] [event] key=value ...',json 格式: JSON 对象(含 ts)."""
        if self.log_format == "json":
            payload = {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "event": event,
                **fields,
            }
            click.echo(json.dumps(payload, ensure_ascii=False), err=True)
        else:
            parts = [f"[{_ts()}]", f"[{event}]"]
            for k, v in fields.items():
                parts.append(f"{k}={v}")
            click.echo(" ".join(parts), err=True)


def _log_stage_progress(current: int, total: int, name: str) -> None:
    """输出 stage 进度: '[ts] Stage X/3: architect'."""
    click.echo(f"[{_ts()}] Stage {current}/{total}: {name}")


def _emit_stage_done(stage: str, elapsed: float, tokens: int = 0) -> None:
    """输出 stage 完成: '[ts]   ✓ Stage X done in 1.2s (tokens: 1234)'."""
    click.echo(f"[{_ts()}]   ✓ Stage {stage} done in {elapsed:.1f}s (tokens: {tokens})")


def _log_engine_version(version: str) -> None:
    """输出当前使用的 engine 版本(v2.0 / v2.0)."""
    click.echo(f"[{_ts()}] [engine] using {version} orchestrator")
