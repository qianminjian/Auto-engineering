"""文件操作工具 — Phase 0.2 真接.

5 个工具: ReadFile / WriteFile / EditFile / SearchCode / ListDir.
"""

from __future__ import annotations

from pathlib import Path

from .base import BaseTool, ToolResult


class ReadFileTool(BaseTool):
    """Read file content with optional line range. 行号 1-based."""

    name = "read_file"
    description = "Read file content. Supports line range via offset/limit."
    parameters = {
        "file_path": {"type": "string", "description": "Absolute file path"},
        "offset": {"type": "integer", "description": "Start line (1-based, default 1)"},
        "limit": {"type": "integer", "description": "Lines to read (default 200)"},
    }

    async def execute(self, **kwargs) -> ToolResult:
        path = Path(kwargs.get("file_path", ""))
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
            return ToolResult(success=False, content="", error=str(exc))


class WriteFileTool(BaseTool):
    """Create or overwrite file. 自动创建父目录."""

    name = "write_file"
    description = "Create or overwrite a file. Auto-creates parent directories."
    parameters = {
        "file_path": {"type": "string", "description": "Absolute file path"},
        "content": {"type": "string", "description": "Full file content"},
    }

    async def execute(self, **kwargs) -> ToolResult:
        path = Path(kwargs.get("file_path", ""))
        content = kwargs.get("content", "")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return ToolResult(success=True, content=f"Wrote {len(content)} bytes to {path}")
        except Exception as exc:
            return ToolResult(success=False, content="", error=str(exc))


class EditFileTool(BaseTool):
    """Replace exact string in file. 旧串不存在 → error."""

    name = "edit_file"
    description = "Replace exact string in file. Returns error if old_string not found."
    parameters = {
        "file_path": {"type": "string", "description": "Absolute file path"},
        "old_string": {"type": "string", "description": "Existing string to replace"},
        "new_string": {"type": "string", "description": "Replacement string"},
    }

    async def execute(self, **kwargs) -> ToolResult:
        path = Path(kwargs.get("file_path", ""))
        old = kwargs.get("old_string", "")
        new = kwargs.get("new_string", "")
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
            return ToolResult(success=True, content=f"Edited {path}")
        except Exception as exc:
            return ToolResult(success=False, content="", error=str(exc))


class SearchCodeTool(BaseTool):
    """Grep-like search in project files."""

    name = "search_code"
    description = "Search regex pattern in files. Returns matching lines with file:line:content."
    parameters = {
        "pattern": {"type": "string", "description": "Regex pattern"},
        "path": {"type": "string", "description": "Directory to search (default '.')"},
        "file_pattern": {"type": "string", "description": "Glob file filter (e.g. '*.py')"},
    }

    async def execute(self, **kwargs) -> ToolResult:
        import re

        pattern = kwargs.get("pattern", "")
        path = Path(kwargs.get("path", "."))
        file_pattern = kwargs.get("file_pattern")
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
                    continue
            if not matches:
                return ToolResult(success=True, content="(no matches)")
            return ToolResult(success=True, content="\n".join(matches[:100]))
        except Exception as exc:
            return ToolResult(success=False, content="", error=str(exc))


class ListDirTool(BaseTool):
    """List directory contents."""

    name = "list_dir"
    description = "List files and subdirectories in a directory."
    parameters = {
        "path": {"type": "string", "description": "Directory path (default '.')"},
    }

    async def execute(self, **kwargs) -> ToolResult:
        path = Path(kwargs.get("path", "."))
        try:
            if not path.exists():
                return ToolResult(success=False, content="", error=f"Path not found: {path}")
            if not path.is_dir():
                return ToolResult(success=False, content="", error=f"Not a directory: {path}")
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
            lines = [f"{'[D]' if e.is_dir() else '[F]'} {e.name}" for e in entries]
            return ToolResult(success=True, content="\n".join(lines) or "(empty)")
        except Exception as exc:
            return ToolResult(success=False, content="", error=str(exc))
