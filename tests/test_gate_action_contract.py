from __future__ import annotations

from pathlib import Path

import pytest

from auto_engineering.cli.dev_loop import _project_result_repair_action
from auto_engineering.host.execution_assembler import (
    HostEvidenceValidationError,
    HostExecutionAssembler,
)


def test_gate_repair_action_exposes_exact_gate_resolution_contract() -> None:
    action = {
        "action": "gate",
        "stage": "project_setup",
        "message_id": "gate-1",
        "gate": {
            "id": "state_reconciliation",
            "options": [
                {"id": "reinitialize", "label": "重新初始化"},
                {"id": "reconcile", "label": "修复状态并继续"},
            ],
        },
        "instruction": "处理当前 Gate",
    }

    projected = _project_result_repair_action(
        action,
        {
            "error_code": "GATE_RESOLUTION_REQUIRED",
            "message": "当前 active Action 是 Gate，必须提交 gate_resolution",
        },
    )

    assert projected["expected_format"] == {
        "gate_resolution": {
            "gate_id": "state_reconciliation",
            "resolution": "reinitialize | reconcile",
        },
    }
    assert projected["result_contract"] == {
        "schema_version": "1.0",
        "required": ["gate_resolution"],
        "properties": {"gate_resolution": {"type": "object"}},
        "additionalProperties": False,
    }
    assert "不得提交顶层 decision" in projected["instruction"]


def test_gate_finalizer_rejects_top_level_decision_and_accepts_nested_resolution(
    tmp_path: Path,
) -> None:
    action = {
        "action": "gate",
        "stage": "project_setup",
        "message_id": "gate-1",
        "thread_id": "thread-1",
        "tick": 2,
        "correlation_id": "thread-1",
        "result_contract": {
            "schema_version": "1.0",
            "required": ["gate_resolution"],
            "properties": {"gate_resolution": {"type": "object"}},
            "additionalProperties": False,
        },
    }
    assembler = HostExecutionAssembler(tmp_path)

    with pytest.raises(HostEvidenceValidationError, match="COORDINATOR_FIELD"):
        assembler.finalize(
            action=action,
            outcomes=[],
            coordinator_payload={"decision": "reconcile"},
        )

    result = assembler.finalize(
        action=action,
        outcomes=[],
        coordinator_payload={
            "gate_resolution": {
                "gate_id": "state_reconciliation",
                "resolution": "reconcile",
            },
        },
    )
    assert result["gate_resolution"]["resolution"] == "reconcile"
