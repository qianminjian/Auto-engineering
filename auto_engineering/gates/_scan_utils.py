"""Shared file-scanning infrastructure for Gate implementations.

Extracted from safety.py and audit.py (P1-13 dedup).
"""

from __future__ import annotations

import logging
from pathlib import Path

_logger = logging.getLogger("ae.gates.scan_utils")

DEFAULT_MAX_FILE_MB = 5


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
