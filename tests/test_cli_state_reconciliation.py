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

    def load_projection(self, thread_id: str) -> EngineState:
        assert thread_id == self.state.thread_id
        return self.state

    def load_action_snapshot(self, thread_id: str) -> dict | None:
        assert thread_id == self.state.thread_id
        return self.action


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

    action = _resolve_active_thread_start(
        root=tmp_path,
        design_doc_path="design/feature.md",
        store=store,
        events=_Events(state, old_action),
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
