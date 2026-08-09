from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_engineering.cli.dev_loop import _process_state_reconciliation_result
from auto_engineering.engine.state import EngineState
from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.protocol import action_envelope, validate_action_envelope
from auto_engineering.loop.state_reconciliation import (
    StateReconciliationError,
    StateReconciliationService,
)


def _seed(root: Path) -> tuple[SQLiteEventStore, EngineState, dict]:
    events = SQLiteEventStore(root / "events.db")
    state = EngineState(
        requirement="按当前设计开发",
        thread_id="thread-old",
        current_stage="developer",
        tick=4,
        state_reconciliation={
            "status": "waiting_user",
            "gate_message_id": "gate-message",
            "intent": {
                "mode": "design_doc",
                "design_doc_path": "design/current.md",
                "design_doc_digest": "sha256:abc",
                "scope": None,
            },
        },
    )
    gate = action_envelope(
        {
            "action": "gate",
            "gate": {
                "id": "state_reconciliation",
                "type": "decision",
                "options": [
                    {"id": "reinitialize", "label": "重新初始化"},
                    {"id": "reconcile", "label": "修复状态并继续"},
                ],
            },
        },
        thread_id=state.thread_id,
        tick=5,
        stage=state.current_stage,
        message_id="gate-message",
    )
    events.import_checkpoint(
        checkpoint_id="checkpoint-old",
        state=state,
        action=gate,
    )
    return events, state, gate


def _result(gate: dict, resolution: str = "reinitialize") -> dict:
    return {
        "schema_version": "1.1",
        "message_type": "result",
        "message_id": "result-choice",
        "thread_id": gate["thread_id"],
        "tick": gate["tick"],
        "stage": gate["stage"],
        "causation_id": gate["message_id"],
        "correlation_id": gate["correlation_id"],
        "extensions": {},
        "gate_resolution": {
            "gate_id": "state_reconciliation",
            "resolution": resolution,
        },
    }


def test_reinitialize_selection_supersedes_old_thread_and_keeps_audit(tmp_path: Path) -> None:
    events, _, gate = _seed(tmp_path)

    outcome = StateReconciliationService(events).select(_result(gate))

    projection = events.load_projection("thread-old")
    assert projection is not None
    assert projection.thread_status == "superseded"
    assert projection.state_reconciliation is not None
    assert projection.state_reconciliation["choice"] == "reinitialize"
    assert outcome.choice == "reinitialize"
    assert outcome.intent["design_doc_path"] == "design/current.md"
    assert outcome.response["action"] == "done"
    assert outcome.response["verdict"] == "SUPERSEDED"
    validate_action_envelope(outcome.response)
    assert [event.event_type.value for event in events.load_stream("thread-old")][-2:] == [
        "StateReconciliationSelected",
        "ThreadSuperseded",
    ]


def test_reinitialize_selection_is_idempotent(tmp_path: Path) -> None:
    events, _, gate = _seed(tmp_path)
    service = StateReconciliationService(events)
    result = _result(gate)

    first = service.select(result)
    repeated = service.select(result)

    assert repeated == first
    assert len(events.load_stream("thread-old")) == 3


def test_selection_must_bind_active_gate_message(tmp_path: Path) -> None:
    events, _, gate = _seed(tmp_path)
    result = _result(gate)
    result["causation_id"] = "wrong-gate"

    with pytest.raises(StateReconciliationError, match="causation"):
        StateReconciliationService(events).select(result)


def test_unknown_selection_fails_closed(tmp_path: Path) -> None:
    events, _, gate = _seed(tmp_path)

    with pytest.raises(StateReconciliationError, match="resolution"):
        StateReconciliationService(events).select(_result(gate, "discard-everything"))


def test_cli_reinitialize_creates_new_thread_and_replays_new_action(tmp_path: Path) -> None:
    design = tmp_path / "design" / "current.md"
    design.parent.mkdir()
    design.write_text(
        "## B1. 页面\n### B1.1 容器\n#### 初始化页面\n",
        encoding="utf-8",
    )
    events, _, gate = _seed(tmp_path)
    checkpoints: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(":memory:")
    assert checkpoints.reserve_project_thread("thread-old") is None
    checkpoints.record_protocol_action(gate)
    result = _result(gate)
    result_file = tmp_path / "result.json"
    result_file.write_text(json.dumps(result), encoding="utf-8")

    action = _process_state_reconciliation_result(
        result_file=result_file,
        root=tmp_path,
        store=checkpoints,
        events=events,
    )

    assert action is not None
    assert action["thread_id"] != "thread-old"
    assert action["action"] == "project_setup_required"
    assert checkpoints.active_project_thread() == action["thread_id"]
    old_projection = events.load_projection("thread-old")
    assert old_projection is not None
    assert old_projection.thread_status == "superseded"
    assert events.load_projection(action["thread_id"]) is not None

    repeated = _process_state_reconciliation_result(
        result_file=result_file,
        root=tmp_path,
        store=checkpoints,
        events=events,
    )
    assert repeated == action
