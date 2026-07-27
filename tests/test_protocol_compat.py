"""v1.0 Result 到 Protocol Envelope v1.1 的兼容入口。"""

from __future__ import annotations

import logging

import pytest

from auto_engineering.loop.protocol import (
    ProtocolErrorCode,
    ProtocolValidationError,
)


def _upgrade_legacy_result(result: dict, action: dict | None) -> dict:
    from auto_engineering.loop.protocol_compat import upgrade_legacy_result

    return upgrade_legacy_result(result, action)


def _active_action(**overrides) -> dict:
    action = {
        "schema_version": "1.1",
        "message_type": "action",
        "message_id": "action-1",
        "thread_id": "thread-1",
        "tick": 3,
        "stage": "critic",
        "causation_id": "result-previous",
        "correlation_id": "thread-1",
        "extensions": {},
        "action": "critic",
    }
    action.update(overrides)
    return action


def test_legacy_stage_result_is_upgraded(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="ae.loop.protocol_compat")

    upgraded = _upgrade_legacy_result(
        {"stage": "critic", "verdict": "APPROVE", "findings": []},
        _active_action(),
    )

    assert upgraded["schema_version"] == "1.1"
    assert upgraded["message_type"] == "result"
    assert upgraded["causation_id"] == "action-1"
    assert upgraded["thread_id"] == "thread-1"
    assert upgraded["tick"] == 3
    assert upgraded["extensions"]["compat"]["source_schema_version"] == "1.0"
    assert "legacy_result_upgraded" in caplog.text


def test_legacy_gate_resolution_uses_active_gate_stage() -> None:
    upgraded = _upgrade_legacy_result(
        {
            "gate_resolution": {
                "gate_id": "checkpoint_architect",
                "resolution": "继续",
            }
        },
        _active_action(action="gate", stage="architect"),
    )

    assert upgraded["stage"] == "architect"
    assert upgraded["causation_id"] == "action-1"


def test_legacy_result_without_active_action_fails_closed() -> None:
    with pytest.raises(ProtocolValidationError) as exc_info:
        _upgrade_legacy_result({"stage": "critic"}, None)

    assert exc_info.value.code is ProtocolErrorCode.ACTION_NOT_ACTIVE


def test_legacy_stage_mismatch_does_not_guess_completed_action() -> None:
    with pytest.raises(ProtocolValidationError) as exc_info:
        _upgrade_legacy_result(
            {"stage": "architect", "plan": "old"},
            _active_action(stage="developer", action="developer"),
        )

    assert exc_info.value.code is ProtocolErrorCode.ACTION_NOT_ACTIVE


def test_native_result_is_not_rewritten() -> None:
    native = {
        "schema_version": "1.1",
        "message_type": "result",
        "message_id": "result-1",
        "thread_id": "thread-1",
        "tick": 3,
        "stage": "critic",
        "causation_id": "action-1",
        "correlation_id": "thread-1",
        "extensions": {},
        "verdict": "APPROVE",
        "findings": [],
    }

    assert _upgrade_legacy_result(native, _active_action()) == native
