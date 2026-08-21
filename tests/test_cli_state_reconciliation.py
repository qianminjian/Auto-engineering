from __future__ import annotations

from pathlib import Path

from auto_engineering.cli.dev_loop import _resolve_active_thread_start
from auto_engineering.engine.state import EngineState
from auto_engineering.loop.invocation_intent import InvocationIntent


class _Store:
    def __init__(self, thread_id: str, active_action: dict | None = None) -> None:
        self.thread_id = thread_id
        self.active_action = active_action
        self.recorded: list[dict] = []

    def active_project_thread(self) -> str:
        return self.thread_id

    def load_active_protocol_action(self, thread_id: str) -> dict | None:
        assert thread_id == self.thread_id
        return self.active_action

    def record_protocol_action(self, action: dict) -> None:
        self.recorded.append(action)


class _Events:
    def __init__(self, state: EngineState, action: dict | None = None) -> None:
        self.state = state
        self.action = action
        self.committed: list[dict] = []

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
    old_action = {"action": "developer", "thread_id": state.thread_id}
    store = _Store(state.thread_id, old_action)

    events = _Events(state, old_action)
    action = _resolve_active_thread_start(
        root=tmp_path,
        design_doc_path="design/feature.md",
        store=store,
        events=events,
    )

    assert action is not None
    assert action["action"] == "gate"
    assert action["gate"]["id"] == "state_reconciliation"
    assert [item["id"] for item in action["gate"]["options"]] == [
        "reinitialize",
        "reconcile",
    ]
    assert action["extensions"]["ae"]["execution_control"]["disposition"] == "WAIT_USER"
    assert store.recorded == [action]
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
    store = _Store(state.thread_id, old_action)

    action = _resolve_active_thread_start(
        root=tmp_path,
        design_doc_path="design/feature.md",
        store=store,
        events=_Events(state, old_action),
    )

    assert action == old_action
    assert store.recorded == []


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
    store = _Store(state.thread_id, old_action)

    action = _resolve_active_thread_start(
        root=tmp_path,
        design_doc_path="design/feature.md",
        store=store,
        events=_Events(state, old_action),
    )

    assert action == old_action
    assert store.recorded == []


def test_repeated_conflict_reuses_gate_without_duplicate_event(tmp_path: Path) -> None:
    _, state = _intent_and_state(tmp_path)
    store = _Store(state.thread_id)
    first_events = _Events(state)
    first = _resolve_active_thread_start(
        root=tmp_path,
        design_doc_path="design/feature.md",
        store=store,
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
        store=store,
        events=repeated_events,
    )

    assert repeated is not None
    assert repeated["message_id"] == first["message_id"]
    assert repeated_events.committed == []
