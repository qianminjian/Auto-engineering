"""Host Action generation 绑定组合器的唯一实现。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


def map_bound_action_for_host(
    action: dict,
    root: Path,
    *,
    include_failure_journal: bool = True,
    bind_worker_execution_identity_fn: Callable,
    map_action_fn: Callable,
) -> dict:
    """先绑定当前宿主代际，再生成宿主投影。"""
    return map_action_fn(
        bind_worker_execution_identity_fn(
            action,
            root,
            include_failure_journal=include_failure_journal,
        )
    )
