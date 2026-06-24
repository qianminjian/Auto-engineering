"""Tests for ToolRegistry — Phase 3 C3b.

设计: design/LOOP-DEVELOPMENT-PLAN.md Phase 3 文件 13.

ToolRegistry:
- register(tool): add tool indexed by name
- get(name): retrieve tool
- list_tools(): all registered
- to_schemas(): list of Anthropic tool_use schemas
"""

from __future__ import annotations

import pytest


class _Echo:
    """最小 BaseTool-like stub for testing."""

    def __init__(self, name="echo", description="Echo input"):
        from auto_engineering.tools.base import BaseTool, ToolResult
        self.name = name
        self.description = description
        self.parameters = {"text": "string"}
        self._BaseTool = BaseTool
        self._ToolResult = ToolResult

    def execute(self, text: str):
        return self._ToolResult(success=True, content=text)

    def to_schema(self):
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {"type": "object", "properties": {"text": "string"}, "required": ["text"]},
        }


class TestToolRegistry:
    """ToolRegistry — 工具注册表."""

    def test_register_and_get(self):
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        tool = _Echo()
        reg.register(tool)
        assert reg.get("echo") is tool

    def test_register_duplicate_name_raises(self):
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        reg.register(_Echo())
        with pytest.raises(ValueError, match="already registered"):
            reg.register(_Echo())  # 同名再次注册

    def test_get_unknown_returns_none(self):
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        assert reg.get("nonexistent") is None

    def test_list_tools_returns_all(self):
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        echo = _Echo(name="echo")
        calc = _Echo(name="calc")
        reg.register(echo)
        reg.register(calc)
        tools = reg.list_tools()
        assert echo in tools
        assert calc in tools
        assert len(tools) == 2

    def test_to_schemas_returns_anthropic_format(self):
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        reg.register(_Echo(name="echo"))
        schemas = reg.to_schemas()
        assert len(schemas) == 1
        assert schemas[0]["name"] == "echo"
        assert "input_schema" in schemas[0]

    def test_to_schemas_empty_registry(self):
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        assert reg.to_schemas() == []