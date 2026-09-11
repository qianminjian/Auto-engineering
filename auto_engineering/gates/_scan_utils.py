"""Shared file-scanning infrastructure for Gate implementations.

Extracted from safety.py and audit.py (P1-13 dedup).
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

__all__ = [
    "DEFAULT_MAX_FILE_MB",
    "DEFAULT_SKIP_DIRS",
    "find_silent_except_lines",
    "iter_scan_files",
    "read_file_safe",
    "should_skip_path",
]

_logger = logging.getLogger("ae.gates.scan_utils")

DEFAULT_MAX_FILE_MB = 5

# Audit/Safety 共享同一套业务源码扫描边界；依赖运行时、生成物和测试夹具
# 不属于被 Gate 评估的业务实现，避免两个 Gate 各自维护一份易漂移的列表。
DEFAULT_SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ae-state",
        ".ae-plugin",
        ".gitnexus",
        ".uv-cache",
        ".ae-runtime",
        "dist",
        "build",
        ".eggs",
        "tests",
        "_scratch",
        ".planning",
    }
)


def find_silent_except_lines(content: str) -> list[int]:
    """返回仅空处理或仅 ``pass`` 的异常处理行号。"""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    lines = content.splitlines()
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and "noqa" not in lines[node.lineno - 1].lower()
        and (not node.body or all(isinstance(statement, ast.Pass) for statement in node.body))
    ]


def read_file_safe(path: Path, max_size_mb: int = DEFAULT_MAX_FILE_MB) -> str | None:
    """Read file content with size guard and error handling.

    Returns None if the file is too large or unreadable.
    """
    try:
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > max_size_mb:
            return None
        return path.read_text(errors="ignore")
    except (OSError, UnicodeDecodeError):
        _logger.debug("scan: 不可读文件 %s", path)
        return None


def should_skip_path(path: Path, skip_dirs: set[str]) -> bool:
    """Check if path is inside any skip_dir."""
    return any(part in skip_dirs for part in path.parts)


def iter_scan_files(
    project_root: Path,
    *,
    extensions: set[str] | None = None,
    skip_dirs: set[str] | None = None,
) -> list[tuple[Path, str]]:
    """Collect files matching extensions, excluding skip_dirs.

    Returns list of (absolute_path, relative_path_str).
    """
    _skip = skip_dirs or set()
    _exts = extensions
    files: list[tuple[Path, str]] = []
    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        if should_skip_path(path, _skip):
            continue
        if _exts is not None and path.suffix.lower() not in _exts:
            continue
        rel = str(path.relative_to(project_root))
        files.append((path, rel))
    return files
