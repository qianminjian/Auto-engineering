"""Bash 工具 — v2.0 真接.

安全策略:
    - 默认 timeout 120s(可调)
    - P1.5: 危险命令黑名单(rm -rf /, dd if=, mkfs, chmod 777 /etc/, > /etc/)
    - v2.5 P1-S2: 扩展黑名单 + 审计日志 (每个命令执行前记录, 用于事后追溯)
    - 捕获 stdout + stderr + returncode
    - 返回 ToolResult(success, content)

安全模型: shell=True 是 LLM agent 工具的设计选择 (允许 pipeline / redirect).
黑名单是 defense-in-depth 而非绝对防御. 真防御: 沙箱化执行环境 (e.g.,
container with no network, read-only root fs). 详见 BEACON §v2.5 P1-S2.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import ClassVar

from .base import BaseTool, ToolResult

__all__ = ["RunBashTool"]

# v5.4 审计 P2-8: logger 命名统一为 _logger (曾用 _audit_logger)
_logger = logging.getLogger("ae.tools.bash")


class RunBashTool(BaseTool):
    """Execute shell command with dangerous pattern blacklist.

    P1.5: 黑名单检测在 subprocess.run 之前执行,防止破坏性命令.
    v2.5 P1-S2: 扩展黑名单 (curl|sh / python -c / base64 -d 等 RCE proxy)
    + 审计日志 (每个 command 在执行前 INFO 级别记录, 含 cwd / timeout).
    """

    name = "run_bash"
    description = "Execute shell command and return output. Blocks until done or timeout."
    parameters: ClassVar[dict] = {
        "command": {"type": "string", "description": "Shell command to execute", "required": True},
        "cwd": {"type": "string", "description": "Working directory (optional)"},
        "timeout": {"type": "integer", "description": "Timeout in seconds (default 120)"},
    }

    # 黑名单: 匹配则拒绝执行
    # 2026-07-04 修复 (v5.0 深度审计 P1-D-05): 统一为 13 模式与 hooks/pre-tool.sh 对齐.
    # 删除 python -c 模式 (原第 14), 避免客户端/服务端黑名单不一致.
    DANGEROUS_PATTERNS: ClassVar[list[str]] = [
        # P1.5 原列表
        r"rm\s+-rf\s+/\s*$",  # rm -rf / 或 rm -rf /...
        r"rm\s+-rf\s+/",  # rm -rf /任意位置(保守)
        r"dd\s+if=",  # dd 直接复制设备
        r"mkfs",  # 文件系统创建
        r"chmod\s+777\s+/etc",  # chmod 777 /etc
        r">\s*/etc/",  # 重定向到 /etc
        # v2.5 P1-S2 扩展: RCE proxy / 反向 shell / 数据外泄
        r"\bcurl\b.*\|\s*(ba)?sh\b",  # curl ... | sh / bash (下载即执行)
        r"\bwget\b.*\|\s*(ba)?sh\b",  # wget ... | sh / bash
        r"\bnc\b.*-[a-zA-Z]*e\b",  # nc -e (反向 shell)
        r"\bncat\b.*-[a-zA-Z]*e\b",  # ncat -e
        r"\bbash\s+-i\b.*>/dev/tcp/",  # bash interactive + /dev/tcp (反弹 shell)
        r"\beval\s+\$\(",  # eval $(...) 命令替换注入
        r"\bbase64\s+-d\b.*\|\s*(ba)?sh\b",  # base64 -d | sh
        # python -c 已删除 (统一为 13 模式, 与 hooks/pre-tool.sh 一致)
    ]

    async def execute(self, **kwargs) -> ToolResult:
        command = kwargs.get("command", "")
        cwd = kwargs.get("cwd")
        timeout = int(kwargs.get("timeout", 120))

        if not command:
            return ToolResult(success=False, content="", error="command is empty")

        # v7.0: cwd 不存在或无法访问 → 回退到 project_root (DeepSeek 幻觉 /workspace 等路径)
        if cwd and not os.path.isdir(str(cwd)):
            cwd = str(self.project_root) if self.project_root else None

        # P1.5: 黑名单检查
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command):
                _logger.warning(
                    "bash_blocked: pattern=%s command=%r cwd=%s",
                    pattern, command[:200], cwd,
                )
                return ToolResult(
                    success=False,
                    content="",
                    error=f"dangerous command blocked: {command[:60]}",
                )

        # v2.5 P1-S2: 审计日志 — 每个执行的命令 INFO 记录
        _logger.info(
            "bash_exec: command=%r cwd=%s timeout=%ds", command[:500], cwd, timeout
        )

        try:
            _logger.warning("bash_exec shell=True: %s", command[:200])
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = (result.stdout or "") + (result.stderr or "")
            _logger.info(
                "bash_done: returncode=%d elapsed=ok cmd=%r", result.returncode, command[:200]
            )
            return ToolResult(
                success=(result.returncode == 0),
                content=output.strip(),
                error=None if result.returncode == 0 else f"exit code {result.returncode}",
            )
        except subprocess.TimeoutExpired:
            _logger.warning("bash_timeout: command=%r timeout=%ds", command[:200], timeout)
            return ToolResult(
                success=False,
                content="",
                error=f"Command timed out after {timeout}s",
            )
        except Exception as exc:
            _logger.error("bash_error: command=%r error=%r", command[:200], exc)
            return ToolResult(success=False, content="", error=str(exc))
