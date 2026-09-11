"""Architect 输出到执行结构的显式激活服务。"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.design_doc import DesignDoc
from auto_engineering.engine.models import Plan
from auto_engineering.engine.progress_tree import ProgressTree
from auto_engineering.engine.state import EngineState
from auto_engineering.engine.verification_layers import (
    VerificationLayers,
    determine_verification_layers,
)
from auto_engineering.loop.architecture_baseline import build_architecture_baseline
from auto_engineering.loop.events import LoopEventType
from auto_engineering.loop.task_factory import tasks_from_batch_plan

EmitEvent = Callable[[LoopEventType, dict], None]


@dataclass(frozen=True, slots=True)
class ArchitectureActivationResult:
    baseline: dict
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
        is_reconcile = bool(candidate and candidate.get("reconciled") is True)
        batches = BatchState.flatten_batch_plan([
            dict(item) for item in state.batch_plan
        ])
        if batch_state is not None and state.plan_refine_count > 0 and not is_reconcile:
            completed = batch_state.completed_batch_ids()
            raw_base_revision = state._runtime_ctx.get(
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
            batches = batch_state.batch_plan

        if is_reconcile:
            verification_layers = determine_verification_layers(design_doc, batches)
            progress_tree = (
                ProgressTree.from_design_doc(design_doc)
                if design_doc is not None
                else ProgressTree.from_batch_plan(batches, state.requirement)
            )
            if design_doc is not None:
                progress_tree.apply_batch_plan_totals(batches)

        baseline = self._build_baseline(
            state,
            batches,
            design_doc=design_doc,
        )
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
                # 结构同步只处理设计层次；PlanPatch 的完整合并计划才是任务总量
                # 权威。必须在同一激活中重算 totals，并保留既有 done facts。
                progress_tree.apply_batch_plan_totals(batches)
            else:
                progress_tree.sync_from_batch_plan(batches)
        return ArchitectureActivationResult(
            baseline=baseline,
            batch_state=batch_state,
            plan=plan,
            verification_layers=verification_layers,
            progress_tree=progress_tree,
        )

    def _build_baseline(
        self,
        state: EngineState,
        batches: list[dict],
        *,
        design_doc: DesignDoc | None,
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
        raw_candidate = state._runtime_ctx.get("architecture_candidate")
        raw_coverage = state._runtime_ctx.get("architect_plan_coverage")
        architect_plan_coverage = (
            dict(raw_coverage) if isinstance(raw_coverage, Mapping) else None
        )
        if isinstance(raw_candidate, dict):
            candidate_batches = self._canonical_batches(
                raw_candidate.get("batch_plan", []),
                design_doc=design_doc,
            )
            if candidate_batches != batches:
                raise ValueError("ARCHITECTURE_CANDIDATE_DRIFT")
            contracts = dict(raw_candidate.get("contracts", {}))
            raw_obligations = raw_candidate.get("obligations", [])
            obligations = list(raw_obligations) if isinstance(
                raw_obligations,
                list,
            ) else []
        else:
            previous = state.architecture_baseline or {}
            contracts = dict(previous.get("contracts", {}))
            contracts.update(state.contracts)
            obligations_by_id = {
                item.get("id"): item
                for item in previous.get("obligations", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            raw_obligations = state._runtime_ctx.get("architect_obligations", [])
            if isinstance(raw_obligations, list):
                for item in raw_obligations:
                    if isinstance(item, dict) and isinstance(item.get("id"), str):
                        obligations_by_id[item["id"]] = item
            obligations = list(obligations_by_id.values())
        reconciled_revision = (
            state.plan_reconciliation.get("current_revision")
            if isinstance(state.plan_reconciliation, dict)
            else None
        )
        return build_architecture_baseline(
            revision=(
                reconciled_revision
                if isinstance(reconciled_revision, int)
                else max(1, state.plan_refine_count + 1)
            ),
            design_doc_path=design_path,
            design_doc_digest=digest,
            plan=state.plan,
            batch_plan=batches,
            contracts=contracts,
            obligations=obligations,
            accepted_at_tick=state.tick,
            architect_plan_coverage=architect_plan_coverage,
        )

    @staticmethod
    def _canonical_batches(
        batch_plan: object,
        *,
        design_doc: DesignDoc | None,
    ) -> list[dict]:
        """用执行游标的同一规则物化 Candidate，避免 raw/flat 形态误报漂移。"""

        if not isinstance(batch_plan, list):
            raise ValueError("ARCHITECTURE_CANDIDATE_BATCH_PLAN_INVALID")
        copied = deepcopy(batch_plan)
        if not all(isinstance(item, dict) for item in copied):
            raise ValueError("ARCHITECTURE_CANDIDATE_BATCH_PLAN_INVALID")
        if design_doc is not None:
            return BatchState.from_design_doc(design_doc, copied).batch_plan
        return BatchState.from_batch_plan(copied).batch_plan


__all__ = ["ArchitectureActivationResult", "ArchitectureActivationService"]
