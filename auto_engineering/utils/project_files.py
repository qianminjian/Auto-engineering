"""项目根文件遍历的单一、有界实现。"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from pathlib import Path

PROJECT_SCAN_SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".ae-state",
        ".ae-runtime",
        ".ae-plugin",
        ".gitnexus",
        ".uv-cache",
        "dist",
        "build",
        ".eggs",
        "_scratch",
        ".planning",
        ".tox",
        ".nox",
    }
)


def iter_project_files(
    project_root: Path,
    *,
    skip_dirs: Iterable[str] = (),
) -> Iterator[Path]:
    """剪枝遍历项目文件，不进入被排除的目录。

    运行时状态、依赖缓存和历史证据可能包含数万文件；先用 ``rglob``
    全量枚举再按路径丢弃，会把被排除目录的 I/O 成本错误地带入 Core。
    这里统一使用 top-down ``os.walk``，在进入目录前剪枝，并固定目录/文件
    顺序以保持扫描结果确定性。目录 symlink 不跟随，文件 symlink 仍作为
    文件交给调用方做各自的边界校验。
    """

    root = project_root.resolve()
    excluded = frozenset(skip_dirs)
    for directory, directories, files in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        directories[:] = sorted(
            name for name in directories if name not in excluded
        )
        for name in sorted(files):
            yield Path(directory) / name


__all__ = ["PROJECT_SCAN_SKIP_DIRS", "iter_project_files"]
