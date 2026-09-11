"""Architect task 机器契约回归。"""

from auto_engineering.loop.architect_task_contract import (
    architect_task_schema,
    architect_task_template,
    validate_architect_batch_plan,
    validate_architect_task,
)


def _task(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "B1-T1",
        "description": "实现能力并补充验证",
        "kind": "implementation",
        "module_ref": "§B1",
        "file_targets": ["src/feature.py"],
        "depends_on": [],
    }
    value.update(overrides)
    return value


def test_schema_and_template_have_one_required_field_set() -> None:
    schema = architect_task_schema()
    template = architect_task_template()

    assert schema["schema_version"] == "1.0"
    assert schema["required"] == list(template)


def test_complete_task_is_accepted() -> None:
    assert validate_architect_task(_task()) is None
    assert validate_architect_batch_plan([{"tasks": [_task()]}]) is None


def test_missing_task_field_is_rejected_before_activation() -> None:
    task = _task()
    del task["module_ref"]

    assert validate_architect_task(task) == "ARCHITECT_TASK_FIELD_MISSING: task.module_ref"


def test_duplicate_task_id_is_rejected() -> None:
    assert validate_architect_batch_plan([
        {"tasks": [_task()]},
        {"tasks": [_task(description="另一个任务")]},
    ]) == "ARCHITECT_TASK_ID_DUPLICATE: B1-T1"
