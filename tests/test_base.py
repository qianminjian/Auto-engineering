"""Tests for tools/base.py — Phase 3 C3a.

工具基础（BaseTool + ToolResult + to_schema）已有 parallel work 实现.
本测试文件验证 API 契约 + 边界场景.

设计: design/LOOP-DEVELOPMENT-PLAN.md Phase 3 文件 12.
来源: AutoGen _base.py Tool Protocol.
"""

from __future__ import annotations

import pytest


class TestToolResult:
    """ToolResult 数据类 — 工具调用的结构化结果."""

    def test_success_result(self):
        from auto_engineering.tools.base import ToolResult

        r = ToolResult(success=True, content="file written")
        assert r.success is True
        assert r.content == "file written"
        assert r.error is None

    def test_failure_result_includes_error(self):
        from auto_engineering.tools.base import ToolResult

        r = ToolResult(success=False, content="", error="file not found")
        assert r.success is False
        assert r.error == "file not found"

    def test_default_error_is_none(self):
        from auto_engineering.tools.base import ToolResult

        r = ToolResult(success=True, content="ok")
        assert r.error is None


class TestBaseTool:
    """BaseTool 抽象基类 + to_schema 方法."""

    def test_tool_metadata_attributes(self):
        from auto_engineering.tools.base import BaseTool

        class Echo(BaseTool):
            name = "echo"
            description = "Echo input"
            parameters = {"text": "string"}

            def execute(self, text: str) -> ToolResult:
                return ToolResult(success=True, content=text)

        tool = Echo()
        assert tool.name == "echo"
        assert tool.description == "Echo input"
        assert tool.parameters == {"text": "string"}

    def test_tool_execute_returns_tool_result(self):
        from auto_engineering.tools.base import BaseTool, ToolResult

        class Echo(BaseTool):
            name = "echo"
            description = "Echo input"
            parameters = {"text": "string"}

            def execute(self, text: str) -> ToolResult:
                return ToolResult(success=True, content=text)

        tool = Echo()
        result = tool.execute(text="hello")
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.content == "hello"

    def test_to_schema_returns_anthropic_format(self):
        from auto_engineering.tools.base import BaseTool

        class Calc(BaseTool):
            name = "calc"
            description = "Calculate"
            parameters = {"a": "integer", "b": "integer"}

            def execute(self, a: int, b: int) -> ToolResult:
                return ToolResult(success=True, content=str(a + b))

        tool = Calc()
        schema = tool.to_schema()
        assert schema["name"] == "calc"
        assert schema["description"] == "Calculate"
        assert schema["input_schema"]["type"] == "object"
        assert schema["input_schema"]["properties"] == {"a": "integer", "b": "integer"}
        assert set(schema["input_schema"]["required"]) == {"a", "b"}

    def test_abstract_subclass_cannot_be_instantiated(self):
        from auto_engineering.tools.base import BaseTool

        class Incomplete(BaseTool):
            name = "incomplete"
            description = "missing execute"

        with pytest.raises(TypeError):
            Incomplete()