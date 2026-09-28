"""宿主租约、失败恢复和连续驱动边界的行为回归。"""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_engineering.host import HostPlatform
from auto_engineering.host.runtime_driver import (
    HostRunLease,
    HostRunLeaseError,
    HostRunLeaseStore,
    StopGuardDecision,
    evaluate_stop,
    host_session_id_from_environ,
)


def _action() -> dict[str, object]:
    return {
        "thread_id": "thread-lease",
        "message_id": "action-lease",
        "execution_generation": 2,
        "extensions": {
            "ae": {
                "execution_control": {
                    "schema_version": "1.0",
                    "disposition": "CONTINUE",
                    "continuation_required": True,
                    "yield_allowed": False,
                    "allowed_stop_reasons": [],
                },
                "runtime": {"build_id": "build-lease"},
            }
        },
    }


def test_lease_from_action_falls_back_to_runtime_revision_and_rejects_bad_inputs() -> None:
    action = _action()
    action["extensions"]["ae"].pop("runtime")  # type: ignore[index]
    action["extensions"]["ae"]["runtime_revision"] = {  # type: ignore[index]
        "engine_build_id": "build-revision"
    }
    lease = HostRunLease.from_action(
        action, platform="codex", host_session_id="session-lease"
    )
    assert lease.build_id == "build-revision"

    for invalid in (
        {**action, "thread_id": ""},
        {**action, "execution_generation": True},
        {**action, "extensions": {}},
    ):
        with pytest.raises(HostRunLeaseError):
            HostRunLease.from_action(
                invalid, platform="codex", host_session_id="session-lease"
            )


def test_lease_from_dict_normalizes_legacy_token_and_rejects_forgery() -> None:
    lease = HostRunLease.from_action(
        _action(), platform="codex", host_session_id="session-lease"
    )
    raw = lease.to_dict()
    raw.pop("fencing_token")
    restored = HostRunLease.from_dict(raw)
    assert restored.fencing_token == lease.fencing_token

    with pytest.raises(HostRunLeaseError, match="HOST_RUN_LEASE_FENCE_INVALID"):
        HostRunLease.from_dict({**raw, "fencing_token": "forged"})
    with pytest.raises(HostRunLeaseError, match="HOST_RUN_LEASE_FIELDS_INVALID"):
        HostRunLease.from_dict({**raw, "unexpected": True})


def test_lease_store_fails_closed_for_corrupt_and_non_object_files(tmp_path: Path) -> None:
    store = HostRunLeaseStore(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("not-json", encoding="utf-8")
    with pytest.raises(HostRunLeaseError, match="HOST_RUN_LEASE_CORRUPT"):
        store.load()
    store.path.write_text("[]", encoding="utf-8")
    with pytest.raises(HostRunLeaseError, match="HOST_RUN_LEASE_INVALID"):
        store.load()


def test_lease_store_clear_if_matches_is_compare_and_delete(tmp_path: Path) -> None:
    store = HostRunLeaseStore(tmp_path)
    lease = HostRunLease.from_action(
        _action(), platform="codex", host_session_id="session-lease"
    )
    store.save(lease)
    different = HostRunLease.from_action(
        {**_action(), "message_id": "other-action"},
        platform="codex",
        host_session_id="session-lease",
    )
    assert store.clear_if_matches(different) is False
    assert store.clear_if_matches(lease) is True
    assert store.clear_if_matches(lease) is False
    store.clear()


def test_stop_guard_blocks_only_same_session_non_yieldable_continue() -> None:
    lease = HostRunLease.from_action(
        _action(), platform="codex", host_session_id="session-lease"
    )
    assert evaluate_stop(lease, host_session_id="session-lease") is StopGuardDecision.BLOCK
    assert evaluate_stop(lease, host_session_id="other-session") is StopGuardDecision.ALLOW
    assert evaluate_stop(None, host_session_id="session-lease") is StopGuardDecision.ALLOW


def test_session_id_lookup_respects_platform_and_legacy_mapping_call() -> None:
    env = {
        "CODEX_THREAD_ID": "codex-thread",
        "CLAUDE_CODE_SESSION_ID": "claude-session",
    }
    assert host_session_id_from_environ(HostPlatform.CODEX, env) == "codex-thread"
    assert host_session_id_from_environ(HostPlatform.CLAUDE_CODE, env) == "claude-session"
    assert host_session_id_from_environ(HostPlatform.UNKNOWN, env) == "codex-thread"
    assert host_session_id_from_environ({"CLAUDE_SESSION_ID": "legacy"}) == "legacy"
    assert host_session_id_from_environ(HostPlatform.CODEX, {}) is None


def test_lease_to_dict_recomputes_empty_legacy_fence() -> None:
    lease = HostRunLease(
        schema_version="1.0",
        thread_id="thread-lease",
        action_message_id="action-lease",
        platform="codex",
        host_session_id="session-lease",
        build_id="build-lease",
        disposition="CONTINUE",
        continuation_required=True,
        yield_allowed=False,
        execution_generation=1,
        fencing_token="",
    )
    payload = lease.to_dict()
    assert payload["fencing_token"]
