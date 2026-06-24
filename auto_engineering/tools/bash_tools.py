"""Bash 工具 — Phase 0.2 真接.

安全策略:
    - 默认 timeout 120s(可调)
    - 不阻止所有危险命令(rm -rf) — Agent 自治原则
    - 捕获 stdout + stderr + returncode
    - 返回 ToolResult(success, content)
"""
from __future__ import annotations

import subprocess

from .base import BaseTool, ToolResult


class RunBashTool(BaseTool):
    """Execute shell command. 阻塞直到命令完成或 timeout."""

    name = "run_bash"
    description = "Execute shell command and return output. Blocks until done or timeout."
    parameters = {
        "command": {"type": "string", "description": "Shell command to execute"},
        "cwd": {"type": "string", "description": "Working directory (optional)"},
        "timeout": {"type": "integer", "description": "Timeout in seconds (default 120)"},
    }

    async def execute(self, **kwargs) -> ToolResult:
        command = kwargs.get("command", "")
        cwd = kwargs.get("cwd")
        timeout = int(kwargs.get("timeout", 120))
        try:
            if not command:
                return ToolResult(success=False, content="", error="command is empty")
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = (result.stdout or "") + (result.stderr or "")
            return ToolResult(
                success=(result.returncode == 0),
                content=output.strip(),
                error=None if result.returncode == 0 else f"exit code {result.returncode}",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False, content="",
                error=f"Command timed out after {timeout}s",
            )
        except Exception as exc:
            return ToolResult(success=False, content="", error=str(exc))
