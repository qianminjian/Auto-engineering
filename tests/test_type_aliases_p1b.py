"""P1-B: Type ambiguity fix - EngineState / AgentTask + backward compat aliases.

设计动机:
- loop.state.LoopState 已被 v2.3 P0-A 重命名为 CheckpointEnvelope
- engine.state.LoopState 仍是 v1.0 dataclass, 与 v2.0 同名, 造成 IDE/import 混淆
- runtime.task.Task 同样与 loop.plan.Task 同名冲突

修复:
- engine.state.LoopState → EngineState
- runtime.task.Task → AgentTask
- 旧名作为 type alias 保持兼容, 不破坏现有代码

TDD: 先验证 import 行为, 再做重命名.
"""
from __future__ import annotations


class TestEngineStateRename:
    """engine.state.LoopState → EngineState (P1-B)."""

    def test_enginestate_class_exists(self) -> None:
        """新名 EngineState 存在."""
        from auto_engineering.engine.state import EngineState

        assert EngineState is not None
        assert hasattr(EngineState, "__dataclass_fields__")

    def test_loopstate_alias_points_to_enginestate(self) -> None:
        """旧名 LoopState 仍可 import, 是 EngineState 的 alias."""
        from auto_engineering.engine.state import EngineState, LoopState

        assert LoopState is EngineState, "LoopState 必须 alias 到 EngineState"

    def test_enginestate_has_expected_fields(self) -> None:
        """EngineState 字段保持不变 (向后兼容)."""
        from auto_engineering.engine.state import EngineState

        fields = EngineState.__dataclass_fields__
        # 关键字段 (与原 LoopState 一致)
        assert "requirement" in fields
        assert "plan" in fields
        assert "files_changed" in fields
        assert "critic_verdict" in fields

    def test_enginestate_instantiable(self) -> None:
        """EngineState 可正常实例化 (确认不是 stub)."""
        from auto_engineering.engine.state import EngineState

        state = EngineState(requirement="test", plan="p")
        assert state.requirement == "test"
        assert state.plan == "p"


class TestAgentTaskRename:
    """runtime.task.Task → AgentTask (P1-B)."""

    def test_agenttask_class_exists(self) -> None:
        """新名 AgentTask 存在."""
        from auto_engineering.runtime.task import AgentTask

        assert AgentTask is not None

    def test_task_alias_points_to_agenttask(self) -> None:
        """旧名 Task 仍可 import, 是 AgentTask 的 alias."""
        from auto_engineering.runtime.task import AgentTask, Task

        assert Task is AgentTask, "Task 必须 alias 到 AgentTask"

    def test_agenttask_instantiable(self) -> None:
        """AgentTask 可正常实例化."""
        from auto_engineering.runtime.task import AgentTask

        task = AgentTask(id="t1", description="test", expected_output="output")
        assert task.id == "t1"
        assert task.description == "test"
        assert task.expected_output == "output"
