"""Tests for runtime/task.py — Phase 2 T1.

TDD Red phase: Task + TaskResult dataclass 字段定义.
参考 CrewAI task.py:114-213 富 Task 模型(简化版,只保留 v1.0 必要字段).
"""

from __future__ import annotations

from auto_engineering.runtime.task import Task, TaskResult


class TestTaskDataclass:
    """Task dataclass 字段 + 默认值."""

    def test_task_minimal_creation(self):
        """最小字段: id + description + expected_output."""
        t = Task(id="t1", description="实现 x", expected_output="x.py")
        assert t.id == "t1"
        assert t.description == "实现 x"
        assert t.expected_output == "x.py"
        assert t.output_schema is None
        assert t.tools == []
        assert t.input_channels == []
        assert t.output_channels == []

    def test_task_with_full_fields(self):
        """完整字段:output_schema + tools + input/output channels."""
        t = Task(
            id="t1",
            description="实现 x",
            expected_output="x.py",
            output_schema={
                "type": "object",
                "properties": {"plan": {"type": "string"}},
            },
            tools=["read_file", "write_file"],
            input_channels=["plan"],
            output_channels=["files_changed"],
        )
        assert t.output_schema["properties"]["plan"]["type"] == "string"
        assert "read_file" in t.tools
        assert t.input_channels == ["plan"]
        assert t.output_channels == ["files_changed"]

    def test_task_dataclass_equality(self):
        """同字段 dataclass 相等."""
        t1 = Task(id="t1", description="x", expected_output="y")
        t2 = Task(id="t1", description="x", expected_output="y")
        assert t1 == t2

    def test_task_dataclass_immutability_note(self):
        """Task 是 mutable dataclass(允许运行时修改 fields).

        Why: LoopEngine 可能根据 runtime 反馈调整 Task。
        """
        t = Task(id="t1", description="x", expected_output="y")
        t.description = "x updated"
        assert t.description == "x updated"


class TestTaskResultDataclass:
    """TaskResult dataclass 字段."""

    def test_task_result_minimal(self):
        """最小字段: task_id + values."""
        r = TaskResult(task_id="t1", values={"files_changed": ["x.py"]})
        assert r.task_id == "t1"
        assert r.values["files_changed"] == ["x.py"]
        assert r.raw_response is None
        assert r.tool_calls == []
        assert r.agent_type == ""

    def test_task_result_with_full_fields(self):
        r = TaskResult(
            task_id="t1",
            values={"files_changed": ["x.py"]},
            raw_response="<LLM response>",
            tool_calls=[{"name": "write_file", "args": {"path": "x.py"}}],
            agent_type="developer",
        )
        assert r.raw_response == "<LLM response>"
        assert r.tool_calls[0]["name"] == "write_file"
        assert r.agent_type == "developer"

    def test_task_result_default_factory_independence(self):
        """每个 TaskResult 实例的 tool_calls 是独立 list(default_factory)."""
        r1 = TaskResult(task_id="t1", values={})
        r2 = TaskResult(task_id="t2", values={})
        r1.tool_calls.append({"x": 1})
        assert r2.tool_calls == []  # r2 不应受 r1 影响


class TestTaskToStageMapping:
    """Task 与 StageGraph.Stage 是不同抽象,Task 是 runtime 层,Stage 是 graph 层.

    当前 v1.0 两者字段重叠(都从 CrewAI Task 模型借鉴),
    v2.0 可能拆分:Stage(graph 层)+ Task(runtime 层)。
    """

    def test_task_import_path(self):
        """Task 应在 runtime.task(不是 engine.graph)。"""
        from auto_engineering.runtime.task import Task as T

        assert T.__module__ == "auto_engineering.runtime.task"

    def test_task_id_can_be_stage_name(self):
        """Task.id 通常等于 Stage.name(同一概念在 graph/runtime 两层)."""
        from auto_engineering.engine.graph import Stage

        stage = Stage(
            name="developer",
            agent_type="developer",
            description_template="...",
            expected_output="...",
        )
        task = Task(id=stage.name, description="x", expected_output="y")
        assert task.id == stage.name
