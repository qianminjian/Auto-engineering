"""Architect 计划的无副作用结构验证。"""

from __future__ import annotations

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.design_doc import DesignDoc
from auto_engineering.engine.progress_tree import ProgressTree
from auto_engineering.engine.verification_layers import determine_verification_layers
from auto_engineering.loop.architect_task_contract import validate_architect_batch_plan
from auto_engineering.loop.architecture_candidate import (
    ArchitectureCandidateBuilder,
    ArchitectureCandidateError,
)
from auto_engineering.loop.engineering_model import EngineeringModel
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
    implementation_batches: dict[str, list[int]] = {}
    test_tasks: list[tuple[str, str, int]] = []
    if isinstance(raw_batches, list):
        for batch_index, batch in enumerate(raw_batches):
            if not isinstance(batch, dict):
                continue
            for task in batch.get("tasks", []):
                if isinstance(task, dict) and isinstance(task.get("id"), str):
                    tasks[task["id"]] = task
                    module_ref = task.get("module_ref")
                    kind = task.get("kind", task.get("type"))
                    if not isinstance(module_ref, str) or not module_ref:
                        continue
                    if kind == "implementation":
                        implementation_batches.setdefault(module_ref, []).append(
                            batch_index
                        )
                    elif kind in {"test", "contract_test"}:
                        test_tasks.append((task["id"], module_ref, batch_index))

    # Developer 每次只消费一个 batch；如果测试先进入当前 batch，而对应
    # 实现却被安排到未来 batch，该测试在当前 Action 必然失败。这是
    # Architect 计划拓扑错误，必须在激活前拒绝，不能让 Worker 越界补文件。
    for task_id, module_ref, test_batch_index in test_tasks:
        implementation_indices = implementation_batches.get(module_ref, [])
        if implementation_indices and not any(
            index <= test_batch_index for index in implementation_indices
        ):
            return (
                "ARCHITECT_TEST_IMPLEMENTATION_ORDER_INVALID: 测试任务 "
                f"{task_id} ({module_ref}) 对应实现位于未来 batch；"
                "实现任务必须位于同一或更早 batch"
            )

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
    refine_request: dict | None = None,
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

    # 有显式设计文档时，计划进入激活前必须满足当前 Architect 机器契约。
    # 无设计文档仍保留旧输入兼容性，避免把历史模糊需求的迁移成本伪装成
    # 本次设计驱动协议的一部分；后续可在无设计文档协议定型后单独收紧。
    if design_doc is not None:
        if result.get("result_type") == "plan_reconciliation":
            task_plan = result.get("new_batch_plan")
        elif active_revision <= 0:
            task_plan = result.get("batch_plan")
        else:
            patch = result.get("plan_patch")
            task_plan = patch.get("add_batches") if isinstance(patch, dict) else None
        task_error = validate_architect_batch_plan(task_plan)
        if task_error:
            return task_error

    obligation_error = validate_architect_obligations(
        candidate, research_archive or {}
    )
    if obligation_error:
        return obligation_error
    if isinstance(refine_request, dict) and refine_request.get("source") == "critic":
        required_refs: set[str] = set()
        for gap in refine_request.get("gaps", []):
            if not isinstance(gap, dict):
                continue
            source_ref = gap.get("source_ref")
            if isinstance(source_ref, str) and source_ref:
                required_refs.add(source_ref)
        mapped_refs: set[str] = set()
        for obligation in candidate.get("obligations", []):
            if not isinstance(obligation, dict):
                continue
            source_ref = obligation.get("source_ref")
            if isinstance(source_ref, str) and source_ref:
                mapped_refs.add(source_ref)
        missing_refs = sorted(required_refs - mapped_refs)
        if missing_refs:
            return "Critic finding 缺少修复义务映射: " + ", ".join(missing_refs)
    batches = candidate.get("batch_plan", [])
    if not isinstance(batches, list) or not batches:
        return "batch_plan 不能为空"
    try:
        normalized = BatchState.flatten_batch_plan(batches)
        if design_doc is None and any(
            "plate_keys" in batch for batch in normalized
        ):
            # 模糊需求没有 DesignDoc 可做组件存在性校验，但显式使用新
            # routing 合同时仍必须经过同一归一化。否则空 plate_keys 会
            # 绕过 prevalidator，直到 ARCHITECTURE_PLAN_ACTIVATED 的副作用
            # 阶段才抛出裸 ValueError。未携带 routing 字段的历史结果继续
            # 保留只读兼容校验，不在这里伪造新的机器路由。
            normalized = BatchState.from_batch_plan(normalized).batch_plan
        elif design_doc is not None:
            normalized = BatchState.from_design_doc(design_doc, normalized).batch_plan
        if design_doc is None:
            tasks_from_batch_plan(normalized, requirement)
            return None
        model = EngineeringModel.from_design_doc(
            design_doc, design_digest="sha256:" + "0" * 64
        )
        for batch in normalized:
            references = batch.get("design_sections", [])
            if isinstance(references, list):
                model.select_sections(
                    str(reference) for reference in references
                )
        design_components = {
            component.name: component
            for plate in design_doc.plates
            for component in plate.components
        }
        for batch in normalized:
            raw_keys = batch.get("plate_keys")
            target_names = (
                [key for key in raw_keys if isinstance(key, str)]
                if isinstance(raw_keys, list) and raw_keys
                else [str(batch.get("component", ""))]
            )
            target_components = [
                design_components[name] for name in target_names if name in design_components
            ]
            if not any(component.design_items for component in target_components):
                continue
            refs = batch.get("design_item_refs")
            if not isinstance(refs, list) or not refs:
                return (
                    "BATCH_DESIGN_ITEM_SCOPE_REQUIRED: batch "
                    f"{batch.get('batch_id', '?')} 必须声明非空 design_item_refs"
                )
            allowed = {
                item.item_id
                for component in target_components
                for item in component.design_items
            }
            invalid = sorted({ref for ref in refs if ref not in allowed})
            if invalid:
                allowed_refs = sorted(
                    item.item_id
                    for component in target_components
                    for item in component.design_items
                )
                return (
                    "BATCH_DESIGN_ITEM_SCOPE_INVALID: batch "
                    f"{batch.get('batch_id', '?')} 含不属于组件的 design_item_refs "
                    + ", ".join(invalid)
                    + "；有效 design_item_refs: "
                    + (", ".join(allowed_refs) if allowed_refs else "（无）")
                )
        tree = ProgressTree.from_design_doc(design_doc)
        tree.apply_batch_plan_totals(normalized)
        tasks_from_batch_plan(normalized, requirement)
        determine_verification_layers(design_doc, normalized)
    except (TypeError, KeyError, ValueError) as exc:
        return str(exc)
    return None
