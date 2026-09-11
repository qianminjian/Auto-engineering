"""Architect 结果拒绝后的确定性修复提示。"""

from __future__ import annotations

from collections.abc import Sequence


def architect_repair_guidance(
    rejection_message: str,
    rejection_violations: object,
) -> str:
    """把 Architect 校验错误转换为不重跑 Worker 的机器修复指导。"""

    guidance: list[str] = []
    if "BATCH_DESIGN_ITEM_SCOPE" in rejection_message:
        guidance.append(
            "这是机器设计项范围校验，不需要用户输入或重新启动 Worker。"
            "直接从 result_rejection.message 中‘有效 design_item_refs’后的列表"
            "逐字复制到对应 batch 的 design_item_refs；不得使用章节号、标题或 slug。"
        )
    if "OBLIGATION_UPDATE_REQUIRED" in rejection_message:
        guidance.append(
            "这是已有 Research/设计义务的增量更新校验。不得在 obligations 中"
            "重写已有 source_ref；保留历史 obligation，只在当前"
            "plan_patch.obligation_updates 中使用，并以 source_ref 精确匹配后追加实现、验证或 contract"
            "目标。没有新增目标时不要改写该义务。"
        )
    if "ARCHITECT_TEST_IMPLEMENTATION_ORDER_INVALID" in rejection_message:
        guidance.append(
            "这是 Architect 的 TDD 批次拓扑错误，不是 Worker 失败。"
            "若测试会导入对应实现，必须把测试 task 与实现 task 放入同一 batch，"
            "保持实现 task 的 depends_on 指向测试 task；只有独立且不导入未来实现的"
            "契约测试才可放在更早 batch。不得重新 spawn、重做或读取已完成 Worker。"
        )
    coverage_violations = [
        str(item)
        for item in rejection_violations
        if isinstance(item, str) and item.startswith("ARCHITECT_RESULT_")
    ] if isinstance(rejection_violations, Sequence) and not isinstance(
        rejection_violations, (str, bytes)
    ) else []
    if coverage_violations or "ARCHITECT_RESULT_COVERAGE" in rejection_message:
        details = "；".join(coverage_violations)
        guidance.append(
            "这是 Architect 计划身份覆盖校验，不是 Worker 失败。"
            "Worker outcome 中的 batch_id 和 task.id 是唯一权威身份，必须逐字复制；"
            "不得把它们改成新编号、重新分批、删除批次、不得重新 spawn 或再次读取/执行"
            "Worker。只修复当前 coordinator-result 的语义字段，然后沿用当前 Action 的"
            "finalize、validate、submit。Core 已给出的身份差异如下："
            f"{details or rejection_message}。"
            "若存在 MISSING_BATCHES/MISSING_TASKS，必须补回这些原始身份；"
            "若存在 EXTRA_BATCHES/EXTRA_TASKS，必须删除新增身份。"
        )
    return "".join(guidance)


__all__ = ["architect_repair_guidance"]
