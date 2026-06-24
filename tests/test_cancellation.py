"""CancellationToken 贯穿 loop.py 测试 — Phase 1.2.

覆盖: cancellation 已取消 → LoopEngine.run() 抛 TASK_CANCELLED + 保存 drained.
"""
from __future__ import annotations

import pytest

from auto_engineering.engine import LoopEngine, build_dev_loop_graph
from auto_engineering.errors import AEError, ErrorCode
from tests.conftest import ScriptedMockRuntime, run_async


class TestCancellationTokenInLoop:
    """LoopEngine.run() 接受 cancellation 参数."""

    def test_run_without_cancellation_runs_normally(self, checkpoint_dir):
        """不传 cancellation → 正常运行."""
        runtime = ScriptedMockRuntime({
            "architect": {"plan": "p", "file_list": ["x.py"]},
            "developer": {"files_changed": ["x.py"], "commit_hash": "abc", "test_results": {}},
            "critic": {"verdict": "APPROVE", "findings": [], "critic_feedback": ""},
        })
        engine = LoopEngine(build_dev_loop_graph(), runtime=runtime, checkpoint_dir=checkpoint_dir)
        result = run_async(engine.run("build x", max_steps=10))
        assert result.status == "done"

    def test_run_with_cancellation_not_triggered_runs_normally(self, checkpoint_dir):
        """传 cancellation 但未取消 → 正常运行."""
        from auto_engineering.cli import CancellationToken

        runtime = ScriptedMockRuntime({
            "architect": {"plan": "p", "file_list": ["x.py"]},
            "developer": {"files_changed": ["x.py"], "commit_hash": "abc", "test_results": {}},
            "critic": {"verdict": "APPROVE", "findings": [], "critic_feedback": ""},
        })
        token = CancellationToken()  # 未取消
        engine = LoopEngine(build_dev_loop_graph(), runtime=runtime, checkpoint_dir=checkpoint_dir)
        result = run_async(engine.run("build x", max_steps=10, cancellation=token))
        assert result.status == "done"

    def test_run_with_cancellation_pre_triggered_raises_cancelled(self, checkpoint_dir):
        """传已取消 token → run() 第一轮 check 立即抛 TASK_CANCELLED."""
        from auto_engineering.cli import CancellationToken

        runtime = ScriptedMockRuntime({})  # 不应被调用
        token = CancellationToken()
        token.cancel()  # 预取消

        engine = LoopEngine(build_dev_loop_graph(), runtime=runtime, checkpoint_dir=checkpoint_dir)
        with pytest.raises(AEError) as exc_info:
            run_async(engine.run("build x", max_steps=10, cancellation=token))
        assert exc_info.value.code == ErrorCode.TASK_CANCELLED
        # runtime 不应被调用
        assert runtime.call_log == []

    def test_cancellation_saves_checkpoint_as_drained(self, checkpoint_dir):
        """取消时 checkpoint 状态设为 'drained'(可被 resume 识别)."""
        from auto_engineering.cli import CancellationToken

        runtime = ScriptedMockRuntime({})  # 不调用
        token = CancellationToken()
        token.cancel()

        engine = LoopEngine(build_dev_loop_graph(), runtime=runtime, checkpoint_dir=checkpoint_dir)
        with pytest.raises(AEError):
            run_async(engine.run("build x", max_steps=10, cancellation=token))

        # checkpoint 应该被存为 drained
        assert engine.checkpoint.status == "drained"
        # 持久化到 DB(注意 _init_checkpoint 用 thread_id 作为文件名,不是 checkpoint.id)
        from pathlib import Path

        db_path = Path(checkpoint_dir) / f"{engine.checkpoint.thread_id}.db"
        assert db_path.exists()

    def test_cancellation_passes_to_runtime_execute(self, checkpoint_dir):
        """cancellation token 传给 runtime.execute(stage, state, cancellation)."""
        from auto_engineering.cli import CancellationToken

        captured: list = []

        class CapturingRuntime:
            async def execute(self, stage, state, cancellation=None, token_tracker=None):
                captured.append(cancellation)
                from auto_engineering.engine.loop import StageResult

                return StageResult(
                    stage=stage.name,
                    writes={"plan": "p", "file_list": ["x.py"]},
                )

        token = CancellationToken()
        engine = LoopEngine(build_dev_loop_graph(), runtime=CapturingRuntime(), checkpoint_dir=checkpoint_dir)
        run_async(engine.run("build x", max_steps=10, cancellation=token))

        # cancellation 应至少传给 runtime 一次
        assert token in captured
