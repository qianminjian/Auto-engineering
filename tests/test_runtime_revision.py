"""Phase 80 T405：运行时兼容向量与 Action 边界激活。"""

from __future__ import annotations

from pathlib import Path

from auto_engineering.build_identity import source_build_identity
from auto_engineering.loop.runtime_revision import (
    CompatibilityDecision,
    RuntimeRevision,
    evaluate_compatibility,
)


def test_source_build_identity_changes_with_runtime_content(tmp_path: Path) -> None:
    package = tmp_path / "auto_engineering"
    package.mkdir()
    (package / "engine.py").write_text("VALUE = 1\n", encoding="utf-8")
    first = source_build_identity(package, version="5.8.0-rc.5")

    (package / "engine.py").write_text("VALUE = 2\n", encoding="utf-8")
    second = source_build_identity(package, version="5.8.0-rc.5")

    assert first != second
    assert first.startswith("5.8.0-rc.5+source.sha256.")


def _revision(*, prompt: str = "prompt-a", build: str = "rc.5") -> RuntimeRevision:
    return RuntimeRevision(
        protocol_version="1.1",
        event_schema_version="1.0",
        projection_schema_version="1.0",
        action_contract_version="1.1",
        prompt_revision=prompt,
        policy_revision="policy-a",
        engine_build_id=build,
    )


def test_runtime_revision_round_trips_with_stable_field_set() -> None:
    revision = _revision()

    assert RuntimeRevision.from_dict(revision.to_dict()) == revision
    assert list(revision.to_dict()) == [
        "protocol_version",
        "event_schema_version",
        "projection_schema_version",
        "action_contract_version",
        "prompt_revision",
        "policy_revision",
        "engine_build_id",
    ]


def test_engine_build_change_is_audit_only() -> None:
    assert evaluate_compatibility(
        issued=_revision(build="rc.5"),
        current=_revision(build="rc.6"),
        has_active_action=True,
    ) is CompatibilityDecision.COMPATIBLE


def test_prompt_change_waits_for_active_action_boundary() -> None:
    assert evaluate_compatibility(
        issued=_revision(prompt="old"),
        current=_revision(prompt="new"),
        has_active_action=True,
    ) is CompatibilityDecision.ACTIVATE_AFTER_ACTION


def test_prompt_change_activates_immediately_without_active_action() -> None:
    assert evaluate_compatibility(
        issued=_revision(prompt="old"),
        current=_revision(prompt="new"),
        has_active_action=False,
    ) is CompatibilityDecision.COMPATIBLE


def test_unknown_protocol_without_migrator_is_incompatible() -> None:
    issued = RuntimeRevision.from_dict({
        **_revision().to_dict(),
        "protocol_version": "9.0",
    })

    assert evaluate_compatibility(
        issued=issued,
        current=_revision(),
        has_active_action=True,
    ) is CompatibilityDecision.INCOMPATIBLE


def test_restore_activates_new_prompt_revision_only_after_active_action(
    tmp_path, monkeypatch
) -> None:
    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator
    from tests.test_tick_orchestrator import _store_orchestrator

    class _Registry:
        def registry_hash(self) -> str:
            return "new-prompt-revision"

    db = tmp_path / "checkpoint.db"
    store = SQLiteCheckpointStore(db)
    original = _store_orchestrator(store)
    active_action = original.init("实现 X")
    old_revision = active_action["extensions"]["ae"]["runtime_revision"]
    store.close()

    monkeypatch.setattr(
        "auto_engineering.loop.tick_orchestrator.default_registry",
        lambda: _Registry(),
    )
    restored_store = SQLiteCheckpointStore(db)
    restored = TickOrchestrator.restore(tmp_path, restored_store)

    assert restored._active_action["message_id"] == active_action["message_id"]
    assert restored._state.active_runtime_revision == old_revision
    assert restored._state.pending_runtime_revision["prompt_revision"] == (
        "new-prompt-revision"
    )

    restored._current_result_message_id = "result-for-active-action"
    next_action = restored.build_action()

    assert next_action["message_id"] != active_action["message_id"]
    assert next_action["extensions"]["ae"]["runtime_revision"][
        "prompt_revision"
    ] == "new-prompt-revision"
    assert restored._state.pending_runtime_revision is None
    restored_store.close()
