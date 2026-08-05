"""Architect 计划的无副作用结构验证。"""

from __future__ import annotations

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.design_doc import DesignDoc
from auto_engineering.engine.progress_tree import ProgressTree
from auto_engineering.engine.verification_layers import determine_verification_layers
from auto_engineering.loop.task_factory import tasks_from_batch_plan


def dry_run_architect_plan(
    design_doc: DesignDoc | None,
    result: dict,
    requirement: str,
) -> str | None:
    """验证 Architect 计划能否初始化执行树，不修改现有状态。"""
    if design_doc is None:
        return None
    patch = result.get("plan_patch")
    batches = patch.get("add_batches", []) if isinstance(patch, dict) else result.get("batch_plan", [])
    if not isinstance(batches, list) or not batches:
        return "batch_plan 不能为空"
    try:
        normalized = BatchState.flatten_batch_plan(batches)
        BatchState.from_design_doc(design_doc, normalized)
        tree = ProgressTree.from_design_doc(design_doc)
        tree.apply_batch_plan_totals(normalized)
        tasks_from_batch_plan(normalized, requirement)
        determine_verification_layers(design_doc, normalized)
    except (TypeError, KeyError, ValueError) as exc:
        return str(exc)
    return None
