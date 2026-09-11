"""Architect Worker 计划与 Coordinator Result 的完整覆盖校验。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from auto_engineering.engine.batch_state import BatchState


def _bounded_error(value: object) -> str:
    text = " ".join(str(value).split())
    return text[:240]


def _architect_plan_manifest_result(
    value: object,
) -> tuple[dict[str, Any] | None, str | None]:
    """返回 manifest 及机器可读的结构化失败原因。"""
    if not isinstance(value, list) or not all(
        isinstance(item, Mapping) for item in value
    ):
        return None, "batch_plan 必须是 object 数组"
    try:
        flattened = BatchState.flatten_batch_plan(deepcopy([dict(item) for item in value]))
    except (KeyError, TypeError, ValueError) as exc:
        return None, _bounded_error(exc)
    encoded = json.dumps(
        flattened,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    batch_ids = tuple(
        str(item["batch_id"])
        for item in flattened
        if isinstance(item, Mapping) and isinstance(item.get("batch_id"), str)
    )
    task_ids = tuple(
        str(task["id"])
        for item in flattened
        if isinstance(item, Mapping)
        for task in item.get("tasks", [])
        if isinstance(task, Mapping) and isinstance(task.get("id"), str)
    )
    return {
        "schema_version": "1.0",
        "digest": hashlib.sha256(encoded).hexdigest(),
        "batch_ids": list(batch_ids),
        "task_ids": list(task_ids),
    }, None


def architect_plan_manifest(value: object) -> dict[str, Any] | None:
    """把嵌套/扁平 batch plan 转为可比较的稳定摘要。"""

    manifest, _ = _architect_plan_manifest_result(value)
    return manifest


def architect_plan_coverage_violations(
    *,
    worker_payloads: list[Mapping[str, Any]],
    coordinator_payload: Mapping[str, Any],
) -> tuple[str, ...]:
    """拒绝 Coordinator 对已提交 Architect 计划的删减或改写。

    当前 Architect Action 是单 Worker 合同。若未来允许多个 Architect Worker，
    必须先定义显式合并投影，不能在这里默默拼接多个结果。
    """

    if not worker_payloads:
        return ()
    if len(worker_payloads) != 1:
        return ("ARCHITECT_RESULT_COVERAGE_SOURCE_UNSUPPORTED",)
    source = worker_payloads[0].get("batch_plan")
    if "batch_plan" not in worker_payloads[0] and "batch_plan" not in coordinator_payload:
        # Architect 的设计变更/授权 Gate 可以只提交 change requests；此类
        # 结果尚未产生执行计划，不应被错误套用计划覆盖合同。
        return ()
    candidate = coordinator_payload.get("batch_plan")
    source_manifest, source_error = _architect_plan_manifest_result(source)
    if source_manifest is not None and "batch_plan" not in coordinator_payload:
        source_batches = tuple(str(item) for item in source_manifest["batch_ids"])
        source_tasks = tuple(str(item) for item in source_manifest["task_ids"])
        return (
            "ARCHITECT_RESULT_COVERAGE_LOSS",
            "ARCHITECT_RESULT_SOURCE_DIGEST:" + str(source_manifest["digest"]),
            "ARCHITECT_RESULT_CANDIDATE_DIGEST:missing",
            "ARCHITECT_RESULT_SOURCE_BATCHES:" + ",".join(source_batches),
            "ARCHITECT_RESULT_CANDIDATE_BATCHES:",
            "ARCHITECT_RESULT_SOURCE_TASKS:" + ",".join(source_tasks),
            "ARCHITECT_RESULT_CANDIDATE_TASKS:",
            "ARCHITECT_RESULT_MISSING_BATCHES:" + ",".join(source_batches),
            "ARCHITECT_RESULT_EXTRA_BATCHES:",
            "ARCHITECT_RESULT_MISSING_TASKS:" + ",".join(source_tasks),
            "ARCHITECT_RESULT_EXTRA_TASKS:",
        )
    candidate_manifest, candidate_error = _architect_plan_manifest_result(candidate)
    if source_manifest is None or candidate_manifest is None:
        violations = ["ARCHITECT_RESULT_COVERAGE_INVALID"]
        if source_error:
            violations.append("ARCHITECT_RESULT_COVERAGE_SOURCE_REASON:" + source_error)
        if candidate_error:
            violations.append(
                "ARCHITECT_RESULT_COVERAGE_CANDIDATE_REASON:" + candidate_error
            )
        return tuple(violations)
    source_digest = str(source_manifest["digest"])
    candidate_digest = str(candidate_manifest["digest"])
    source_batches = tuple(str(item) for item in source_manifest["batch_ids"])
    candidate_batches = tuple(str(item) for item in candidate_manifest["batch_ids"])
    source_tasks = tuple(str(item) for item in source_manifest["task_ids"])
    candidate_tasks = tuple(str(item) for item in candidate_manifest["task_ids"])
    # 覆盖身份必须严格相等；其它字段允许经过确定性语义校验后做规范化修复。
    # 例如 Worker 的 plate_keys 表示错误可以修正，但不能借此删除 B2 或 B2-T1。
    if source_batches == candidate_batches and source_tasks == candidate_tasks:
        return ()
    return (
        "ARCHITECT_RESULT_COVERAGE_LOSS",
        "ARCHITECT_RESULT_SOURCE_DIGEST:" + source_digest,
        "ARCHITECT_RESULT_CANDIDATE_DIGEST:" + candidate_digest,
        "ARCHITECT_RESULT_SOURCE_BATCHES:" + ",".join(source_batches),
        "ARCHITECT_RESULT_CANDIDATE_BATCHES:" + ",".join(candidate_batches),
        "ARCHITECT_RESULT_SOURCE_TASKS:" + ",".join(source_tasks),
        "ARCHITECT_RESULT_CANDIDATE_TASKS:" + ",".join(candidate_tasks),
        "ARCHITECT_RESULT_MISSING_BATCHES:"
        + ",".join(item for item in source_batches if item not in candidate_batches),
        "ARCHITECT_RESULT_EXTRA_BATCHES:"
        + ",".join(item for item in candidate_batches if item not in source_batches),
        "ARCHITECT_RESULT_MISSING_TASKS:"
        + ",".join(item for item in source_tasks if item not in candidate_tasks),
        "ARCHITECT_RESULT_EXTRA_TASKS:"
        + ",".join(item for item in candidate_tasks if item not in source_tasks),
    )


__all__ = ["architect_plan_coverage_violations", "architect_plan_manifest"]
