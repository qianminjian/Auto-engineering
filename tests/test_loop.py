"""LoopEngine 端到端: architect → developer → critic 完整路径.

Phase 1 不调 LLM,所有 Agent 行为用 conftest.py 的 MockRuntime 替代.
"""

import pytest

from auto_engineering.engine import (
    LoopEngine,
    LoopResult,
    build_dev_loop_graph,
)
from auto_engineering.engine.loop import StageResult
from auto_engineering.errors import AEError, ErrorCode
from tests.conftest import (
    ScriptedMockRuntime,
    StepLimitedMockRuntime,
    run_async,
)


# ----- 端到端路径 -----

def test_full_loop_APPROVE_path_3_步完成(checkpoint_dir):
    runtime = ScriptedMockRuntime({
        "architect": {"plan": "do it", "file_list": ["x.py"], "batch_plan": [], "contracts": {}},
        "developer": {"files_changed": ["x.py"], "commit_hash": "abc", "test_results": {}},
        "critic": {"verdict": "APPROVE", "findings": [], "critic_feedback": ""},
    })
    engine = LoopEngine(build_dev_loop_graph(), runtime=runtime, checkpoint_dir=checkpoint_dir)
    result: LoopResult = run_async(engine.run("build x", max_steps=10))

    assert result.status == "done"
    assert result.total_steps == 3
    assert result.state.verdict == "APPROVE"
    assert result.state.commit_hash == "abc"
    assert runtime.call_log == ["architect", "developer", "critic"]


def test_full_loop_MAJOR_反馈回路_2_轮_critic(checkpoint_dir):
    """Critic 第一次 MAJOR → 回 developer → 修复 → critic 第二次 APPROVE."""
    runtime = StepLimitedMockRuntime(major_count=1)
    engine = LoopEngine(build_dev_loop_graph(), runtime=runtime, checkpoint_dir=checkpoint_dir)
    result = run_async(engine.run("build x", max_steps=10))

    assert result.status == "done"
    # architect + developer + critic(MAJOR) + developer + critic(APPROVE) = 5 步
    assert result.total_steps == 5
    assert result.state.verdict == "APPROVE"
    assert runtime.call_log == [
        "architect", "developer", "critic",
        "developer", "critic",
    ]
    # 第二轮 critic 的 feedback 覆盖了第一轮的
    assert result.state.critic_feedback == ""  # 第二轮 critic 给空


def test_full_loop_3_轮_MAJOR_后_APPROVE(checkpoint_dir):
    """测试 2 次 MAJOR 反馈回路."""
    runtime = StepLimitedMockRuntime(major_count=2)
    engine = LoopEngine(build_dev_loop_graph(), runtime=runtime, checkpoint_dir=checkpoint_dir)
    result = run_async(engine.run("build x", max_steps=20))

    assert result.status == "done"
    # architect + (developer + critic) × 3 = 7 步
    assert result.total_steps == 7
    assert runtime.critic_calls == 3


# ----- max_steps 上限 -----

def test_loop_hits_step_limit_returns_out_of_steps(checkpoint_dir):
    """max_steps=2 时,只跑 2 步就退出(architect + developer,critic 没机会跑)."""
    runtime = StepLimitedMockRuntime(major_count=999)  # 永远 MAJOR
    engine = LoopEngine(build_dev_loop_graph(), runtime=runtime, checkpoint_dir=checkpoint_dir)
    result = run_async(engine.run("build x", max_steps=2))

    assert result.status == "out_of_steps"
    assert result.total_steps == 2


# ----- resume -----

def test_resume_从_checkpoint_恢复(checkpoint_dir):
    """max_steps=2 跑一次 → resume → 继续到 done."""
    runtime = StepLimitedMockRuntime(major_count=1)
    engine1 = LoopEngine(build_dev_loop_graph(), runtime=runtime, checkpoint_dir=checkpoint_dir)
    result1 = run_async(engine1.run("build x", max_steps=2))

    # 第一次只跑 2 步
    assert result1.status == "out_of_steps"
    assert result1.total_steps == 2
    cp_id = result1.checkpoint_id

    # resume: 同一 engine,store 还在(同进程),加载 checkpoint 继续
    result2 = run_async(engine1.resume(cp_id))

    assert result2.status == "done"
    # 续跑 3 步(critic + developer + critic) = 共 5 步
    assert result2.total_steps == 5
    assert result2.state.verdict == "APPROVE"


