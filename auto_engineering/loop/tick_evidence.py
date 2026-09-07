"""Tick 观测与变更证据的 canonical helpers。"""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable
from typing import Protocol

from auto_engineering.engine.state import EngineState

_logger = logging.getLogger("ae.loop.tick_evidence")


class TickEvidenceTarget(Protocol):
    """观测 helper 所需的最小 Orchestrator 视图。"""

    project_root: object
    _state: EngineState | None
    _active_action: dict | None
    _t_gate_ms: float
    _t_guard_sub_ms: float


def record_tick_latency(
    target: TickEvidenceTarget,
    t_start: float,
    tick_no: int,
    *,
    budget_ms: int,
) -> None:
    """记录 Tick 延迟；超预算只告警，不改变 Tick 结果。"""
    if target._state is None:
        return
    t_total_ms = (time.perf_counter() - t_start) * 1000
    t_gate_ms = target._t_gate_ms
    t_guard_sub_ms = target._t_guard_sub_ms
    t_orch_ms = t_total_ms - t_gate_ms - t_guard_sub_ms
    active_spawn = (
        target._active_action.get("spawn")
        if isinstance(target._active_action, dict)
        else None
    )
    spawn_count = (
        active_spawn.get("count")
        if isinstance(active_spawn, dict)
        else 0
    )
    target._state.action_history.append({
        "tick": tick_no,
        "stage": target._state.current_stage,
        "spawn_count": spawn_count if isinstance(spawn_count, int) else 0,
        "t_total_ms": round(t_total_ms, 2),
        "t_gate_ms": round(t_gate_ms, 2),
        "t_guard_sub_ms": round(t_guard_sub_ms, 2),
        "t_orchestration_ms": round(t_orch_ms, 2),
    })
    if t_orch_ms > budget_ms:
        _logger.warning(
            "[latency] tick %d 编排开销 %.0fms 超预算 %dms "
            "(total=%.0f gate=%.0f guard_sub=%.0f)",
            tick_no, t_orch_ms, budget_ms,
            t_total_ms, t_gate_ms, t_guard_sub_ms,
        )


def compute_diff_stats(
    target: TickEvidenceTarget,
    files_changed: list,
    *,
    git_runner: Callable | None = None,
) -> tuple[int, int]:
    """从 git diff --numstat 计算变更行数；失败时返回零值证据。"""
    if not files_changed:
        return 0, 0
    try:
        runner = git_runner if git_runner is not None else subprocess.run
        result = runner(
            ["git", "-C", str(target.project_root), "diff", "--numstat"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return 0, 0
        added = 0
        removed = 0
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                if parts[0] == "-" and parts[1] == "-":
                    continue
                try:
                    if parts[0] != "-":
                        added += int(parts[0])
                    if parts[1] != "-":
                        removed += int(parts[1])
                except ValueError:
                    _logger.debug(
                        "git diff numstat parse failed: %s", line, exc_info=True,
                    )
        return added, removed
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0, 0
