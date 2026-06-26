"""Tests for runtime/runtime.py — Phase 2 T3.

TDD Red phase: AgentRuntime register + execute.
参考 AutoGen SingleThreadedAgentRuntime.register_factory + _get_agent.
"""

from __future__ import annotations

import pytest

from auto_engineering.engine.graph import Stage
from auto_engineering.engine.loop import StageResult
from auto_engineering.engine.state import LoopState
from auto_engineering.runtime.context import TaskContext
from auto_engineering.runtime.runtime import Agent, AgentRuntime
from auto_engineering.runtime.task import Task, TaskResult
from tests.conftest import run_async


class MockAgent:
    """Mock Agent. v1.0 BaseAgent 是空类,Phase 3 才有真实实现.

    AgentRuntime 通过 Protocol 接受任何 Agent-like 对象(duck typing).
    """

    def __init__(self, agent_type: str, writes: dict):
        self.agent_type = agent_type
        self.writes = writes
        self.execute_calls: list[tuple[str, str]] = []

    async def execute(self, task: Task, ctx: TaskContext, cancellation=None) -> TaskResult:
        self.execute_calls.append((task.id, ctx.current_stage))
        return TaskResult(
            task_id=task.id,
            values=self.writes.copy(),
            raw_response="<mock response>",
            tool_calls=[],
            agent_type=self.agent_type,
        )


class TestAgentRuntimeRegistration:
    """AgentRuntime.register 行为."""

    def test_register_new_agent_succeeds(self):
        rt = AgentRuntime()
        agent = MockAgent("architect", {"plan": "p"})
        rt.register("architect", lambda: agent)
        assert "architect" in rt._factories

    def test_register_duplicate_raises_value_error(self):
        rt = AgentRuntime()
        rt.register("architect", lambda: MockAgent("architect", {}))
        with pytest.raises(ValueError, match="already registered"):
            rt.register("architect", lambda: MockAgent("architect", {}))

    def test_register_with_correct_expected_class_succeeds(self):
        class MyAgent(MockAgent):
            pass

        rt = AgentRuntime()
        rt.register("test", lambda: MyAgent("test", {}), expected_class=MyAgent)
        assert "test" in rt._factories

    def test_register_with_wrong_expected_class_raises_type_error(self):
        class MyAgent(MockAgent):
            pass

        class OtherAgent(MockAgent):
            pass

        rt = AgentRuntime()
        with pytest.raises(TypeError, match=r"OtherAgent.*MyAgent"):
            rt.register("test", lambda: OtherAgent("test", {}), expected_class=MyAgent)

    def test_register_without_expected_class_skips_type_check(self):
        """无 expected_class 时不验证类型."""
        rt = AgentRuntime()
        rt.register("test", lambda: MockAgent("test", {}))
        assert "test" in rt._factories


class TestAgentRuntimeExecute:
    """AgentRuntime.execute 行为."""

    def _make_stage(self) -> Stage:
        return Stage(
            name="architect",
            agent_type="architect",
            description_template="分析需求: {requirement}",
            expected_output="plan",
            input_channels=["requirement"],
            output_channels=["plan", "file_list"],
        )

    def test_execute_calls_registered_agent(self):
        """execute() 找到对应 agent_type 的 Agent 并 execute."""
        rt = AgentRuntime()
        agent = MockAgent("architect", {"plan": "p", "file_list": ["x.py"]})
        rt.register("architect", lambda: agent)

        stage = self._make_stage()
        state = LoopState(requirement="实现 x")

        result = run_async(rt.execute(stage, state))

        assert isinstance(result, StageResult)
        assert result.stage == "architect"
        assert result.writes == {"plan": "p", "file_list": ["x.py"]}
        assert agent.execute_calls == [("architect", "architect")]

    def test_execute_unregistered_agent_raises_lookup_error(self):
        rt = AgentRuntime()
        stage = Stage(name="x", agent_type="unknown", description_template="", expected_output="")

        with pytest.raises(LookupError, match="not registered"):
            run_async(rt.execute(stage, LoopState()))

    def test_execute_lazily_creates_agent(self):
        """Agent 延迟实例化,首次 execute 才创建."""
        rt = AgentRuntime()
        call_count = [0]

        def factory():
            call_count[0] += 1
            return MockAgent("test", {})

        rt.register("test", factory)
        assert call_count[0] == 0  # 注册时不调用 factory

        stage = Stage(name="t", agent_type="test", description_template="", expected_output="")
        run_async(rt.execute(stage, LoopState()))
        assert call_count[0] == 1

        # 第二次 execute 复用实例
        run_async(rt.execute(stage, LoopState()))
        assert call_count[0] == 1


