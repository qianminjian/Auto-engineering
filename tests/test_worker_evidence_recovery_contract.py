"""Worker evidence 与跨会话 generation 恢复的合同回归。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_engineering.host.path_contract import worker_outcome_path
from auto_engineering.host.runtime_driver import HostRunLease, HostRunLeaseStore
from auto_engineering.host.worker_evidence import (
    HostEvidenceValidationError,
    _canonical_worker_business_status,
    _native_business_artifact,
    native_outcomes_are_ready,
    parse_private_worker_artifact,
)


def test_native_result_accepts_one_wrapped_nested_business_object() -> None:
    artifact = _native_business_artifact(
        {
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": '前缀 {"plan":{"steps":["保留嵌套"]}} 后缀',
                    }
                ]
            }
        },
        worker_id="architect-0",
        status="completed",
    )

    assert artifact == {
        "worker_id": "architect-0",
        "status": "completed",
        "payload": {"plan": {"steps": ["保留嵌套"]}},
        "summary": "native_worker_result",
    }


def test_native_result_accepts_text_block_list_and_normalizes_alias_status() -> None:
    artifact = _native_business_artifact(
        [{"type": "text", "text": '{"files_changed":[]}'}],
        worker_id="developer-0",
        status="success",
    )

    assert artifact["status"] == "success"
    assert artifact["payload"] == {"files_changed": []}


@pytest.mark.parametrize(
    "raw",
    [
        {"result": []},
        {"content": [{"type": "image", "data": "ignored"}]},
        {"content": [{"type": "text", "text": "{not-json"}]},
        [{"type": "image", "data": "ignored"}],
        [{"type": "text", "text": "{not-json"}],
        {"result": {"result": {"plan": "nested-wrapper"}}},
    ],
)
def test_native_result_rejects_missing_or_ambiguous_business_object(raw: object) -> None:
    with pytest.raises(HostEvidenceValidationError, match="WORKER_NATIVE_RESULT_INVALID"):
        _native_business_artifact(
            raw,
            worker_id="worker-0",
            status="completed",
        )


@pytest.mark.parametrize(
    "raw",
    [
        {"plan": "ok", "native_worker_handle": "forbidden"},
        {"worker_id": "worker-0", "status": "completed"},
        {
            "worker_id": "other-worker",
            "status": "completed",
            "payload": {},
            "summary": "wrong identity",
        },
    ],
)
def test_native_result_rejects_host_fields_and_partial_worker_envelopes(raw: object) -> None:
    with pytest.raises(HostEvidenceValidationError, match="WORKER_NATIVE_RESULT"):
        _native_business_artifact(raw, worker_id="worker-0", status="completed")


def test_native_result_rejects_non_mapping_result_wrapper() -> None:
    with pytest.raises(HostEvidenceValidationError, match="WORKER_NATIVE_RESULT_INVALID"):
        _native_business_artifact(
            {"result": "not-an-object"},
            worker_id="worker-0",
            status="completed",
        )


def test_private_worker_artifact_accepts_one_outcome_wrapper() -> None:
    raw = {
        "outcome": {
            "worker_id": "worker-0",
            "status": "completed",
            "payload": {"plan": "done"},
            "summary": "业务完成",
        }
    }

    assert parse_private_worker_artifact(raw, worker_id="worker-0") == raw["outcome"]


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {
            "worker_id": "other-worker",
            "status": "completed",
            "payload": {},
            "summary": "业务完成",
        },
        {
            "worker_id": "worker-0",
            "status": "completed",
            "payload": [],
            "summary": "业务完成",
        },
    ],
)
def test_private_worker_artifact_rejects_invalid_envelope(raw: object) -> None:
    with pytest.raises(
        HostEvidenceValidationError,
        match="WORKER_PRIVATE_ARTIFACT_INVALID:worker-0",
    ):
        parse_private_worker_artifact(raw, worker_id="worker-0")


def test_private_worker_artifact_normalizes_missing_summary_once() -> None:
    raw = {"worker_id": "worker-0", "status": "completed", "payload": {}}

    assert parse_private_worker_artifact(raw, worker_id="worker-0") == {
        **raw,
        "summary": "native_worker_result",
    }


def test_business_status_normalization_is_fail_closed_for_non_string() -> None:
    assert _canonical_worker_business_status(None) is None
    assert _canonical_worker_business_status("timeout") == "timed_out"


def test_native_ready_rejects_stale_generation_or_fence() -> None:
    action = {
        "message_id": "action-ready",
        "execution_generation": 2,
        "fencing_token": "f" * 64,
        "spawn": {"invocations": [{"worker_id": "worker-0"}]},
        "host_execution": {
            "workers": [{
                "worker_id": "worker-0",
                "execution_generation": 2,
                "fencing_token": "f" * 64,
            }],
        },
    }
    outcome = {
        "worker_id": "worker-0",
        "native_worker_handle": "native-0",
        "status": "completed",
        "payload": {"done": True},
        "summary": "完成",
        "actual_model": "test-model",
        "isolation_evidence": "fresh_context",
        "execution_generation": 2,
        "fencing_token": "f" * 64,
    }
    assert native_outcomes_are_ready(action=action, outcome_items=[outcome])
    stale_generation = {**outcome, "execution_generation": 1}
    stale_fence = {**outcome, "fencing_token": "e" * 64}
    assert not native_outcomes_are_ready(
        action=action, outcome_items=[stale_generation]
    )
    assert not native_outcomes_are_ready(action=action, outcome_items=[stale_fence])


def _action_with_worker(message_id: str = "action-private-recovery") -> dict:
    return {
        "message_id": message_id,
        "thread_id": "thread-private-recovery",
        "spawn": {"invocations": [{"worker_id": "worker-0"}]},
    }


def _save_lease(root: Path, action: dict, *, session: str) -> None:
    HostRunLeaseStore(root).save(
        HostRunLease.from_action(
            {
                **action,
                "extensions": {
                    "ae": {
                        "execution_control": {
                            "schema_version": "1.0",
                            "disposition": "CONTINUE",
                            "continuation_required": True,
                            "yield_allowed": False,
                            "allowed_stop_reasons": [],
                        },
                        "runtime": {"build_id": "build-private-recovery"},
                    }
                },
            },
            platform="codex",
            host_session_id=session,
        )
    )


def test_valid_private_outcome_reuses_generation_after_host_takeover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from auto_engineering.cli.dev_loop import _bind_worker_execution_identity

    monkeypatch.setenv("AE_HOST_PLATFORM", "codex")
    monkeypatch.setenv("CODEX_THREAD_ID", "session-a")
    action = _action_with_worker()
    first = _bind_worker_execution_identity(action, tmp_path)
    _save_lease(tmp_path, first, session="session-a")
    outcome_path = tmp_path / worker_outcome_path(
        action["message_id"], "worker-0", 1
    )
    outcome_path.parent.mkdir(parents=True, exist_ok=True)
    outcome_path.write_text(
        json.dumps(
            {
                "worker_id": "worker-0",
                "status": "completed",
                "payload": {"plan": "已落盘"},
                "summary": "业务完成",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("CODEX_THREAD_ID", "session-b")
    resumed = _bind_worker_execution_identity(action, tmp_path)

    assert first["execution_generation"] == 1
    assert resumed["execution_generation"] == 1
    assert resumed["fencing_token"] != first["fencing_token"]


def test_worker_execution_binding_rewrites_core_invocation_to_current_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from auto_engineering.cli.dev_loop import _bind_worker_execution_identity

    monkeypatch.setenv("AE_HOST_PLATFORM", "codex")
    monkeypatch.setenv("CODEX_THREAD_ID", "session-bound-path")
    action = _action_with_worker("action-bound-path")
    bound = _bind_worker_execution_identity(action, tmp_path)
    invocation = bound["spawn"]["invocations"][0]
    assert invocation["outcome_path"] == worker_outcome_path(
        "action-bound-path", "worker-0", bound["execution_generation"]
    )


def test_valid_private_outcome_reuses_latest_generation_after_lease_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from auto_engineering.cli.dev_loop import _bind_worker_execution_identity

    monkeypatch.setenv("AE_HOST_PLATFORM", "codex")
    monkeypatch.setenv("CODEX_THREAD_ID", "session-after-stop")
    action = _action_with_worker("action-private-no-lease")
    outcome_path = tmp_path / worker_outcome_path(
        action["message_id"], "worker-0", 3
    )
    outcome_path.parent.mkdir(parents=True, exist_ok=True)
    outcome_path.write_text(
        json.dumps(
            {
                "worker_id": "worker-0",
                "status": "completed",
                "payload": {"plan": "可恢复"},
                "summary": "业务完成",
            }
        ),
        encoding="utf-8",
    )

    resumed = _bind_worker_execution_identity(action, tmp_path)

    assert resumed["execution_generation"] == 3
