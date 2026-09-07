"""Developer 变更证据辅助逻辑。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from auto_engineering.engine.state import EngineState


def declared_real_files(state: EngineState, root: Path) -> set[str]:
    """返回位于项目内且真实存在的声明文件，拒绝路径穿越。"""
    resolved_root = root.resolve()
    evidence: set[str] = set()
    for raw in getattr(state, "files_changed", []) or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        candidate = Path(raw)
        candidate = candidate if candidate.is_absolute() else resolved_root / candidate
        try:
            resolved = candidate.resolve(strict=True)
            relative = resolved.relative_to(resolved_root)
        except (OSError, ValueError):
            continue
        if resolved.is_file():
            evidence.add(relative.as_posix())
    return evidence


def verification_only_batch_ready(state: EngineState, root: Path) -> bool:
    """允许已存在目标的验证型 batch 以零 diff 结束。"""
    test_results = getattr(state, "test_results", {}) or {}
    if (
        not isinstance(test_results, dict)
        or not isinstance(test_results.get("passed"), int)
        or isinstance(test_results.get("passed"), bool)
        or test_results.get("passed", 0) < 1
        or test_results.get("failed", 0) != 0
    ):
        return False
    # TickOrchestrator injects these non-persistent handles into _runtime_ctx
    # before running the Guardrail.  Direct attributes are kept as a small
    # compatibility seam for isolated callers/tests, but are not the runtime
    # contract and are absent after EngineState reconstruction.
    runtime_ctx = getattr(state, "_runtime_ctx", {}) or {}
    batch_state = getattr(state, "batch_state", None) or runtime_ctx.get(
        "batch_state"
    )
    plan = getattr(state, "_plan", None) or runtime_ctx.get("plan")
    if batch_state is None or plan is None:
        return False
    try:
        tasks = batch_state.current_batch_tasks(plan)
    except (AttributeError, TypeError, ValueError):
        return False
    targets = [
        str(target)
        for task in tasks
        for target in getattr(task, "target_files", ()) or ()
    ]
    if not targets:
        return False
    resolved_root = root.resolve()
    for target in targets:
        candidate = Path(target)
        candidate = candidate if candidate.is_absolute() else resolved_root / candidate
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(resolved_root)
        except (OSError, ValueError):
            return False
        if not resolved.is_file():
            return False
    return True