class TestAgentRuntimeBuildContext:
    """execute() 构造 TaskContext + Task."""

    def test_execute_builds_task_context_with_inputs_from_state(self):
        rt = AgentRuntime()
        captured_ctx: list[TaskContext] = []

        class CaptureAgent:
            async def execute(self, task, ctx, cancellation=None):
                captured_ctx.append(ctx)
                return TaskResult(task_id=task.id, values={})

        rt.register("t", lambda: CaptureAgent())
        stage = Stage(
            name="t",
            agent_type="t",
            description_template="按 {plan} 实现",
            expected_output="code",
            input_channels=["plan"],
            output_channels=["files_changed"],
        )
        state = LoopState(requirement="r", plan="my plan")

        run_async(rt.execute(stage, state))

        assert len(captured_ctx) == 1
        ctx = captured_ctx[0]
        assert ctx.state is state
        assert ctx.requirement == "r"
        assert ctx.current_stage == "t"
        assert ctx.inputs == {"plan": "my plan"}

    def test_execute_builds_task_with_rendered_description(self):
        """Task.description 用 Stage.render_description 渲染(input_channels 替换)."""
        rt = AgentRuntime()
        captured_task: list[Task] = []

        class CaptureAgent:
            async def execute(self, task, ctx, cancellation=None):
                captured_task.append(task)
                return TaskResult(task_id=task.id, values={})

        rt.register("t", lambda: CaptureAgent())
        # 多行模板 — 缺失 channel 整行删除(D2 修复)
        stage = Stage(
            name="t",
            agent_type="t",
            description_template="按 {plan} 实现\n反馈 {critic_feedback}",
            expected_output="code",
            input_channels=["plan", "critic_feedback"],
            output_channels=["files_changed"],
        )
        # critic_feedback 为空 → 整行删除
        state = LoopState(requirement="r", plan="my plan")

        run_async(rt.execute(stage, state))

        task = captured_task[0]
        assert "按 my plan 实现" in task.description
        assert "critic_feedback" not in task.description
        assert "反馈" not in task.description  # 整行删除后这行消失
        assert task.id == "t"
        assert task.expected_output == "code"

    def test_build_task_resolves_tool_names_to_base_tool_instances(self):
        """P0.1: _build_task 用 registry 把 stage.tools (string list) 解析为 BaseTool 实例."""
        from auto_engineering.tools import ReadFileTool, ToolRegistry

        registry = ToolRegistry()
        registry.register(ReadFileTool())

        rt = AgentRuntime(registry=registry)

        captured_task: list[Task] = []

        class CaptureAgent:
            async def execute(self, task, ctx, cancellation=None):
                captured_task.append(task)
                return TaskResult(task_id=task.id, values={})

        rt.register("t", lambda: CaptureAgent())
        stage = Stage(
            name="t",
            agent_type="t",
            description_template="",
            expected_output="",
            tools=["read_file"],  # string name
            output_channels=["files_changed"],
        )
        state = LoopState(requirement="r")

        run_async(rt.execute(stage, state))

        task = captured_task[0]
        # task.tools 应该是 list[BaseTool],不是 list[str]
        assert len(task.tools) == 1
        assert hasattr(task.tools[0], "execute")  # 是 BaseTool 实例
        assert task.tools[0].name == "read_file"

    def test_build_task_skips_unregistered_tools(self):
        """P0.1: registry 中不存在的工具名被跳过(安全降级)."""
        from auto_engineering.tools import ReadFileTool, ToolRegistry

        registry = ToolRegistry()
        registry.register(ReadFileTool())  # 只有 read_file

        rt = AgentRuntime(registry=registry)

        captured_task: list[Task] = []

        class CaptureAgent:
            async def execute(self, task, ctx, cancellation=None):
                captured_task.append(task)
                return TaskResult(task_id=task.id, values={})

        rt.register("t", lambda: CaptureAgent())
        stage = Stage(
            name="t",
            agent_type="t",
            description_template="",
            expected_output="",
            tools=["read_file", "nonexistent_tool", "write_file"],  # write_file 不在 registry
            output_channels=["files_changed"],
        )
        state = LoopState(requirement="r")

        run_async(rt.execute(stage, state))

        task = captured_task[0]
        # 只解析出 read_file,其余跳过
        assert len(task.tools) == 1
        assert task.tools[0].name == "read_file"

    def test_build_task_without_registry_returns_empty_tools(self):
        """P0.1: 无 registry 时 task.tools 为空列表(向后兼容)."""
        rt = AgentRuntime()  # 无 registry

        captured_task: list[Task] = []

        class CaptureAgent:
            async def execute(self, task, ctx, cancellation=None):
                captured_task.append(task)
                return TaskResult(task_id=task.id, values={})

        rt.register("t", lambda: CaptureAgent())
        stage = Stage(
            name="t",
            agent_type="t",
            description_template="",
            expected_output="",
            tools=["read_file"],
            output_channels=["files_changed"],
        )
        state = LoopState(requirement="r")

        run_async(rt.execute(stage, state))

        task = captured_task[0]
        assert task.tools == []


