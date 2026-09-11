"""Architect task 的唯一机器可读契约。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ARCHITECT_TASK_CONTRACT_VERSION = "1.0"
ARCHITECT_TASK_KINDS = ("implementation", "test", "contract_test")
ARCHITECT_TASK_REQUIRED_FIELDS = (
    "id",
    "description",
    "kind",
    "module_ref",
    "file_targets",
    "depends_on",
)


def architect_task_schema() -> dict[str, Any]:
    """返回给 Action/日志/测试使用的稳定 JSON Schema 子集。"""

    return {
        "schema_version": ARCHITECT_TASK_CONTRACT_VERSION,
        "required": list(ARCHITECT_TASK_REQUIRED_FIELDS),
        "properties": {
            "id": {"type": "string", "minLength": 1},
            "description": {"type": "string", "minLength": 1},
            "kind": {"type": "string", "enum": list(ARCHITECT_TASK_KINDS)},
            "module_ref": {"type": "string", "minLength": 1},
            "file_targets": {"type": "array", "items": {"type": "string"}},
            "depends_on": {"type": "array", "items": {"type": "string"}},
        },
    }


def architect_task_template() -> dict[str, Any]:
    """返回 Prompt 中使用的任务模板，避免 Action 再维护第二份字段清单。"""

    return {
        "id": "B<n>-T<n>",
        "description": "string",
        "kind": "implementation|test|contract_test",
        "module_ref": "string",
        "file_targets": ["relative_posix_path"],
        "depends_on": ["task_id"],
    }


def architect_task_format_description() -> str:
    """生成短格式描述，供 Action expected_format 使用。"""

    fields = ", ".join(ARCHITECT_TASK_REQUIRED_FIELDS)
    return (
        f"[{fields}]；kind={ '|'.join(ARCHITECT_TASK_KINDS) }；"
        "file_targets 为 project_root-relative POSIX 路径；"
        "depends_on 为 task_id 数组"
    )


def validate_architect_task(
    task: object,
    *,
    location: str = "task",
) -> str | None:
    """校验一个任务；返回稳定、可直接交给 Worker 修复的错误文本。"""

    if not isinstance(task, Mapping):
        return f"ARCHITECT_TASK_INVALID: {location} 必须为 object"
    for field in ARCHITECT_TASK_REQUIRED_FIELDS:
        if field not in task:
            return f"ARCHITECT_TASK_FIELD_MISSING: {location}.{field}"
    for field in ("id", "description", "module_ref"):
        if not isinstance(task[field], str) or not task[field].strip():
            return f"ARCHITECT_TASK_FIELD_INVALID: {location}.{field}"
    kind = task["kind"]
    if kind not in ARCHITECT_TASK_KINDS:
        return (
            f"ARCHITECT_TASK_KIND_INVALID: {location}.kind="
            f"{kind!r}; allowed={','.join(ARCHITECT_TASK_KINDS)}"
        )
    for field in ("file_targets", "depends_on"):
        value = task[field]
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item for item in value
        ):
            return f"ARCHITECT_TASK_FIELD_INVALID: {location}.{field}"
    for target in task["file_targets"]:
        if target.startswith("/") or "\\" in target or ".." in target.split("/"):
            return f"ARCHITECT_TASK_PATH_INVALID: {location}.file_targets={target!r}"
    return None


def validate_architect_batch_plan(batch_plan: object) -> str | None:
    """校验首次计划或 plan_patch.add_batches 中的全部任务。"""

    if not isinstance(batch_plan, list):
        return "ARCHITECT_BATCH_PLAN_INVALID: batch_plan 必须为 array"
    seen: set[str] = set()
    for batch_index, batch in enumerate(batch_plan):
        if not isinstance(batch, Mapping):
            return f"ARCHITECT_BATCH_INVALID: batch_plan[{batch_index}] 必须为 object"
        tasks = batch.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            return f"ARCHITECT_BATCH_TASKS_INVALID: batch_plan[{batch_index}].tasks"
        for task_index, task in enumerate(tasks):
            location = f"batch_plan[{batch_index}].tasks[{task_index}]"
            error = validate_architect_task(task, location=location)
            if error:
                return error
            task_id = str(task["id"])
            if task_id in seen:
                return f"ARCHITECT_TASK_ID_DUPLICATE: {task_id}"
            seen.add(task_id)
    return None


__all__ = [
    "ARCHITECT_TASK_CONTRACT_VERSION",
    "ARCHITECT_TASK_KINDS",
    "ARCHITECT_TASK_REQUIRED_FIELDS",
    "architect_task_format_description",
    "architect_task_schema",
    "architect_task_template",
    "validate_architect_batch_plan",
    "validate_architect_task",
]
