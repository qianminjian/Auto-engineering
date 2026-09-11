from __future__ import annotations

from pathlib import Path

import pytest

from auto_engineering.cli.dev_loop import _resolve_active_thread_start
from auto_engineering.engine.state import EngineState
from auto_engineering.loop.invocation_intent import InvocationIntent


class _Events:
    def __init__(self, state: EngineState, action: dict | None = None) -> None:
        self.state = state
        self.action = action
        self.committed: list[dict] = []

    def current_thread(self) -> str:
        return self.state.thread_id

    def unfinished_threads(self) -> list[str]:
        return [self.state.thread_id]

    def load_projection(self, thread_id: str) -> EngineState:
        assert thread_id == self.state.thread_id
        return self.state

    def load_action_snapshot(self, thread_id: str) -> dict | None:
        assert thread_id == self.state.thread_id
        return self.action

    def next_sequence(self, thread_id: str) -> int:
        assert thread_id == self.state.thread_id
        return 1

    def commit_tick(self, **commit: object) -> None:
        self.committed.append(commit)


def _intent_and_state(root: Path) -> tuple[InvocationIntent, EngineState]:
    design = root / "design" / "feature.md"
    design.parent.mkdir()
    design.write_text("# Current design\n", encoding="utf-8")
    intent = InvocationIntent.from_design_doc(root, "design/feature.md")
    state = EngineState(
        thread_id="old-thread",
        current_stage="developer",
        design_doc_path=intent.design_doc_path,
        architecture_baseline={
            "design_doc": {
                "path": intent.design_doc_path,
                "digest": intent.design_doc_digest.removeprefix("sha256:"),
            }
        },
        project_profile={
            "paths": {"source_roots": ["src"], "test_roots": ["tests"]},
            "evidence": [],
        },
    )
    return intent, state


def test_conflicting_active_thread_returns_persisted_decision_gate(tmp_path: Path) -> None:
    _, state = _intent_and_state(tmp_path)
    state.project_anchor_baseline = ["src", "tests"]
    old_action = {"action": "developer", "thread_id": state.thread_id}
    events = _Events(state, old_action)
    action = _resolve_active_thread_start(
        root=tmp_path,
        design_doc_path="design/feature.md",
        events=events,
    )

    assert action is not None
    assert action["action"] == "gate"
    assert action["project_root"] == str(tmp_path.resolve())
    assert action["gate"]["id"] == "state_reconciliation"
    assert [item["id"] for item in action["gate"]["options"]] == [
        "reinitialize",
        "reconcile",
    ]
    assert action["extensions"]["ae"]["execution_control"]["disposition"] == "WAIT_USER"
    assert action["expected_format"] == {
        "gate_resolution": {
            "gate_id": "state_reconciliation",
            "resolution": "reinitialize | reconcile",
        },
    }
    assert action["result_contract"] == {
        "schema_version": "1.0",
        "required": ["gate_resolution"],
        "properties": {"gate_resolution": {"type": "object"}},
        "additionalProperties": False,
    }
    assert "禁止提交顶层 decision" in action["instruction"]
    assert len(events.committed) == 1
    committed_event = events.committed[0]["events"][0]
    assert committed_event.causation_id == action["message_id"]
    assert events.committed[0]["action"] == action


def test_compatible_active_thread_returns_original_action(tmp_path: Path) -> None:
    _, state = _intent_and_state(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "package.json").write_text(
        '{"scripts":{"test":"vitest"}}', encoding="utf-8"
    )
    old_action = {
        "action": "developer",
        "thread_id": state.thread_id,
        "message_id": "existing-action",
    }
    action = _resolve_active_thread_start(
        root=tmp_path,
        design_doc_path="design/feature.md",
        events=_Events(state, old_action),
    )

    assert action == old_action


def test_pre_architect_gap_thread_resumes_from_init_digest(tmp_path: Path) -> None:
    intent, state = _intent_and_state(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "package.json").write_text(
        '{"scripts":{"test":"vitest"}}', encoding="utf-8",
    )
    state.current_stage = "gap_review"
    state.architecture_baseline = None
    state.design_doc_digest = intent.design_doc_digest
    old_action = {
        "action": "gap_review",
        "stage": "gap_review",
        "thread_id": state.thread_id,
        "message_id": "gap-action",
    }
    action = _resolve_active_thread_start(
        root=tmp_path,
        design_doc_path="design/feature.md",
        events=_Events(state, old_action),
    )

    assert action == old_action


def test_repeated_conflict_reuses_gate_without_duplicate_event(tmp_path: Path) -> None:
    _, state = _intent_and_state(tmp_path)
    state.project_anchor_baseline = ["src", "tests"]
    first_events = _Events(state)
    first = _resolve_active_thread_start(
        root=tmp_path,
        design_doc_path="design/feature.md",
        events=first_events,
    )
    assert first is not None
    state.state_reconciliation = {
        "status": "waiting_user",
        "gate_message_id": first["message_id"],
    }
    repeated_events = _Events(state)

    repeated = _resolve_active_thread_start(
        root=tmp_path,
        design_doc_path="design/feature.md",
        events=repeated_events,
    )

    assert repeated is not None
    assert repeated["message_id"] == first["message_id"]
    assert repeated_events.committed == []


