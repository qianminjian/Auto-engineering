"""CancellationToken — 协作式取消令牌 (Phase 03 整合到 runtime 模块).

设计来源: design/v2.0-Analysis-Loop.md §4.6 L1 Inner Loop (max_iterations 硬上限)
+ cli.py 原 CancellationToken 拆分到 runtime/ 模块避免循环引用.

借鉴 AutoGen _base_agent.py cancellation 支持.

用法:
    token = CancellationToken()
    token.cancel()                     # 用户 Ctrl-C / Orchestrator 超时触发
    if token.is_cancelled(): ...       # 软检查
    token.check()                       # 硬检查 + 抛 AEError(TASK_CANCELLED)
"""

from __future__ import annotations

from dataclasses import dataclass

from auto_engineering.errors import AEError, ErrorCode


@dataclass
class CancellationToken:
    """协作式取消令牌. SIGINT handler 调 cancel(),loop 中 check() 检测."""

    _cancelled: bool = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def check(self) -> None:
        """若已 cancel, 抛 AEError(TASK_CANCELLED)."""
        if self._cancelled:
            raise AEError(
                ErrorCode.TASK_CANCELLED,
                "Loop was cancelled by user (SIGINT).",
            )


__all__ = ["CancellationToken"]