"""Loop 边界纯函数的路径、验证型 batch 和执行处置回归。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_engineering.loop.change_evidence import (
    declared_real_files,
    verification_only_batch_ready,
)
from auto_engineering.loop.execution_control import (
    ExecutionControl,
    ExecutionControlError,
    ExecutionDisposition,
    control_for_action,
    project_execution_control,
)


def test_declared_real_files_is_root_bound_and_skips_missing_entries(tmp_path: Path) -> None:
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    source.write_text("pass", encoding="utf-8")
    state = SimpleNamespace(
        files_changed=["src/main.py", "missing.py", "../escape.py", "", None]
    )
    assert declared_real_files(state, tmp_path) == {"src/main.py"}


@pytest.mark.parametrize(
    "state",
    [
        SimpleNamespace(test_results={"passed": 0, "failed": 0}),
        SimpleNamespace(test_results={"passed": True, "failed": 0}),
        SimpleNamespace(test_results={"passed": 1, "failed": 1}),
        SimpleNamespace(test_results={"passed": 1}, batch_state=None),
    ],
)
def test_verification_only_batch_requires_passing_evidence_and_runtime_handles(
    tmp_path: Path, state: object
) -> None:
    assert verification_only_batch_ready(state, tmp_path) is False


def test_verification_only_batch_accepts_existing_targets_from_runtime_context(
    tmp_path: Path,
) -> None:
    target = tmp_path / "src" / "existing.py"
    target.parent.mkdir()
    target.write_text("pass", encoding="utf-8")
    task = SimpleNamespace(target_files=["src/existing.py"])
    batch_state = SimpleNamespace(current_batch_tasks=lambda _plan: [task])
    state = SimpleNamespace(
        test_results={"passed": 1, "failed": 0},
        _runtime_ctx={"batch_state": batch_state, "plan": object()},
    )
    assert verification_only_batch_ready(state, tmp_path) is True

    bad = SimpleNamespace(
        test_results={"passed": 1, "failed": 0},
        _runtime_ctx={
            "batch_state": SimpleNamespace(current_batch_tasks=lambda _plan: []),
            "plan": object(),
        },
    )
    assert verification_only_batch_ready(bad, tmp_path) is False


def test_execution_control_validates_contract_and_projects_all_action_dispositions() -> None:
    valid = ExecutionControl(
        schema_version="1.0",
        disposition=ExecutionDisposition.CONTINUE,
        continuation_required=True,
        yield_allowed=False,
        allowed_stop_reasons=(),
    )
    assert ExecutionControl.from_dict(valid.to_dict()) == valid
    with pytest.raises(ExecutionControlError):
        ExecutionControl.from_dict({"disposition": "unknown"})
    with pytest.raises(ExecutionControlError):
        ExecutionControl.from_dict({**valid.to_dict(), "extra": True})
    with pytest.raises(ExecutionControlError):
        ExecutionControl(
            schema_version="1.0",
            disposition=ExecutionDisposition.WAIT_USER,
            continuation_required=False,
            yield_allowed=True,
            allowed_stop_reasons=(),
        )

    actions = [
        ({"action": "done"}, ExecutionDisposition.TERMINAL),
        ({"action": "error", "error_code": "E"}, ExecutionDisposition.ERROR),
        ({"action": "session_rollover"}, ExecutionDisposition.HANDOFF_REQUIRED),
        ({"action": "gap_review"}, ExecutionDisposition.WAIT_USER),
        ({"action": "resource_wait"}, ExecutionDisposition.WAIT_RESOURCE),
        (
            {"action": "developer", "gate_summary": {
                "task_evidence": {"status": "environment_failure"},
            }},
            ExecutionDisposition.WAIT_RESOURCE,
        ),
        ({"action": "gate", "gate": {"type": "manual"}}, ExecutionDisposition.WAIT_USER),
        ({"action": "gate", "gate": {"type": "unknown"}}, ExecutionDisposition.ERROR),
        ({"action": "other"}, ExecutionDisposition.CONTINUE),
    ]
    for action, disposition in actions:
        assert control_for_action(action).disposition is disposition
    projected = project_execution_control({
        "action": "done", "extensions": {"ae": {"old": True}}
    })
    assert projected["extensions"]["ae"]["execution_control"]["disposition"] == "TERMINAL"
