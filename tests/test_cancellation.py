"""CancellationToken 5 个关键路径独立测试 (P1-3 全面深度审计 2026-07-04).

测试覆盖 (5 个关键路径):
    1. 新建 token 默认未取消 (is_cancelled=False, check() 不抛)
    2. cancel() 后 is_cancelled() 返回 True
    3. cancel() 后 check() 抛 AEError(TASK_CANCELLED)
    4. cancel() 多次调用幂等 (重入安全)
    5. cancel() 后 check() 多次调用一致抛 (每次都抛)

背景: 之前测试分散在 test_agents_base_llm.py (agent.execute 路径) 和
test_cli_dev_loop_extended.py (CLI 路径), 缺独立单元测试覆盖 token 本身行为.
"""

from __future__ import annotations

import asyncio

import pytest

from auto_engineering.errors import AEError, ErrorCode
from auto_engineering.runtime.cancellation import CancellationToken


class TestCancellationTokenBasics:
    """CancellationToken 基础状态管理."""

    def test_new_token_not_cancelled(self) -> None:
        """新建 token 默认 is_cancelled() = False (未触发取消)."""
        token = CancellationToken()
        assert token.is_cancelled() is False, (
            "新 token 默认状态应为未取消, 但 is_cancelled() 返回 True"
        )

    def test_new_token_check_does_not_raise(self) -> None:
        """新建 token check() 不抛 (未触发取消不应抛错)."""
        token = CancellationToken()
        # check() 在未取消时静默返回, 不抛 AEError
        token.check()


class TestCancellationTokenCancel:
    """cancel() 状态改变."""

    def test_cancel_makes_is_cancelled_true(self) -> None:
        """cancel() 后 is_cancelled() 返回 True."""
        token = CancellationToken()
        assert token.is_cancelled() is False
        token.cancel()
        assert token.is_cancelled() is True

    def test_cancel_makes_check_raise(self) -> None:
        """cancel() 后 check() 抛 AEError(TASK_CANCELLED)."""
        token = CancellationToken()
        token.cancel()
        with pytest.raises(AEError) as exc_info:
            token.check()
        assert exc_info.value.code == ErrorCode.TASK_CANCELLED
        assert "cancelled" in str(exc_info.value).lower()


class TestCancellationTokenIdempotency:
    """cancel() 重入安全 + check() 一致性."""

    def test_multiple_cancel_is_idempotent(self) -> None:
        """多次 cancel() 调用幂等 (状态不变, 不抛异常)."""
        token = CancellationToken()
        token.cancel()
        token.cancel()  # 第二次
        token.cancel()  # 第三次
        assert token.is_cancelled() is True
        # 仍应抛 (幂等不改变行为)
        with pytest.raises(AEError):
            token.check()

    def test_check_after_cancel_consistent(self) -> None:
        """cancel() 后多次 check() 一致抛 AEError(TASK_CANCELLED)."""
        token = CancellationToken()
        token.cancel()
        for i in range(5):
            with pytest.raises(AEError) as exc_info:
                token.check()
            assert exc_info.value.code == ErrorCode.TASK_CANCELLED, (
                f"第 {i+1} 次 check() 应一致抛 TASK_CANCELLED"
            )


class TestCancellationTokenEdgeCases:
    """边界 + 集成."""

    def test_separate_tokens_independent(self) -> None:
        """多个 token 实例独立 (一个取消不影响其他)."""
        token_a = CancellationToken()
        token_b = CancellationToken()
        token_a.cancel()
        assert token_a.is_cancelled() is True
        assert token_b.is_cancelled() is False, (
            "token_b 应独立于 token_a, 不受 token_a.cancel() 影响"
        )

    def test_check_does_not_modify_state(self) -> None:
        """check() 不修改状态 (无副作用, 多次 check 一致)."""
        token = CancellationToken()
        # check 5 次 (未取消)
        for _ in range(5):
            token.check()
        assert token.is_cancelled() is False, (
            "check() 应无副作用, 不改变 _cancelled 状态"
        )

    def test_ae_error_carries_cancellation_message(self) -> None:
        """AEError.message 含可读信息 (辅助调试)."""
        token = CancellationToken()
        token.cancel()
        with pytest.raises(AEError) as exc_info:
            token.check()
        # 验证 message 包含 SIGINT 提示, 用户可识别
        assert "SIGINT" in str(exc_info.value) or "cancelled" in str(exc_info.value).lower()

    def test_token_equality_by_default_state(self) -> None:
        """相同 _cancelled 状态的 token 表现一致 (无隐性副作用)."""
        token_a = CancellationToken()
        token_b = CancellationToken()
        # 都没取消: 一致行为
        assert token_a.is_cancelled() == token_b.is_cancelled()
        token_a.cancel()
        assert token_a.is_cancelled() != token_b.is_cancelled()


class TestCancellationTokenAsync:
    """异步路径 — 跨 await 传播 (与 orchestrator 主循环集成).

    实际 orchestrator.run() 跨 await 调 token.check(), 验证异步上下文正确.
    """

    @pytest.mark.asyncio
    async def test_check_in_async_context(self) -> None:
        """async 上下文中 check() 正确抛 AEError."""

        async def worker(token: CancellationToken) -> None:
            await asyncio.sleep(0)  # 让出执行权
            token.check()  # 应抛

        token = CancellationToken()
        token.cancel()
        with pytest.raises(AEError) as exc_info:
            await worker(token)
        assert exc_info.value.code == ErrorCode.TASK_CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_during_async_work_propagates(self) -> None:
        """异步 work 中调用 cancel(), check() 后续能检测."""
        import asyncio

        cancel_done = asyncio.Event()

        async def worker(token: CancellationToken) -> None:
            await asyncio.sleep(0.05)  # 模拟异步工作
            token.cancel()
            cancel_done.set()
            await asyncio.sleep(0.05)
            token.check()  # 应抛

        token = CancellationToken()
        with pytest.raises(AEError) as exc_info:
            await worker(token)
        assert cancel_done.is_set(), "worker 应执行到 cancel()"
        assert exc_info.value.code == ErrorCode.TASK_CANCELLED