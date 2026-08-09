"""Architect 输出到执行结构的显式激活服务。"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.design_doc import DesignDoc
from auto_engineering.engine.progress_tree import ProgressTree
from auto_engineering.engine.state import EngineState
from auto_engineering.engine.verification_layers import (
    VerificationLayers,
    determine_verification_layers,
)
from auto_engineering.loop.architecture_baseline import build_architecture_baseline
from auto_engineering.loop.events import LoopEventType
from auto_engineering.loop.plan import Plan
from auto_engineering.loop.task_factory import tasks_from_batch_plan

EmitEvent = Callable[[LoopEventType, dict], None]


@dataclass(frozen=True, slots=True)
class ArchitectureActivationResult:
    batch_state: BatchState
    plan: Plan
    verification_layers: VerificationLayers
    progress_tree: ProgressTree


class ArchitectureActivationService:
    """物化 Architect 已接受的 batch、baseline 和验证结构。"""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    def activate(
        self,
        *,
        state: EngineState,
        design_doc: DesignDoc | None,
        batch_state: BatchState | None,
        progress_tree: ProgressTree | None,
        verification_layers: VerificationLayers | None,
        emit: EmitEvent,
    ) -> ArchitectureActivationResult:
        raw_candidate = state._runtime_ctx.get("architecture_candidate")
        candidate = raw_candidate if isinstance(raw_candidate, dict) else None
        batches = BatchState.flatten_batch_plan([
            dict(item) for item in state.batch_plan
        ])
        if batch_state is not None and state.plan_refine_count > 0:
            completed = batch_state.completed_batch_ids()
            raw_base_revision = state._runtime_ctx.pop(
                "plan_patch_base_revision",
                state.plan_refine_count,
            )
            base_revision = (
                raw_base_revision
                if isinstance(raw_base_revision, int)
                and not isinstance(raw_base_revision, bool)
                else state.plan_refine_count
            )
            batch_state = batch_state.apply_plan_patch(
                base_revision=base_revision,
                active_revision=state.plan_refine_count,
                add_batches=batches,
                completed_batch_ids=completed,
                design_doc=design_doc,
            )
            batches = batch_state.batch_plan
        else:
            if candidate is not None:
                batches = BatchState.flatten_batch_plan([
                    dict(item) for item in candidate.get("batch_plan", [])
                ])
            batch_state = (
                BatchState.from_design_doc(design_doc, batches)
                if design_doc is not None
                else BatchState.from_batch_plan(batches)
            )

        baseline = self._build_baseline(state, batches)
        state.architecture_baseline = baseline
        emit(LoopEventType.ARCHITECTURE_BASELINE_ACCEPTED, {"baseline": baseline})

        plan = tasks_from_batch_plan(batches, state.requirement)
        if verification_layers is None:
            verification_layers = determine_verification_layers(design_doc, batches)

        if progress_tree is None:
            if design_doc is not None:
                progress_tree = ProgressTree.from_design_doc(design_doc)
                progress_tree.apply_batch_plan_totals(batches)
            else:
                progress_tree = ProgressTree.from_batch_plan(
                    batches,
                    state.requirement,
                )
        elif state.plan_refine_count > 0:
            verification_layers = determine_verification_layers(design_doc, batches)
            if design_doc is not None:
                progress_tree.sync_from_design_doc(design_doc)
            else:
                progress_tree.sync_from_batch_plan(batches)
        return ArchitectureActivationResult(
            batch_state=batch_state,
            plan=plan,
            verification_layers=verification_layers,
            progress_tree=progress_tree,
        )

    def _build_baseline(
        self,
        state: EngineState,
        batches: list[dict],
    ) -> dict:
        design_path = state.design_doc_path or ""
        digest = ""
        if design_path:
            path = Path(design_path)
            if not path.is_absolute():
                path = self._project_root / path
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                digest = ""
        raw_candidate = state._runtime_ctx.pop("architecture_candidate", None)
        if isinstance(raw_candidate, dict):
            candidate_batches = raw_candidate.get("batch_plan", [])
            if candidate_batches != batches:
                raise ValueError("ARCHITECTURE_CANDIDATE_DRIFT")
            contracts = dict(raw_candidate.get("contracts", {}))
            raw_obligations = raw_candidate.get("obligations", [])
            obligations = list(raw_obligations) if isinstance(
                raw_obligations,
                list,
            ) else []
            state._runtime_ctx.pop("architect_obligations", None)
        else:
            previous = state.architecture_baseline or {}
            contracts = dict(previous.get("contracts", {}))
            contracts.update(state.contracts)
            obligations_by_id = {
                item.get("id"): item
                for item in previous.get("obligations", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            raw_obligations = state._runtime_ctx.pop("architect_obligations", [])
            if isinstance(raw_obligations, list):
                for item in raw_obligations:
                    if isinstance(item, dict) and isinstance(item.get("id"), str):
                        obligations_by_id[item["id"]] = item
            obligations = list(obligations_by_id.values())
        return build_architecture_baseline(
            revision=max(1, state.plan_refine_count + 1),
            design_doc_path=design_path,
            design_doc_digest=digest,
            plan=state.plan,
            batch_plan=batches,
            contracts=contracts,
            obligations=obligations,
            accepted_at_tick=state.tick,
        )


__all__ = ["ArchitectureActivationResult", "ArchitectureActivationService"]
