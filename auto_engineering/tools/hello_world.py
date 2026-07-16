"""hello_world — 最简工具，返回问候语。"""
from __future__ import annotations

import logging
from typing import Any, ClassVar

from .base import BaseTool, ToolResult

__all__ = ["HelloWorldTool"]

_logger = logging.getLogger("ae.tools.hello_world")


class HelloWorldTool(BaseTool):
    """问候语工具 — 无参数，execute() 返回固定字符串."""

    name: str = "hello_world"
    description: str = "返回 'Hello, Auto-Engineering!' 问候语，零依赖零参数"
    parameters: ClassVar[dict[str, Any]] = {}

    async def execute(self, **kwargs: Any) -> ToolResult:
        _logger.debug("hello_world 工具被调用")
        return ToolResult(success=True, content="Hello, Auto-Engineering!")
