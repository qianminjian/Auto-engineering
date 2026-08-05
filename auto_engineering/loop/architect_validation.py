"""Architect 计划的无副作用结构验证。"""

from __future__ import annotations

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.design_doc import DesignDoc
from auto_engineering.engine.progress_tree import ProgressTree
from auto_engineering.engine.verification_layers import determine_verification_layers
from auto_engineering.loop.task_factory import tasks_from_batch_plan


def _validate_refine_finding_coverage(result: dict, batches: list[dict]) -> str | None:
    """确保 verifier findings 不会只出现在反馈里而未进入新任务。"""
    feedback = result.get("feedback")
    refine = feedback.get("refine_request") if isinstance(feedback, dict) else None
    findings = refine.get("gaps", []) if isinstance(refine, dict) else []
    if not findings:
        return None
    refs: set[str] = set()
    for batch in batches:
        for task in batch.get("tasks", []) if isinstance(batch, dict) else []:
            raw = task.get("finding_ref", []) if isinstance(task, dict) else []
            if isinstance(raw, str):
                refs.add(raw)
            elif isinstance(raw, list):
                refs.update(str(item) for item in raw)
    missing = [
        str(item.get("design_ref", item.get("id", "")))
        for item in findings
        if str(item.get("design_ref", item.get("id", ""))) not in refs
    ]
    return (
        "ARCHITECT_FINDING_UNCOVERED: " + ", ".join(missing)
        if missing else None
    )


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
        if error := _validate_refine_finding_coverage(result, normalized):
            return error
    except (TypeError, KeyError, ValueError) as exc:
        return str(exc)
    return None
