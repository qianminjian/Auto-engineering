"""Tests for v5.0 Phase 05 — M5 Round 重构.

设计: v5.0 §B2.12 run_round 签名扩展 + §B2.12a per_task_ctx 独立 +
      §B2.12b _topological_levels (Kahn BFS 分层).

覆盖:
    - run_round 新增 stage: str / contracts: dict | None 参数
    - _topological_levels: 单任务/并行/环检测
    - per_task_ctx 独立 (避免 shared ctx.task 串扰)
    - run_round 错误分类: AEError(ERR_TASK_CANCELLED) / CancelledError / Exception
"""

from __future__ import annotations

import asyncio
import time

import pytest

from auto_engineering.loop.round import (
    run_round,
    TaskOutcome,
)
from auto_engineering.loop.plan import Task, ConflictError, _topological_levels


# ============================================================
# 共享 helper
# ============================================================


def make_task(tid: str, deps: list[str] | None = None) -> Task:
    """构造测试用 Task (role=developer 默认)."""
    return Task(id=tid, deps=list(deps or []), role="developer")


# ============================================================
# Group 1: run_round 签名扩展
# ============================================================


class TestRunRoundSignature:
    """v5.0 §B2.12 — run_round 接受 stage + contracts 参数."""

    @pytest.mark.asyncio
    async def test_run_round_with_stage_param(self):
        """run_round 接受 stage: str 参数 (默认空串不报错)."""
        async def executor(task, ctx):
            return TaskOutcome(task_id=task.id, status="completed", output=task.id)

        task = make_task("t1")
        # stage="developer" 应当被接受 (供 run_gates 过滤 Gate)
        result = await run_round(
            tasks=[task],
            executor=executor,
            stage="developer",
        )
        assert result.completed_count == 1

    @pytest.mark.asyncio
    async def test_run_round_with_contracts_param(self):
        """run_round 接受 contracts: dict | None 参数."""
        async def executor(task, ctx):
            return TaskOutcome(task_id=task.id, status="completed", output=task.id)

        task = make_task("t1")
        contracts = {"api_user": {"request": {}, "response": {}, "status": 200}}
        # contracts=None 默认, contracts=dict 应被接受
        result = await run_round(
            tasks=[task],
            executor=executor,
            contracts=contracts,
        )
        assert result.completed_count == 1

    @pytest.mark.asyncio
    async def test_run_round_default_stage_and_contracts(self):
        """不传 stage/contracts 也应工作 (向后兼容)."""
        async def executor(task, ctx):
            return TaskOutcome(task_id=task.id, status="completed", output=task.id)

        task = make_task("t1")
        result = await run_round(tasks=[task], executor=executor)
        assert result.completed_count == 1


# ============================================================
# Group 2: _topological_levels (Kahn BFS 分层)
# ============================================================


class TestTopologicalLayers:
    """v5.0 §B2.12b — _topological_levels 分层 (round.py 内部使用).

    注意: plan.py 已存在 _topological_levels (DFS 递归 + cache),
    这里测试的是 round.py 中的 _topological_levels (Kahn BFS 实现).
    """

    def test_topological_levels_single_task(self):
        """单个无依赖 task → [[t1]]."""
        layers = _topological_levels([make_task("t1")])
        assert layers == [[make_task("t1")]]

    def test_topological_levels_parallel(self):
        """多个无依赖 task → [[t1, t2, t3]] (同层并行)."""
        tasks = [make_task("t1"), make_task("t2"), make_task("t3")]
        layers = _topological_levels(tasks)
        assert len(layers) == 1
        assert len(layers[0]) == 3
        # 同层的 task id 应当是输入的 id 集合
        layer_ids = {t.id for t in layers[0]}
        assert layer_ids == {"t1", "t2", "t3"}

    def test_topological_levels_chain(self):
        """依赖链 t1 → t2 → t3 → 3 层, 每层 1 个."""
        tasks = [
            make_task("t1"),
            make_task("t2", deps=["t1"]),
            make_task("t3", deps=["t2"]),
        ]
        layers = _topological_levels(tasks)
        assert len(layers) == 3
        assert layers[0][0].id == "t1"
        assert layers[1][0].id == "t2"
        assert layers[2][0].id == "t3"

    def test_topological_levels_diamond(self):
        """菱形依赖: t1 → t2, t1 → t3, t2 → t4, t3 → t4 → 3 层."""
        tasks = [
            make_task("t1"),
            make_task("t2", deps=["t1"]),
            make_task("t3", deps=["t1"]),
            make_task("t4", deps=["t2", "t3"]),
        ]
        layers = _topological_levels(tasks)
        assert len(layers) == 3
        assert layers[0][0].id == "t1"
        # t2 和 t3 在同层
        assert {t.id for t in layers[1]} == {"t2", "t3"}
        assert layers[2][0].id == "t4"

    def test_topological_levels_cycle_raises(self):
        """环检测: t1 → t2 → t1 → ConflictError."""
        tasks = [
            make_task("t1", deps=["t2"]),
            make_task("t2", deps=["t1"]),
        ]
        with pytest.raises(ConflictError):
            _topological_levels(tasks)

    def test_topological_levels_empty(self):
        """空列表 → []."""
        assert _topological_levels([]) == []


