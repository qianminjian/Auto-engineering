"""Phase 53 T247：LoopEvent 不可变事实契约。"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from auto_engineering.loop.events import (
    EVENT_SCHEMA_VERSION,
    LoopEvent,
    LoopEventType,
    LoopEventValidationError,
)


def _event(**overrides: object) -> LoopEvent:
    values: dict[str, object] = {
        "thread_id": "thread-1",
        "sequence": 1,
        "event_type": LoopEventType.LOOP_INITIALIZED,
        "payload": {"requirement": "实现事件存储"},
        "correlation_id": "thread-1",
    }
    values.update(overrides)
    return LoopEvent.create(**values)  # type: ignore[arg-type]


def test_event_has_stable_identity_causation_and_payload_hash() -> None:
    event = _event(causation_id="result-1")

    assert event.event_id
    assert event.sequence == 1
    assert event.causation_id == "result-1"
    assert event.correlation_id == "thread-1"
    assert event.schema_version == EVENT_SCHEMA_VERSION
    assert len(event.payload_sha256) == 64
    assert event.verify_payload_hash()


def test_equivalent_payload_has_same_hash_independent_of_key_order() -> None:
    first = _event(payload={"b": 2, "a": 1})
    second = _event(payload={"a": 1, "b": 2}, sequence=2)

    assert first.payload_sha256 == second.payload_sha256


def test_event_and_nested_payload_are_immutable() -> None:
    source = {"nested": {"items": [1, 2]}}
    event = _event(payload=source)
    source["nested"]["items"].append(3)  # type: ignore[index,union-attr]

    assert event.to_dict()["payload"] == {"nested": {"items": [1, 2]}}
    with pytest.raises(FrozenInstanceError):
        event.sequence = 2  # type: ignore[misc]
    with pytest.raises(TypeError):
        event.payload["new"] = True  # type: ignore[index]


@pytest.mark.parametrize("sequence", [-1, True])
def test_invalid_sequence_fails_closed(sequence: object) -> None:
    with pytest.raises(LoopEventValidationError, match="sequence"):
        _event(sequence=sequence)


def test_tampered_serialized_payload_is_rejected() -> None:
    raw = _event().to_dict()
    raw["payload"] = {"requirement": "已篡改"}

    with pytest.raises(LoopEventValidationError, match="payload_sha256"):
        LoopEvent.from_dict(raw)


def test_all_planned_event_types_are_explicit() -> None:
    assert {member.value for member in LoopEventType} == {
        "LoopInitialized",
        "ActionIssued",
        "ResultAccepted",
        "GateResolved",
        "GuardrailEvaluated",
        "GatesCompleted",
        "StageAdvanced",
        "CheckpointImported",
        "LoopCompleted",
        "LoopFailed",
        "ExecutionSessionStarted",
        "SessionBudgetObserved",
        "SessionRolloverRequested",
        "ResumeCapsuleCreated",
        "ExecutionSessionClaimed",
        "ExecutionSessionClosed",
        "ExecutionSessionAbandoned",
        "UsageRecorded",
        "ArtifactRegistered",
        "PlanPatched",
        "StateInvariantRejected",
        "VerificationEvidenceBound",
        "ProjectProfileResolved",
        "ProjectProfileChanged",
        "ProjectProfileConflict",
        "ProjectSetupRequired",
        "ProjectSetupCompleted",
    }


def test_loop_event_schema_is_strict_and_accepts_real_event() -> None:
    schema_path = (
        Path(__file__).parents[1]
        / "auto_engineering"
        / "loop"
        / "loop-event.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    raw = _event().to_dict()

    assert not list(validator.iter_errors(raw))
    raw["unknown"] = True
    assert list(validator.iter_errors(raw))
