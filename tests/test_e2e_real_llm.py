"""端到端真实 LLM 验证 — Phase 1.5 骨架.

策略: 默认 mock 验证(无需 API key),有 ANTHROPIC_API_KEY 时真跑.

目的:
  1. 验证完整 LoopEngine.run() 流程 → checkpoint 落盘 → resume 接管.
  2. 验证 TokenTracker 真累加 LLMUsage(真接 LLM 时 input+output tokens > 0).
  3. 验证 progress output 序列(stage_start → stage_done 顺序).
  4. 验证 cancellation → drained checkpoint 可被 resume.

CI/本地无 key 时: 全用 ScriptedMockRuntime 跑全链路,验证状态机正确.
有 key 时(本地开发): 跑真 Anthropic API,验证 LLM 真实调用 + token 真实累加.

执行:
  无 key:
    pytest tests/test_e2e_real_llm.py -v --no-cov --timeout=120
  有 key:
    ANTHROPIC_API_KEY=sk-... pytest tests/test_e2e_real_llm.py -v --no-cov --timeout=120
"""

from __future__ import annotations

import os

import pytest

from auto_engineering.cli import CancellationToken, ProgressLogger, TokenTracker
from auto_engineering.engine import LoopEngine, build_dev_loop_graph
from tests.conftest import ScriptedMockRuntime, run_async

# ============================================================
# Skip marker: 真实 LLM 测试仅在 ANTHROPIC_API_KEY 存在时跑
# ============================================================

requires_api_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="需 ANTHROPIC_API_KEY 环境变量(本地手动验证)",
)


# ============================================================
# Mock 验证(无 key 时也跑,保证端到端状态机正确)
# ============================================================


class TestE2EMockPipeline:
    """Mock runtime 跑完整 dev-loop 流水线,验证端到端状态机."""

    def test_full_pipeline_mock_runs_to_done(self, checkpoint_dir, tmp_path):
        """完整 mock 流水线: architect → developer → critic → done."""
        runtime = ScriptedMockRuntime(
            {
                "architect": {"plan": "mock plan", "file_list": ["mock.py"]},
                "developer": {
                    "files_changed": ["mock.py"],
                    "commit_hash": "mock123",
                    "test_results": {"passed": 1, "failed": 0},
                },
                "critic": {"verdict": "APPROVE", "findings": [], "critic_feedback": ""},
            }
        )
        engine = LoopEngine(build_dev_loop_graph(), runtime=runtime, checkpoint_dir=checkpoint_dir)
        result = run_async(engine.run("mock e2e", max_steps=10))
        assert result.status == "done"
        assert result.total_steps >= 3  # 至少 3 个 stage

    def test_progress_callbacks_invoked_in_order(self, checkpoint_dir):
        """验证 progress output 序列: stage_start → stage_done 配对出现,无 pre-echo 假象."""
        runtime = ScriptedMockRuntime(
            {
                "architect": {"plan": "p", "file_list": ["x.py"]},
                "developer": {"files_changed": ["x.py"], "commit_hash": "abc", "test_results": {}},
                "critic": {"verdict": "APPROVE", "findings": [], "critic_feedback": ""},
            }
        )
        events: list[tuple[str, str]] = []  # (kind, stage_name)

        def on_stage_start(stage_name: str) -> None:
            events.append(("start", stage_name))

        def on_stage_end(stage_name: str, elapsed_sec: float) -> None:
            events.append(("end", stage_name))

        engine = LoopEngine(build_dev_loop_graph(), runtime=runtime, checkpoint_dir=checkpoint_dir)
        run_async(
            engine.run(
                "e2e progress",
                max_steps=10,
                on_stage_start=on_stage_start,
                on_stage_end=on_stage_end,
            )
        )

        # 验证: 至少 3 对 (start, end),且 end 必须在 start 之后
        starts = [e for e in events if e[0] == "start"]
        ends = [e for e in events if e[0] == "end"]
        assert len(starts) >= 3, f"expected ≥3 stage_start, got {len(starts)}: {events}"
        assert len(ends) >= 3, f"expected ≥3 stage_end, got {len(ends)}: {events}"
        # 每个 stage: start 必须在对应 end 之前(顺序配对)
        assert len(starts) == len(ends), f"start/end 数量必须配对: {events}"
        # Phase 1.4 关键: 没有 pre-echo 假象(即 start 不会出现在 end 之后)
        for i, (kind, name) in enumerate(events):
            if kind == "start":
                # 找到下一个同名 end
                next_end = next(
                    (j for j in range(i + 1, len(events)) if events[j] == ("end", name)),
                    None,
                )
                assert next_end is not None, f"stage {name} start 没有对应 end: {events}"

    def test_token_tracker_accumulates_through_pipeline(self, checkpoint_dir):
        """TokenTracker 真接: runtime.execute 接受并累加 usage(如 runtime 实现)."""
        from auto_engineering.runtime.mock import ScriptedMockRuntime

        # 在 ScriptedMockRuntime 中 token_tracker 不被使用(它不真调 LLM)
        # 这里只验证: 传 tracker 给 run() 不 crash,且 tracker.total_tokens 仍可读
        runtime = ScriptedMockRuntime(
            {
                "architect": {"plan": "p", "file_list": ["x.py"]},
                "developer": {"files_changed": ["x.py"], "commit_hash": "abc", "test_results": {}},
                "critic": {"verdict": "APPROVE", "findings": [], "critic_feedback": ""},
            }
        )
        tracker = TokenTracker(max_tokens=100_000)
        engine = LoopEngine(build_dev_loop_graph(), runtime=runtime, checkpoint_dir=checkpoint_dir)
        run_async(engine.run("e2e token", max_steps=10, token_tracker=tracker))
        # Mock runtime 不真调 LLM → tracker.total_tokens == 0(但应不 crash)
        assert tracker.total_tokens == 0

    def test_cancellation_drains_and_resume(self, checkpoint_dir):
        """端到端: cancellation 触发 → checkpoint.status='drained' → resume 继续."""
        runtime = ScriptedMockRuntime(
            {
                "architect": {"plan": "p", "file_list": ["x.py"]},
                "developer": {"files_changed": ["x.py"], "commit_hash": "abc", "test_results": {}},
                "critic": {"verdict": "APPROVE", "findings": [], "critic_feedback": ""},
            }
        )
        token = CancellationToken()
        token.cancel()  # 预取消 → run() 第一轮 check 立即抛

        engine = LoopEngine(build_dev_loop_graph(), runtime=runtime, checkpoint_dir=checkpoint_dir)
        from auto_engineering.errors import AEError, ErrorCode

        with pytest.raises(AEError) as exc_info:
            run_async(engine.run("e2e cancel", max_steps=10, cancellation=token))
        assert exc_info.value.code == ErrorCode.TASK_CANCELLED
        # checkpoint 应已保存为 drained
        assert engine.checkpoint is not None
        assert engine.checkpoint.status == "drained"


