"""hello_world 工具测试."""
from __future__ import annotations

import pytest

from auto_engineering.tools.hello_world import HelloWorldTool


@pytest.mark.asyncio
async def test_hello_world_name_and_description() -> None:
    """HelloWorldTool 名称与描述正确。"""
    tool = HelloWorldTool()
    assert tool.name == "hello_world"
    assert "Hello" in tool.description


@pytest.mark.asyncio
async def test_hello_world_execute_returns_greeting() -> None:
    """execute() 返回预期问候语。"""
    tool = HelloWorldTool()
    result = await tool.execute()
    assert result.success is True
    assert result.content == "Hello, Auto-Engineering!"


@pytest.mark.asyncio
async def test_hello_world_parameters_empty() -> None:
    """HelloWorldTool 无参数，parameters 为空 dict。"""
    tool = HelloWorldTool()
    assert tool.parameters == {}
