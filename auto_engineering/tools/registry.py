"""ToolRegistry — 工具注册表.

设计: design/LOOP-DEVELOPMENT-PLAN.md v2.0 文件 13.

按 name 索引 BaseTool 实例,提供:
- register(tool): 添加（重名抛 ValueError）
- get(name): 查找（不存在返回 None）
- list_tools(): 所有工具列表
- to_schemas(): 转 Anthropic tool_use schema 列表
- resolve(names): 按名列表取实例(找不到抛 KeyError)
- default_registry(): 构造含 10 个内置工具的 registry 单例
"""

from __future__ import annotations

from .base import BaseTool
from .bash_tools import RunBashTool
from .file_tools import (
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    SearchCodeTool,
    WriteFileTool,
)
from .git_tools import GitCommitTool, GitDiffTool, GitStatusTool
from .test_tools import RunTestsTool


class ToolRegistry:
    """工具注册表."""

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

    def resolve(self, names: list[str]) -> list[BaseTool]:
        """按名列表取实例. 找不到抛 KeyError."""
        result = []
        for name in names:
            tool = self._tools.get(name)
            if tool is None:
                raise KeyError(f"Tool '{name}' not registered")
            result.append(tool)
        return result


def default_registry() -> ToolRegistry:
    """构造含 10 个内置工具的 registry."""
    registry = ToolRegistry()
    for tool in [
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        SearchCodeTool(),
        ListDirTool(),
        RunBashTool(),
        GitStatusTool(),
        GitCommitTool(),
        GitDiffTool(),
        RunTestsTool(),
    ]:
        registry.register(tool)
    return registry
