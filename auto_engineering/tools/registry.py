"""ToolRegistry — 工具注册表.

设计: design/LOOP-DEVELOPMENT-PLAN.md Phase 3 文件 13.

按 name 索引 BaseTool 实例，提供:
- register(tool): 添加（重名抛 ValueError）
- get(name): 查找（不存在返回 None）
- list_tools(): 所有工具列表
- to_schemas(): 转 Anthropic tool_use schema 列表
"""

from __future__ import annotations

from .base import BaseTool


class ToolRegistry:
    """工具注册表。"""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name!r} already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def to_schemas(self) -> list[dict]:
        return [tool.to_schema() for tool in self._tools.values()]