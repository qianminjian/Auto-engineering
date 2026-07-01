"""工具系统 — Agent 可用的文件/Bash/Git/测试工具.

v2.0 真接后导出:
    - 10 个 BaseTool 子类实例
      (ReadFile/WriteFile/EditFile/SearchCode/ListDir/RunBash/
       GitStatus/GitCommit/GitDiff/RunTests)
    - ToolRegistry + default_registry 单例
"""

from .base import BaseTool, ToolResult
from .bash_tools import RunBashTool
from .file_tools import EditFileTool, ListDirTool, ReadFileTool, SearchCodeTool, WriteFileTool
from .git_tools import GitCommitTool, GitDiffTool, GitStatusTool
from .registry import ToolRegistry, default_registry
from .test_tools import RunTestsTool

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
    "ToolRegistry",
    "ToolResult",
    "WriteFileTool",
    "default_registry",
]