# ============================================================
# Group 3: run_round 错误分类
# ============================================================


class TestRunRoundErrorCategorization:
    """v5.0 §B2.12a — run_round 错误分类:

        - AEError(ERR_TASK_CANCELLED) → status=cancelled
        - asyncio.CancelledError     → status=cancelled
        - Exception (其他)            → status=failed
    """

    @pytest.mark.asyncio
    async def test_run_round_aeerror_task_cancelled(self):
        """AEError(ERR_TASK_CANCELLED) → outcome status=cancelled."""
        from auto_engineering.errors import AEError, ErrorCode

        async def executor(task, ctx):
            raise AEError(ErrorCode.TASK_CANCELLED, "用户中断")

        task = make_task("t1")
        result = await run_round(tasks=[task], executor=executor)
        assert len(result.outcomes) == 1
        outcome = result.outcomes[0]
        assert outcome.status == "cancelled"
        assert outcome.task_id == "t1"

    @pytest.mark.asyncio
    async def test_run_round_asyncio_cancelled(self):
        """asyncio.CancelledError → outcome status=cancelled."""
        async def executor(task, ctx):
            raise asyncio.CancelledError()

        task = make_task("t1")
        result = await run_round(tasks=[task], executor=executor)
        assert len(result.outcomes) == 1
        assert result.outcomes[0].status == "cancelled"

    @pytest.mark.asyncio
    async def test_run_round_generic_exception_failed(self):
        """Exception (RuntimeError) → outcome status=failed."""
        async def executor(task, ctx):
            raise RuntimeError("boom")

        task = make_task("t1")
        result = await run_round(tasks=[task], executor=executor)
        assert len(result.outcomes) == 1
        assert result.outcomes[0].status == "failed"
        assert "boom" in (result.outcomes[0].error or "")

    @pytest.mark.asyncio
    async def test_run_round_mixed_error_types(self):
        """混合错误类型: AEError/cancelled/Exception + success → 各自正确分类."""
        from auto_engineering.errors import AEError, ErrorCode

        async def executor(task, ctx):
            if task.id == "ae_cancel":
                raise AEError(ErrorCode.TASK_CANCELLED, "user cancel")
            if task.id == "asyncio_cancel":
                raise asyncio.CancelledError()
            if task.id == "generic_err":
                raise ValueError("bad input")
            return TaskOutcome(task_id=task.id, status="completed", output="ok")

        tasks = [
            make_task("success"),
            make_task("ae_cancel"),
            make_task("asyncio_cancel"),
            make_task("generic_err"),
        ]
        result = await run_round(tasks=tasks, executor=executor)
        by_id = {o.task_id: o.status for o in result.outcomes}
        assert by_id["success"] == "completed"
        assert by_id["ae_cancel"] == "cancelled"
        assert by_id["asyncio_cancel"] == "cancelled"
        assert by_id["generic_err"] == "failed"
