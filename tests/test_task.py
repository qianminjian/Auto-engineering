"""v5.5 audit P1-4: Task + TaskResult dataclass 测试."""

from __future__ import annotations


class TestTask:
    """Task dataclass 构造与默认值."""

    def test_task_default_construction(self):
        """Task 最小构造: id + description + expected_output."""
        from auto_engineering.runtime.task import Task

        t = Task(id="t1", description="desc", expected_output="out")
        assert t.id == "t1"
        assert t.description == "desc"
        assert t.expected_output == "out"

    def test_task_default_factories(self):
        """默认 factory: tools/input_channels/output_channels 为空 list."""
        from auto_engineering.runtime.task import Task

        t = Task(id="t1", description="d", expected_output="e")
        assert t.tools == []
        assert t.input_channels == []
        assert t.output_channels == []
        assert t.output_schema is None

    def test_task_custom_tools_and_channels(self):
        """自定义 tools + channels."""
        from auto_engineering.runtime.task import Task

        t = Task(
            id="t2",
            description="d",
            expected_output="e",
            tools=["read_file", "write_file"],
            input_channels=["plan"],
            output_channels=["files_changed"],
        )
        assert t.tools == ["read_file", "write_file"]
        assert t.input_channels == ["plan"]
        assert t.output_channels == ["files_changed"]

    def test_task_with_output_schema(self):
        """output_schema 可为 dict."""
        from auto_engineering.runtime.task import Task

        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        t = Task(id="t3", description="d", expected_output="e", output_schema=schema)
        assert t.output_schema == schema

    def test_task_mutable_fields(self):
        """Task 字段 mutable — 运行时可调整."""
        from auto_engineering.runtime.task import Task

        t = Task(id="t1", description="d", expected_output="e")
        t.tools.append("bash")
        t.output_channels.append("commit_hash")
        assert "bash" in t.tools
        assert "commit_hash" in t.output_channels


class TestTaskResult:
    """TaskResult dataclass 构造与默认值."""

    def test_taskresult_minimal_construction(self):
        """TaskResult 最小构造: task_id + values."""
        from auto_engineering.runtime.task import TaskResult

        r = TaskResult(task_id="t1", values={"out": "ok"})
        assert r.task_id == "t1"
        assert r.values == {"out": "ok"}

    def test_taskresult_defaults(self):
        """默认值: raw_response=None, tool_calls=[], agent_type=''."""
        from auto_engineering.runtime.task import TaskResult

        r = TaskResult(task_id="t1", values={})
        assert r.raw_response is None
        assert r.tool_calls == []
        assert r.agent_type == ""

    def test_taskresult_full_construction(self):
        """完整构造含所有字段."""
        from auto_engineering.runtime.task import TaskResult

        r = TaskResult(
            task_id="t1",
            values={"files_changed": ["a.py"]},
            raw_response="LLM output text",
            tool_calls=[{"name": "write_file", "args": {"path": "a.py"}}],
            agent_type="developer",
        )
        assert r.task_id == "t1"
        assert r.raw_response == "LLM output text"
        assert len(r.tool_calls) == 1
        assert r.agent_type == "developer"

    def test_taskresult_mutable_fields(self):
        """TaskResult 字段 mutable."""
        from auto_engineering.runtime.task import TaskResult

        r = TaskResult(task_id="t1", values={})
        r.tool_calls.append({"name": "read_file"})
        r.agent_type = "critic"
        assert len(r.tool_calls) == 1
        assert r.agent_type == "critic"


class TestAgentTaskAlias:
    """AgentTask = Task 向后兼容别名."""

    def test_agent_task_is_task(self):
        """AgentTask 和 Task 是同一个类."""
        from auto_engineering.runtime.task import AgentTask, Task

        assert AgentTask is Task

    def test_agent_task_construction(self):
        """用 AgentTask 构造等价于 Task."""
        from auto_engineering.runtime.task import AgentTask

        t = AgentTask(id="at1", description="d", expected_output="e")
        assert t.id == "at1"
        assert t.tools == []
