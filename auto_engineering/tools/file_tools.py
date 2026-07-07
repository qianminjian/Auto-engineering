"""文件操作工具 — v2.0 真接.

5 个工具: ReadFile / WriteFile / EditFile / SearchCode / ListDir.

P1.5: WriteFileTool/EditFileTool 支持 project_root 白名单验证.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

from .base import BaseTool, ToolResult

__all__ = ["ReadFileTool", "WriteFileTool", "EditFileTool", "SearchCodeTool", "ListDirTool"]

_logger = logging.getLogger("ae.tools.file_tools")


class ReadFileTool(BaseTool):
    """Read file content with optional line range and project_root whitelist.

    P1-C: project_root 限制读取操作必须在目录内.
    """

    name = "read_file"
    description = "Read file content. Supports line range via offset/limit."
    parameters: ClassVar[dict] = {
        "file_path": {"type": "string", "description": "Absolute file path"},
        "offset": {"type": "integer", "description": "Start line (1-based, default 1)"},
        "limit": {"type": "integer", "description": "Lines to read (default 200)"},
    }

    async def execute(self, **kwargs) -> ToolResult:
        file_path = kwargs.get("file_path", "")

        if err_result := self._validate_path(file_path):
            return err_result

        path = Path(file_path)
        offset = max(1, int(kwargs.get("offset", 1)))
        limit = int(kwargs.get("limit", 200))
        try:
            if not path.exists():
                return ToolResult(success=False, content="", error=f"File not found: {path}")
            if not path.is_file():
                return ToolResult(success=False, content="", error=f"Not a file: {path}")
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            selected = lines[offset - 1 : offset - 1 + limit]
            return ToolResult(success=True, content="\n".join(selected))
        except Exception as exc:
            _logger.warning("ReadFileTool 失败: %s", exc, exc_info=True)
            return ToolResult(success=False, content="", error=str(exc))


class WriteFileTool(BaseTool):
    """Create or overwrite file with optional project_root whitelist.

    P1.5: project_root 限制写操作必须在目录内.
    """

    name = "write_file"
    description = "Create or overwrite a file. Auto-creates parent directories."
    parameters: ClassVar[dict] = {
        "file_path": {"type": "string", "description": "Absolute file path"},
        "content": {"type": "string", "description": "Full file content"},
    }

    async def execute(self, **kwargs) -> ToolResult:
        file_path = kwargs.get("file_path", "")
        content = kwargs.get("content", "")

        if err_result := self._validate_path(file_path):
            return err_result

        path = Path(file_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            self._fsync(path)
            return ToolResult(success=True, content=f"Wrote {len(content)} bytes to {path}")
        except Exception as exc:
            _logger.warning("WriteFileTool 失败: %s", exc, exc_info=True)
            return ToolResult(success=False, content="", error=str(exc))


class EditFileTool(BaseTool):
    """Replace exact string in file with optional project_root whitelist.

    P1.5: project_root 限制写操作必须在目录内.
    """

    name = "edit_file"
    description = "Replace exact string in file. Returns error if old_string not found."
    parameters: ClassVar[dict] = {
        "file_path": {"type": "string", "description": "Absolute file path"},
        "old_string": {"type": "string", "description": "Existing string to replace"},
        "new_string": {"type": "string", "description": "Replacement string"},
    }

    async def execute(self, **kwargs) -> ToolResult:
        file_path = kwargs.get("file_path", "")
        old = kwargs.get("old_string", "")
        new = kwargs.get("new_string", "")

        if err_result := self._validate_path(file_path):
            return err_result

        path = Path(file_path)
        try:
            if not path.exists():
                return ToolResult(success=False, content="", error=f"File not found: {path}")
            content = path.read_text(encoding="utf-8")
            if old not in content:
                return ToolResult(
                    success=False,
                    content="",
                    error=f"old_string not found in {path}",
                )
            new_content = content.replace(old, new, 1)  # 只替换第一个
            path.write_text(new_content, encoding="utf-8")
            self._fsync(path)
            return ToolResult(success=True, content=f"Edited {path}")
        except Exception as exc:
            _logger.warning("EditFileTool 失败: %s", exc, exc_info=True)
            return ToolResult(success=False, content="", error=str(exc))


class SearchCodeTool(BaseTool):
    """Grep-like search in project files with optional project_root whitelist.

    P0.2: project_root 限制搜索路径必须在目录内.
    """

    name = "search_code"
    description = "Search regex pattern in files. Returns matching lines with file:line:content."
    parameters: ClassVar[dict] = {
        "pattern": {"type": "string", "description": "Regex pattern"},
        "path": {"type": "string", "description": "Directory to search (default '.')"},
        "file_pattern": {"type": "string", "description": "Glob file filter (e.g. '*.py')"},
    }

    async def execute(self, **kwargs) -> ToolResult:
        import re

        pattern = kwargs.get("pattern", "")
        path_str = kwargs.get("path", ".")
        file_pattern = kwargs.get("file_pattern")

        if err_result := self._validate_path(path_str):
            return err_result

        path = Path(path_str)
        try:
            if not path.exists():
                return ToolResult(success=False, content="", error=f"Path not found: {path}")
            regex = re.compile(pattern)
            matches = []
            for file in path.rglob(file_pattern or "*"):
                if not file.is_file():
                    continue
                try:
                    for line_no, line in enumerate(
                        file.read_text(encoding="utf-8", errors="replace").splitlines(),
                        start=1,
                    ):
                        if regex.search(line):
                            matches.append(f"{file}:{line_no}:{line}")
                except Exception:
                    _logger.warning(
                        "SearchCode 文件读取失败: %s", file, exc_info=True,
                    )
                    continue
            if not matches:
                return ToolResult(success=True, content="(no matches)")
            return ToolResult(success=True, content="\n".join(matches[:100]))
        except Exception as exc:
            _logger.warning("SearchCodeTool 失败: %s", exc, exc_info=True)
            return ToolResult(success=False, content="", error=str(exc))


class ListDirTool(BaseTool):
    """List directory contents with project_root whitelist.

    P1-E: project_root 限制列表操作必须在目录内 (2026-07-07 审计 P2-2).
    """

    name = "list_dir"
    description = "List files and subdirectories in a directory."
    parameters: ClassVar[dict] = {
        "path": {"type": "string", "description": "Directory path (default '.')"},
    }

    async def execute(self, **kwargs) -> ToolResult:
        dir_path = kwargs.get("path", ".")

        if err_result := self._validate_path(dir_path):
            return err_result

        path = Path(dir_path)
        try:
            if not path.exists():
                return ToolResult(success=False, content="", error=f"Path not found: {path}")
            if not path.is_dir():
                return ToolResult(success=False, content="", error=f"Not a directory: {path}")
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
            lines = [f"{'[D]' if e.is_dir() else '[F]'} {e.name}" for e in entries]
            return ToolResult(success=True, content="\n".join(lines) or "(empty)")
        except Exception as exc:
            _logger.warning("ListDirTool 失败: %s", exc, exc_info=True)
            return ToolResult(success=False, content="", error=str(exc))
