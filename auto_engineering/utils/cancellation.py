"""CancellationToken — 协作式取消令牌 (Phase 03 整合到 runtime 模块).

设计来源: v2.0 协作式取消契约；当前 v5.8 仅用于在 Tick 边界传播用户取消，
不承担 Round/Iteration 上限或宿主主循环调度。

借鉴 AutoGen _base_agent.py cancellation 支持.

用法:
    token = CancellationToken()
    token.cancel()                     # 用户 Ctrl-C 或宿主取消信号触发
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
                "循环已被用户中断 (SIGINT)",
            )


__all__ = ["CancellationToken"]
