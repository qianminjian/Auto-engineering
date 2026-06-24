"""Bash 工具 — Phase 0.2 真接.

安全策略:
    - 默认 timeout 120s(可调)
    - P1.5: 危险命令黑名单(rm -rf /, dd if=, mkfs, chmod 777 /etc/, > /etc/)
    - 捕获 stdout + stderr + returncode
    - 返回 ToolResult(success, content)
"""

from __future__ import annotations

import re
import subprocess

from .base import BaseTool, ToolResult


class RunBashTool(BaseTool):
    """Execute shell command with dangerous pattern blacklist.

    P1.5: 黑名单检测在 subprocess.run 之前执行,防止破坏性命令.
    """

    name = "run_bash"
    description = "Execute shell command and return output. Blocks until done or timeout."
    parameters = {
        "command": {"type": "string", "description": "Shell command to execute"},
        "cwd": {"type": "string", "description": "Working directory (optional)"},
        "timeout": {"type": "integer", "description": "Timeout in seconds (default 120)"},
    }

    # 黑名单: 匹配则拒绝执行
    DANGEROUS_PATTERNS: list[str] = [
        r"rm\s+-rf\s+/\s*$",  # rm -rf / 或 rm -rf /...
        r"rm\s+-rf\s+/",  # rm -rf /任意位置(保守)
        r"dd\s+if=",  # dd 直接复制设备
        r"mkfs",  # 文件系统创建
        r"chmod\s+777\s+/etc",  # chmod 777 /etc
        r">\s*/etc/",  # 重定向到 /etc
    ]

    async def execute(self, **kwargs) -> ToolResult:
        command = kwargs.get("command", "")
        cwd = kwargs.get("cwd")
        timeout = int(kwargs.get("timeout", 120))

        if not command:
            return ToolResult(success=False, content="", error="command is empty")

        # P1.5: 黑名单检查
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command):
                return ToolResult(
                    success=False,
                    content="",
                    error=f"dangerous command blocked: {command[:60]}",
                )

        try:
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
                success=False,
                content="",
                error=f"Command timed out after {timeout}s",
            )
        except Exception as exc:
            return ToolResult(success=False, content="", error=str(exc))