# ----- 错误路径 -----

def test_loop_未传_runtime_抛_AGENT_REGISTRATION_ERROR(checkpoint_dir):
    engine = LoopEngine(build_dev_loop_graph(), runtime=None, checkpoint_dir=checkpoint_dir)
    with pytest.raises(AEError) as exc_info:
        run_async(engine.run("x"))
    assert exc_info.value.code == ErrorCode.AGENT_REGISTRATION_ERROR


def test_resume_无_store_抛_CHECKPOINT_LOAD_FAILED(checkpoint_dir):
    """Engine 没跑过(无 store)时调 resume → 抛错."""
    engine = LoopEngine(build_dev_loop_graph(), runtime=ScriptedMockRuntime({}), checkpoint_dir=checkpoint_dir)
    with pytest.raises(AEError) as exc_info:
        run_async(engine.resume("some-uuid"))
    assert exc_info.value.code == ErrorCode.CHECKPOINT_LOAD_FAILED


# ----- interrupt_after (D4 修复) -----

def test_interrupt_after_breaks_loop(checkpoint_dir):
    """D4: while 循环在 status=='interrupt_after' 时必须 break,不再进入下一轮.

    旧 v3.0 设计: tick() 不检查 status,while 继续 → interrupt_after 后还会再调度一次 Stage,
    违反中断语义.修复后:after_tick 设置 status='interrupt_after',run() 退出循环.
    """
    runtime = ScriptedMockRuntime({
        "architect": {"plan": "p", "file_list": ["x.py"], "batch_plan": [], "contracts": {}},
        "developer": {"files_changed": ["x.py"], "commit_hash": "abc", "test_results": {}},
        "critic": {"verdict": "APPROVE", "findings": [], "critic_feedback": ""},
    })
    engine = LoopEngine(
        build_dev_loop_graph(),
        runtime=runtime,
        checkpoint_dir=checkpoint_dir,
        interrupt_after={"developer"},
    )
    result: LoopResult = run_async(engine.run("build x", max_steps=10))

    assert result.status == "interrupt_after"
    # architect + developer 后中断,critic 不应该被调度
    assert runtime.call_log == ["architect", "developer"]
    assert result.total_steps == 2
    assert result.state.verdict == ""  # critic 未执行


# ----- v3.1 B6 修复: resume() 校验 checkpoint.status -----

def test_resume_with_done_checkpoint_raises(checkpoint_dir):
    """B6: resume() 拒绝从 status='done' 的 checkpoint 恢复.

    Why: done 表示循环已正常结束,resume 只会触发空跑或重复终止.
    应抛 AEError 让用户明确知道无需 resume.
    """
    runtime = ScriptedMockRuntime({
        "architect": {"plan": "p", "file_list": ["x.py"], "batch_plan": [], "contracts": {}},
        "developer": {"files_changed": ["x.py"], "commit_hash": "abc", "test_results": {}},
        "critic": {"verdict": "APPROVE", "findings": [], "critic_feedback": ""},
    })
    engine = LoopEngine(build_dev_loop_graph(), runtime=runtime, checkpoint_dir=checkpoint_dir)

    # 第一次 run 完成(状态变成 done)
    result = run_async(engine.run("build x", max_steps=10))
    assert result.status == "done"

    # 第二次 resume 应抛错(checkpoint.status='done')
    with pytest.raises(AEError) as exc_info:
        run_async(engine.resume(result.checkpoint_id))
    assert "done" in str(exc_info.value.message).lower() or "cannot resume" in str(exc_info.value.message).lower()


def test_resume_with_pending_checkpoint_works(checkpoint_dir):
    """B6 反向: pending checkpoint 可正常 resume(不阻塞正常路径)."""
    runtime = StepLimitedMockRuntime(major_count=1)
    engine1 = LoopEngine(build_dev_loop_graph(), runtime=runtime, checkpoint_dir=checkpoint_dir)
    result1 = run_async(engine1.run("build x", max_steps=2))

    # out_of_steps 状态 → 应可 resume
    assert result1.status == "out_of_steps"

    # pending/interrupted/drained/out_of_steps 都允许 resume
    result2 = run_async(engine1.resume(result1.checkpoint_id))
    assert result2.status == "done"
