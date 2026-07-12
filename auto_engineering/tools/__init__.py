"""工具系统 — Agent 可用的文件/Bash/Git/测试工具.

⚠️ 双驱动共享资产 (v7.0 T33b, BEACON #54): 本执行栈 (agents/ + runtime/ + tools/ +
loop/round.py) 是 Driver A (Claude Code Agent 填 result) 与 Driver B (StandaloneDriver,
v7.0 进程内自带 key 调 LLM) 的共享引擎, 且 `ae agent` CLI 已独立依赖。退役 v5.5
orchestrator 循环时不得连带删除本执行层 —— Driver B 复用 v5.5 执行栈
(`_step_2e_run_agent` → run_round/AgentRuntime/BaseAgent) 作 tick 填充器。
详见 design/v7.0-Plan-DualDriver.md §2.3.
"""

from .base import BaseTool, ToolResult
from .bash_tools import RunBashTool
from .file_tools import EditFileTool, ListDirTool, ReadFileTool, SearchCodeTool, WriteFileTool
from .git_tools import GitCommitTool, GitDiffTool, GitStatusTool
from .run_tests_tool import RunTestsTool

__all__ = [
    "BaseTool",
    "EditFileTool",
    "GitCommitTool",
    "GitDiffTool",
    "GitStatusTool",
    "ListDirTool",
    "ReadFileTool",
    "RunBashTool",
    "RunTestsTool",
    "SearchCodeTool",
    "ToolResult",
    "WriteFileTool",
]
