"""Phase 80 T406：机器化执行处置与宿主连续驱动。"""

from __future__ import annotations

import pytest

from auto_engineering.host.driver_contract import HostDriverDecision, decide_host_step
from auto_engineering.loop.execution_control import (
    ExecutionControl,
    ExecutionControlError,
    ExecutionDisposition,
    control_for_action,
)


def test_continue_control_forbids_yield() -> None:
    control = control_for_action({"action": "developer"})

    assert control == ExecutionControl(
        schema_version="1.0",
        disposition=ExecutionDisposition.CONTINUE,
        continuation_required=True,
        yield_allowed=False,
        allowed_stop_reasons=(),
        reason_code=None,
    )


def test_invalid_continue_combination_is_rejected() -> None:
    with pytest.raises(ExecutionControlError, match="CONTINUE"):
        ExecutionControl.from_dict({
            "schema_version": "1.0",
            "disposition": "CONTINUE",
            "continuation_required": True,
            "yield_allowed": True,
            "allowed_stop_reasons": [],
        })


def test_gap_review_waits_for_real_user_decision() -> None:
    control = control_for_action({"action": "gap_review"})

    assert control.disposition is ExecutionDisposition.WAIT_USER
    assert control.reason_code == "gap_decisions_required"


def test_environment_failure_waits_instead_of_reentering_code_repair() -> None:
    control = control_for_action({
        "action": "developer",
        "gate_summary": {
            "task_evidence": {"status": "environment_failure", "passed": False}
        },
    })

    assert control.disposition is ExecutionDisposition.WAIT_USER
    assert control.reason_code == "environment_failure"


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ({"action": "developer"}, HostDriverDecision.EXECUTE_NEXT),
        ({"action": "gap_review"}, HostDriverDecision.WAIT),
        ({"action": "done"}, HostDriverDecision.FINISH),
        ({"action": "error"}, HostDriverDecision.FAIL),
        ({"action": "session_rollover"}, HostDriverDecision.HANDOFF),
    ],
)
def test_host_driver_uses_only_machine_disposition(
    action: dict[str, str],
    expected: HostDriverDecision,
) -> None:
    control = control_for_action(action)
    payload = {"extensions": {"ae": {"execution_control": control.to_dict()}}}

    assert decide_host_step(payload) is expected