class TestAgentProtocol:
    """Agent Protocol 定义.

    v1.0 BaseAgent 是空类,Phase 3 才有真实实现.
    AgentRuntime 通过 Protocol 接受任何 Agent-like 对象.
    """

    def test_protocol_is_runtime_checkable(self):

        # Agent 应该是 @runtime_checkable Protocol
        mock = MockAgent("x", {})
        assert isinstance(mock, Agent)

    def test_non_agent_object_fails_isinstance(self):
        class NotAnAgent:
            pass

        assert not isinstance(NotAnAgent(), Agent)


class TestAgentRuntimeReplacesScriptedMockRuntime:
    """AgentRuntime 真接后,ScriptedMockRuntime 应该能注册并被使用.

    这是 Phase 2 实质内容的关键验收点:dev-loop 可以用 AgentRuntime + 任意 Agent,
    不再反向依赖 tests/conftest.
    """

    def test_register_mock_runtime_via_factory(self):
        """把 ScriptedMockRuntime-like 对象包装成 factory 注册."""

        rt = AgentRuntime()

        def make_architect():
            return _ScriptedAgent("architect", {"plan": "p", "file_list": ["x.py"]})

        rt.register("architect", make_architect)
        assert "architect" in rt._factories

        # Smoke: 实际 execute 不抛
        stage = Stage(
            name="architect",
            agent_type="architect",
            description_template="",
            expected_output="",
            output_channels=["plan"],
        )
        result = run_async(rt.execute(stage, LoopState(requirement="r")))
        assert result.stage == "architect"
        assert result.writes["plan"] == "p"


class _ScriptedAgent:
    """Smoke 测试用 Agent,模拟 ScriptedMockRuntime 行为."""

    def __init__(self, agent_type: str, writes: dict):
        self.agent_type = agent_type
        self.writes = writes

    async def execute(self, task, ctx, cancellation=None):
        return TaskResult(
            task_id=task.id,
            values=self.writes.copy(),
            raw_response="<scripted>",
            tool_calls=[],
            agent_type=self.agent_type,
        )


# ============================================================
# v2.3 Phase H — AgentRuntime.get(role) API (P1.4)
# 设计: Orchestrator 需要按 role 查 Agent 实例 — 当前 Runtime 用
#       _get_or_create_agent (private) + execute (高层). 需暴露 get(role)
#       公共 API, 返回 Agent 实例 (懒实例化).
# ============================================================


class TestAgentRuntimeGet:
    """AgentRuntime.get(role) 公共 API (Phase H 新增)."""

    def test_get_returns_registered_agent(self):
        """get(role) 返回已注册的 agent (懒实例化)."""
        rt = AgentRuntime()
        agent = MockAgent("developer", {"x": 1})
        rt.register("developer", lambda: agent)
        got = rt.get("developer")
        assert got is agent, f"get('developer') 应返回 MockAgent 实例, 实际: {got}"

    def test_get_unregistered_returns_none(self):
        """get(unknown_role) 返回 None (不抛 LookupError, 让 caller 优雅降级)."""
        rt = AgentRuntime()
        rt.register("developer", lambda: MockAgent("developer", {}))
        assert rt.get("unknown") is None
        assert rt.get("critic") is None

    def test_get_lazy_instantiation_caches(self):
        """get(role) 多次调用返回同一实例 (延迟实例化缓存)."""
        rt = AgentRuntime()
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return MockAgent("developer", {})

        rt.register("developer", factory)
        # 第一次调用: 触发 factory
        a1 = rt.get("developer")
        assert a1 is not None
        assert call_count == 1
        # 第二次调用: 缓存复用, 不再触发 factory
        a2 = rt.get("developer")
        assert a2 is a1, "get 多次应返回同一实例"
        assert call_count == 1, f"factory 应只调 1 次, 实际: {call_count}"

    def test_get_empty_runtime_returns_none(self):
        """空 Runtime (无注册) → get(any) 返回 None."""
        rt = AgentRuntime()
        assert rt.get("anything") is None
        assert rt.get("developer") is None