def test_interrupted_architect_resumes_when_declared_roots_never_existed(
    tmp_path: Path,
) -> None:
    _, state = _intent_and_state(tmp_path)
    state.current_stage = "architect"
    state.project_anchor_baseline = []
    old_action = {
        "action": "agent",
        "stage": "architect",
        "thread_id": state.thread_id,
        "message_id": "architect-action",
    }
    action = _resolve_active_thread_start(
        root=tmp_path,
        design_doc_path="design/feature.md",
        events=_Events(state, old_action),
    )

    assert action == old_action


def test_recovery_projection_builds_and_rejects_invalid_action_identity(
    tmp_path: Path,
) -> None:
    from auto_engineering.cli.state_reconciliation_projection import (
        build_recovery_gate,
        host_mapping_error_action,
    )

    expected = {"gate_resolution": {"gate_id": "state_reconciliation"}}
    contract = {"required": ["gate_resolution"]}
    gate = build_recovery_gate(
        {"thread_id": "thread-1", "tick": 3, "stage": "developer", "message_id": "old"},
        tmp_path,
        expected_format=expected,
        result_contract=contract,
    )
    assert gate["action"] == "gate"
    assert gate["gate"]["id"] == "state_reconciliation"

    with pytest.raises(ValueError, match="ACTION_IDENTITY_MISSING"):
        build_recovery_gate(
            {"thread_id": "thread-1", "tick": "3"},
            tmp_path,
            expected_format=expected,
            result_contract=contract,
        )

    error = host_mapping_error_action(
        {"thread_id": "thread-1", "tick": 3, "stage": "developer", "message_id": "old"},
        ValueError("ACTION_INVALID"),
        expected_format=expected,
        result_contract=contract,
    )
    assert error["action"] == "error"
    assert error["error_code"] == "ACTION_INVALID"
    assert host_mapping_error_action(
        {}, ValueError("ACTION_INVALID"),
        expected_format=expected,
        result_contract=contract,
    )["error_code"] == "ACTION_INVALID"


def test_persisted_recovery_projection_is_idempotent(tmp_path: Path) -> None:
    from auto_engineering.cli.state_reconciliation_projection import (
        persist_recovery_gate,
        persisted_reconciliation_gate_status,
    )
    from auto_engineering.loop.event_store import SQLiteEventStore
    from auto_engineering.loop.events import LoopEvent, LoopEventType

    state = EngineState(thread_id="thread-1", current_stage="developer")
    with SQLiteEventStore(tmp_path / "events.db") as events:
        events.commit_tick(
            events=[LoopEvent.create(
                thread_id=state.thread_id,
                sequence=0,
                event_type=LoopEventType.LOOP_INITIALIZED,
                payload={"state": state.to_dict()},
                correlation_id=state.thread_id,
            )],
            state=state,
            action={"thread_id": state.thread_id, "message_id": "action-1"},
        )
        kwargs = {
            "expected_format": {"gate_resolution": {"gate_id": "state_reconciliation"}},
            "result_contract": {"required": ["gate_resolution"]},
        }
        first = persist_recovery_gate(
            {"thread_id": state.thread_id, "tick": 0, "message_id": "action-1"},
            state,
            events,
            tmp_path,
            **kwargs,
        )
        projected = events.load_projection(state.thread_id)
        assert projected is not None
        second = persist_recovery_gate(
            {"thread_id": state.thread_id, "tick": 0, "message_id": "action-1"},
            projected,
            events,
            tmp_path,
            **kwargs,
        )
        assert second["message_id"] == first["message_id"]
        assert len(events.load_stream(state.thread_id)) == 2
        status = persisted_reconciliation_gate_status(
            first,
            projected,
            status_action={"action": "gate"},
            next_operation={"operation": "resume"},
        )
        assert status is not None
        assert status["active_action"] == {"action": "gate"}
        assert persisted_reconciliation_gate_status(
            {"action": "developer"}, projected,
            status_action={}, next_operation={},
        ) is None


@pytest.mark.parametrize(
    "content",
    ["not-json", "[]", '{"gate_resolution": {"gate_id": "other"}}'],
)
def test_state_reconciliation_result_projection_ignores_non_current_files(
    tmp_path: Path, content: str,
) -> None:
    from auto_engineering.cli.state_reconciliation_projection import (
        validate_state_reconciliation_result_file,
    )

    result_file = tmp_path / "result.json"
    result_file.write_text(content, encoding="utf-8")
    assert validate_state_reconciliation_result_file(
        result_file=result_file,
        active_thread="thread-1",
        events=object(),  # early returns must not touch the EventStore
    ) is None


def test_state_reconciliation_result_rejects_wrong_thread(tmp_path: Path) -> None:
    from auto_engineering.cli.state_reconciliation_projection import (
        validate_state_reconciliation_result_file,
    )

    result_file = tmp_path / "result.json"
    result_file.write_text(
        '{"thread_id":"other","gate_resolution":{"gate_id":"state_reconciliation"}}',
        encoding="utf-8",
    )
    result = validate_state_reconciliation_result_file(
        result_file=result_file,
        active_thread="thread-1",
        events=object(),
    )
    assert result is not None
    assert result["error_code"] == "ACTION_NOT_ACTIVE"
