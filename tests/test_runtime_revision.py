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


def test_packaged_build_identity_requires_matching_metadata(tmp_path: Path) -> None:
    from auto_engineering import __version__
    from auto_engineering.build_identity import _read_packaged_build_identity

    package_root = tmp_path / "bundle" / "auto_engineering"
    package_root.mkdir(parents=True)
    (package_root.parent / "build-info.json").write_text(
        __import__("json").dumps({
            "build_id": "5.8.0-rc.5+sha256.test",
            "version": __version__,
            "content_sha256": "a" * 64,
        }),
        encoding="utf-8",
    )

    assert _read_packaged_build_identity(package_root) == (
        "5.8.0-rc.5+sha256.test"
    )


def test_packaged_build_identity_rejects_invalid_metadata(tmp_path: Path) -> None:
    from auto_engineering.build_identity import _read_packaged_build_identity

    package_root = tmp_path / "bundle" / "auto_engineering"
    package_root.mkdir(parents=True)
    (package_root.parent / "build-info.json").write_text(
        '{"build_id":"bad","version":"wrong","content_sha256":"bad"}',
        encoding="utf-8",
    )

    assert _read_packaged_build_identity(package_root) is None


def test_build_info_contract_is_shared_by_acceptance_entrypoints() -> None:
    from auto_engineering import build_identity

    validator = getattr(build_identity, "validate_build_info", None)
    assert callable(validator)
    assert validator({
        "version": "5.8.0-rc.5",
        "build_id": "5.8.0-rc.5+sha256.aaaaaaaaaaaaaaaa",
        "content_sha256": "a" * 64,
    }) == {
        "version": "5.8.0-rc.5",
        "build_id": "5.8.0-rc.5+sha256.aaaaaaaaaaaaaaaa",
        "content_sha256": "a" * 64,
    }


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


def test_runtime_revision_diff_names_incompatible_fields() -> None:
    from auto_engineering.loop.runtime_revision import incompatible_fields

    issued = _revision()
    current = RuntimeRevision.from_dict({
        **issued.to_dict(),
        "protocol_version": "1.2",
        "action_contract_version": "1.2",
    })

    assert incompatible_fields(issued=issued, current=current) == {
        "protocol_version": {"expected": "1.2", "actual": "1.1"},
        "action_contract_version": {"expected": "1.2", "actual": "1.1"},
    }




def test_event_store_restore_does_not_require_legacy_checkpoint(tmp_path) -> None:
    from unittest.mock import MagicMock

    from auto_engineering.loop.event_store import SQLiteEventStore
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    (tmp_path / "pyproject.toml").write_text("[project]\nname='event-only'\n")
    (tmp_path / "event_only").mkdir()
    guardrail = MagicMock()
    guardrail.check.return_value = MagicMock(action="pass")
    with SQLiteEventStore(tmp_path / "events.db") as events:
        original = TickOrchestrator(
            tmp_path,
            event_store=events,
            guardrail=guardrail,
        )
        action = original.init("验证纯事件恢复")

        restored = TickOrchestrator.restore_from_event_store(
            tmp_path,
            event_store=events,
            thread_id=action["thread_id"],
            guardrail=guardrail,
        )

        assert restored._state.thread_id == action["thread_id"]
        assert restored._active_action == action
