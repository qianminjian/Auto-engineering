"""Host Action 工作文件的项目根约束与目录准备。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path


def root_bound_path(path: Path, root: Path) -> Path:
    """将协议中的相对路径绑定到显式项目根。"""

    return path.resolve() if path.is_absolute() else (root / path).resolve()


def ensure_action_work_file_parents(
    mapped: Mapping[str, object],
    root: Path,
) -> None:
    """预创建受控 work file 父目录，不创建业务事实。"""

    host_execution = mapped.get("host_execution")
    work_files = (
        host_execution.get("work_files")
        if isinstance(host_execution, Mapping)
        else None
    )
    if not isinstance(work_files, Mapping):
        return
    project_root = root.resolve()
    for key in ("outcomes", "coordinator_result", "result"):
        raw_path = work_files.get(key)
        if not isinstance(raw_path, str) or not raw_path:
            continue
        target = root_bound_path(Path(raw_path), root)
        if not target.is_relative_to(project_root):
            raise ValueError("HOST_ACTION_WORK_FILE_PATH_ESCAPE")
        target.parent.mkdir(parents=True, exist_ok=True)
