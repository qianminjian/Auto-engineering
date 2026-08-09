"""Developer Gate 的执行与 Stage 分派服务。"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.state import EngineState
from auto_engineering.loop.architecture_baseline import select_active_contracts


class GateRunner(Protocol):
    def run(
        self,
        files_changed: Sequence[str],
        *,
        stage: str,
        tick: int,
        contracts: dict[str, Any] | None = None,
    ) -> tuple[dict, float]: ...


class StageGateDispatcher:
    """集中定义 Developer Gate 的正常与强制刷新条件。"""

    def dispatch(
        self,
        stage: str,
        run_developer_gates: Callable[[], None],
        *,
        force: bool = False,
    ) -> None:
        if (force and stage != "developer") or (not force and stage == "developer"):
            run_developer_gates()


class DeveloperGateService:
    def __init__(self, runner: GateRunner) -> None:
        self._runner = runner

    def run(
        self,
        *,
        state: EngineState,
        batch_state: BatchState | None,
        developer_snapshot: Mapping[str, Any] | None,
    ) -> float:
        snapshot_files = (
            developer_snapshot.get("files_changed", [])
            if developer_snapshot and not state.files_changed
            else state.files_changed
        )
        baseline = state.architecture_baseline or {}
        reached = batch_state.completed_batch_ids() if batch_state else set()
        if batch_state is not None and not batch_state.is_component_complete():
            reached.add(batch_state.current_batch_id())
        contracts = select_active_contracts(baseline, reached)
        results, duration_ms = self._runner.run(
            snapshot_files,
            stage=state.current_stage,
            tick=state.tick,
            contracts=contracts,
        )
        state.gate_results = results
        return duration_ms


__all__ = ["DeveloperGateService", "StageGateDispatcher"]
