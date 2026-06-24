"""Tests for runtime/context.py — Phase 2 T2.

TDD Red phase: TaskContext dataclass — runtime 层任务上下文.
"""

from __future__ import annotations

from auto_engineering.engine.state import LoopState
from auto_engineering.runtime.context import TaskContext


class TestTaskContextDataclass:
    """TaskContext 字段."""

    def test_task_context_minimal(self):
        """最小字段: state + requirement."""
        state = LoopState(requirement="实现 x")
        ctx = TaskContext(state=state, requirement="实现 x")
        assert ctx.state is state
        assert ctx.requirement == "实现 x"
        assert ctx.current_stage == ""
        assert ctx.inputs == {}
        assert ctx.outputs == {}

    def test_task_context_with_inputs_outputs(self):
        """inputs/outputs 从 Task.input_channels/output_channels 提取."""
        state = LoopState(requirement="r", plan="p1", files_changed=["x.py"])
        ctx = TaskContext(
            state=state,
            requirement="r",
            current_stage="developer",
            inputs={"plan": "p1"},
            outputs={"files_changed": ["x.py"]},
        )
        assert ctx.current_stage == "developer"
        assert ctx.inputs["plan"] == "p1"
        assert ctx.outputs["files_changed"] == ["x.py"]

    def test_task_context_default_factory_independence(self):
        """inputs/outputs default_factory 独立."""
        ctx1 = TaskContext(state=LoopState(), requirement="r")
        ctx2 = TaskContext(state=LoopState(), requirement="r")
        ctx1.inputs["x"] = 1
        ctx1.outputs["y"] = 2
        assert ctx2.inputs == {}
        assert ctx2.outputs == {}


class TestTaskContextImmutability:
    """state 是引用类型,TaskContext 不 copy — 由调用方保证不被修改."""

    def test_state_reference_shared(self):
        """TaskContext.state 与传入 state 是同一对象(不 copy)."""
        state = LoopState(requirement="r")
        ctx = TaskContext(state=state, requirement="r")
        assert ctx.state is state  # 同一对象
        # 修改 ctx.state 会反映到原始 state
        ctx.state.plan = "p"
        assert state.plan == "p"
