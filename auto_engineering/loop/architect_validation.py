"""Architect 计划的无副作用结构验证。"""

from __future__ import annotations

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.design_doc import DesignDoc
from auto_engineering.engine.progress_tree import ProgressTree
from auto_engineering.engine.verification_layers import determine_verification_layers
from auto_engineering.loop.architecture_candidate import (
    ArchitectureCandidateBuilder,
    ArchitectureCandidateError,
)
from auto_engineering.loop.task_factory import tasks_from_batch_plan


def validate_architect_obligations(
    result: dict,
    research_archive: dict[str, dict],
) -> str | None:
    """验证 Research/Contract 与实现、验证任务之间的显式覆盖关系。"""
    contracts = result.get("contracts", {})
    if not isinstance(contracts, dict):
        return "contracts 必须为 object"
    for name, contract in contracts.items():
        if not isinstance(contract, dict):
            return f"contract '{name}' 必须为 object"

    raw_batches = result.get("batch_plan", [])
    patch = result.get("plan_patch")
    if isinstance(patch, dict):
        raw_batches = patch.get("add_batches", [])
    tasks: dict[str, dict] = {}
    if isinstance(raw_batches, list):
        for batch in raw_batches:
            if not isinstance(batch, dict):
                continue
            for task in batch.get("tasks", []):
                if isinstance(task, dict) and isinstance(task.get("id"), str):
                    tasks[task["id"]] = task

    obligations = result.get("obligations", [])
    if not isinstance(obligations, list):
        return "obligations 必须为 array"
    by_source: dict[str, dict] = {}
    for obligation in obligations:
        if not isinstance(obligation, dict):
            return "obligation 必须为 object"
        source_ref = obligation.get("source_ref")
        if not isinstance(source_ref, str) or not source_ref:
            return "obligation.source_ref 必须为非空字符串"
        if source_ref in by_source:
            return f"source_ref 重复: {source_ref}"
        by_source[source_ref] = obligation
        implementation = obligation.get("implementation_targets", [])
        verification = obligation.get("verification_targets", [])
        if not implementation or not verification:
            return f"obligation {source_ref} 必须同时覆盖实现和验证任务"
        for task_id in [*implementation, *verification]:
            if task_id not in tasks:
                return f"obligation {source_ref} 引用未知 task: {task_id}"
        for task_id in verification:
            task_kind = tasks[task_id].get("kind", tasks[task_id].get("type"))
            if task_kind not in {"test", "contract_test"}:
                return f"verification target {task_id} 必须是 test/contract_test"
        for contract_ref in obligation.get("contract_refs", []):
            if contract_ref not in contracts:
                return f"obligation {source_ref} 引用未知 contract: {contract_ref}"
    missing = sorted(set(research_archive) - set(by_source))
    if missing:
        return f"Research 缺少 obligation 覆盖: {', '.join(missing)}"
    return None


def dry_run_architect_plan(
    design_doc: DesignDoc | None,
    result: dict,
    requirement: str,
    research_archive: dict[str, dict] | None = None,
    *,
    active_revision: int = 0,
    current_baseline: dict | None = None,
) -> str | None:
    """验证 Architect 计划能否初始化执行树，不修改现有状态。"""
    try:
        candidate = ArchitectureCandidateBuilder().build(
            result,
            active_revision=active_revision,
            current_baseline=current_baseline,
        )
    except ArchitectureCandidateError as exc:
        return str(exc)

    obligation_error = validate_architect_obligations(
        candidate, research_archive or {}
    )
    if obligation_error:
        return obligation_error
    if design_doc is None:
        return None
    batches = candidate.get("batch_plan", [])
    if not isinstance(batches, list) or not batches:
        return "batch_plan 不能为空"
    try:
        normalized = BatchState.flatten_batch_plan(batches)
        normalized = BatchState.from_design_doc(design_doc, normalized).batch_plan
        tree = ProgressTree.from_design_doc(design_doc)
        tree.apply_batch_plan_totals(normalized)
        tasks_from_batch_plan(normalized, requirement)
        determine_verification_layers(design_doc, normalized)
    except (TypeError, KeyError, ValueError) as exc:
        return str(exc)
    return None