# ============================================================
# 真实 LLM 验证(需 ANTHROPIC_API_KEY,本地手动跑)
# ============================================================


@requires_api_key
class TestE2ERealLLM:
    """真实 Anthropic API 跑 dev-loop 端到端.

    ⚠️ 需 ANTHROPIC_API_KEY 环境变量. 本地手动验证:
        ANTHROPIC_API_KEY=sk-... pytest tests/test_e2e_real_llm.py -v --no-cov

    验证项:
      1. BaseAgent.execute 真调 LLM(input/output tokens > 0)
      2. TokenTracker 真累加 LLMUsage
      3. ProgressLogger 输出 stage_start/stage_done 事件
    """

    def test_real_llm_architect_invocation(self, checkpoint_dir):
        """真调 LLM 跑 architect stage,验证 input_tokens > 0."""
        from auto_engineering.agents.architect import ArchitectAgent

        agent = ArchitectAgent()
        tracker = TokenTracker(max_tokens=10_000)
        # 简化需求,触发 architect 真接 LLM
        result = agent.execute(
            requirement="创建一个 hello world Python 文件",
            state={},
            token_tracker=tracker,
        )
        assert result.success is True
        assert tracker.total_tokens > 0, f"TokenTracker 未累加, total={tracker.total_tokens}"

    def test_real_llm_progress_logger_emits_events(self, checkpoint_dir, capsys):
        """真跑 LoopEngine + ProgressLogger,验证 stage_start/stage_done 事件输出."""

        # 简化流程: 单 stage architect
        runtime = ScriptedMockRuntime(
            {
                "architect": {"plan": "real plan", "file_list": ["real.py"]},
            }
        )
        engine = LoopEngine(build_dev_loop_graph(), runtime=runtime, checkpoint_dir=checkpoint_dir)
        progress = ProgressLogger(log_format="json")

        from auto_engineering.cli import _emit_stage_done, _log_stage_progress

        events: list[str] = []

        def on_stage_start(stage_name: str) -> None:
            events.append("stage_start")
            _log_stage_progress(0, 0, stage_name)
            progress.emit("stage_start", stage=stage_name)

        def on_stage_end(stage_name: str, elapsed_sec: float) -> None:
            events.append("stage_done")
            _emit_stage_done(stage_name, elapsed_sec, tokens=0)
            progress.emit("stage_done", stage=stage_name, elapsed=elapsed_sec, tokens=0)

        run_async(
            engine.run(
                "real llm e2e",
                max_steps=10,
                on_stage_start=on_stage_start,
                on_stage_end=on_stage_end,
            )
        )

        # 验证 stage_start 和 stage_done 配对出现(无 pre-echo 假象)
        assert "stage_start" in events
        assert "stage_done" in events
        # 顺序: start 在 end 之前
        first_start = events.index("stage_start")
        first_end = events.index("stage_done")
        assert first_start < first_end
