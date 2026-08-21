"""Phase 80 T406：机器化执行处置与宿主连续驱动。"""

from __future__ import annotations

import hashlib
import json

import pytest

from auto_engineering.host import HostPlatform
from auto_engineering.host.driver_contract import HostDriverDecision, decide_host_step
from auto_engineering.host.runtime_driver import (
    HostRunLease,
    HostRunLeaseStore,
    StopGuardDecision,
    evaluate_stop,
    host_session_id_from_environ,
)
from auto_engineering.loop.execution_control import (
    ExecutionControl,
    ExecutionControlError,
    ExecutionDisposition,
    control_for_action,
)


def test_continue_control_forbids_yield() -> None:
    control = control_for_action({"action": "developer"})

    assert control == ExecutionControl(
        schema_version="1.0",
        disposition=ExecutionDisposition.CONTINUE,
        continuation_required=True,
        yield_allowed=False,
        allowed_stop_reasons=(),
        reason_code=None,
    )


def test_invalid_continue_combination_is_rejected() -> None:
    with pytest.raises(ExecutionControlError, match="CONTINUE"):
        ExecutionControl.from_dict({
            "schema_version": "1.0",
            "disposition": "CONTINUE",
            "continuation_required": True,
            "yield_allowed": True,
            "allowed_stop_reasons": [],
        })


def test_gap_review_waits_for_real_user_decision() -> None:
    control = control_for_action({"action": "gap_review"})

    assert control.disposition is ExecutionDisposition.WAIT_USER
    assert control.reason_code == "gap_decisions_required"


def test_gap_review_with_core_auto_decision_continues() -> None:
    control = control_for_action({
        "action": "gap_review",
        "auto_decision": {
            "gap_id": "gap-2",
            "resolution": "Fill",
            "decision_source": "thread_policy",
        },
    })

    assert control.disposition is ExecutionDisposition.CONTINUE


def test_environment_failure_waits_instead_of_reentering_code_repair() -> None:
    control = control_for_action({
        "action": "developer",
        "gate_summary": {
            "task_evidence": {"status": "environment_failure", "passed": False}
        },
    })

    assert control.disposition is ExecutionDisposition.WAIT_USER
    assert control.reason_code == "environment_failure"


def test_agent_capacity_waits_for_resource_without_user_decision() -> None:
    control = control_for_action({
        "action": "resource_wait",
        "reason_code": "HOST_AGENT_CAPACITY",
    })

    assert control.disposition is ExecutionDisposition.WAIT_RESOURCE
    assert control.continuation_required is False
    assert control.yield_allowed is True
    assert control.reason_code == "HOST_AGENT_CAPACITY"


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ({"action": "developer"}, HostDriverDecision.EXECUTE_NEXT),
        ({"action": "gap_review"}, HostDriverDecision.WAIT),
        ({"action": "done"}, HostDriverDecision.FINISH),
        ({"action": "error"}, HostDriverDecision.FAIL),
        ({"action": "session_rollover"}, HostDriverDecision.HANDOFF),
        (
            {"action": "resource_wait", "reason_code": "HOST_AGENT_CAPACITY"},
            HostDriverDecision.RETRY_RESOURCE,
        ),
    ],
)
def test_host_driver_uses_only_machine_disposition(
    action: dict[str, str],
    expected: HostDriverDecision,
) -> None:
    control = control_for_action(action)
    payload = {"extensions": {"ae": {"execution_control": control.to_dict()}}}

    assert decide_host_step(payload) is expected


def test_active_continue_lease_blocks_same_session_stop(tmp_path) -> None:
    action = {
        "message_id": "action-1",
        "thread_id": "thread-1",
        "extensions": {
            "ae": {
                "execution_control": ExecutionControl(
                    schema_version="1.0",
                    disposition=ExecutionDisposition.CONTINUE,
                    continuation_required=True,
                    yield_allowed=False,
                    allowed_stop_reasons=(),
                ).to_dict(),
                "runtime": {"build_id": "build-1"},
            }
        },
    }
    lease = HostRunLease.from_action(
        action,
        platform="codex",
        host_session_id="session-1",
    )
    store = HostRunLeaseStore(tmp_path)
    store.save(lease)

    restored = store.load()
    assert restored == lease
    decision = evaluate_stop(restored, host_session_id="session-1")
    assert decision is StopGuardDecision.BLOCK


def test_run_lease_binds_engine_build_from_current_runtime_revision() -> None:
    action = {
        "message_id": "action-current",
        "thread_id": "thread-current",
        "extensions": {
            "ae": {
                "execution_control": ExecutionControl(
                    schema_version="1.0",
                    disposition=ExecutionDisposition.CONTINUE,
                    continuation_required=True,
                    yield_allowed=False,
                    allowed_stop_reasons=(),
                ).to_dict(),
                "runtime_revision": {
                    "engine_build_id": "5.8.0-rc.5+sha256.current",
                },
            }
        },
    }

    lease = HostRunLease.from_action(
        action,
        platform="claude-code",
        host_session_id="session-current",
    )

    assert lease.build_id == "5.8.0-rc.5+sha256.current"


def test_stop_guard_does_not_block_other_session_or_terminal_action() -> None:
    continue_lease = HostRunLease(
        schema_version="1.0",
        thread_id="thread-1",
        action_message_id="action-1",
        platform="codex",
        host_session_id="session-1",
        build_id="build-1",
        disposition="CONTINUE",
        continuation_required=True,
        yield_allowed=False,
    )
    terminal_lease = HostRunLease(
        schema_version="1.0",
        thread_id="thread-1",
        action_message_id="action-2",
        platform="codex",
        host_session_id="session-1",
        build_id="build-1",
        disposition="TERMINAL",
        continuation_required=False,
        yield_allowed=True,
    )

    assert evaluate_stop(
        continue_lease,
        host_session_id="another-session",
    ) is StopGuardDecision.ALLOW
    assert evaluate_stop(
        terminal_lease,
        host_session_id="session-1",
    ) is StopGuardDecision.ALLOW


def test_host_session_id_uses_detected_platform_not_outer_host() -> None:
    environ = {
        "CODEX_THREAD_ID": "outer-codex",
        "CLAUDE_CODE_SESSION_ID": "current-claude",
    }

    assert host_session_id_from_environ(
        HostPlatform.CLAUDE_CODE,
        environ,
    ) == "current-claude"
    assert host_session_id_from_environ(
        HostPlatform.CODEX,
        environ,
    ) == "outer-codex"


def test_cli_host_mapping_persists_lease_for_current_session(
    tmp_path,
    monkeypatch,
) -> None:
    from auto_engineering.cli.dev_loop import _prepare_action_for_host

    monkeypatch.setenv("CODEX_THREAD_ID", "session-1")
    action = {
        "action": "developer",
        "message_id": "action-1",
        "thread_id": "thread-1",
        "extensions": {
            "ae": {
                "execution_control": ExecutionControl(
                    schema_version="1.0",
                    disposition=ExecutionDisposition.CONTINUE,
                    continuation_required=True,
                    yield_allowed=False,
                    allowed_stop_reasons=(),
                ).to_dict(),
            }
        },
    }

    mapped = _prepare_action_for_host(action, tmp_path)

    assert mapped["message_id"] == "action-1"
    lease = HostRunLeaseStore(tmp_path).load()
    assert lease is not None
    assert lease.action_message_id == "action-1"
    assert lease.host_session_id == "session-1"


def test_cli_lease_uses_inner_claude_identity_when_launched_from_codex(
    tmp_path,
    monkeypatch,
) -> None:
    from auto_engineering.cli.dev_loop import _prepare_action_for_host

    monkeypatch.setenv("CODEX_THREAD_ID", "outer-codex")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "/current/claude/plugin")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "inner-claude")
    action = {
        "action": "developer",
        "message_id": "nested-action",
        "thread_id": "nested-thread",
        "extensions": {
            "ae": {
                "execution_control": ExecutionControl(
                    schema_version="1.0",
                    disposition=ExecutionDisposition.CONTINUE,
                    continuation_required=True,
                    yield_allowed=False,
                    allowed_stop_reasons=(),
                ).to_dict(),
            }
        },
    }

    _prepare_action_for_host(action, tmp_path)

    lease = HostRunLeaseStore(tmp_path).load()
    assert lease is not None
    assert lease.platform == "claude-code"
    assert lease.host_session_id == "inner-claude"


def test_cli_recovery_projection_forbids_duplicate_worker_spawn(
    tmp_path,
    monkeypatch,
) -> None:
    from auto_engineering.cli.dev_loop import _prepare_action_for_host
    monkeypatch.setenv("CODEX_THREAD_ID", "recovery-session")
    action = {
        "schema_version": "1.1",
        "action": "architect",
        "stage": "architect",
        "message_id": "recovery-action",
        "thread_id": "recovery-thread",
        "tick": 7,
        "extensions": {"ae": {"execution_control": ExecutionControl(
            schema_version="1.0",
            disposition=ExecutionDisposition.CONTINUE,
            continuation_required=True,
            yield_allowed=False,
            allowed_stop_reasons=(),
        ).to_dict()}},
        "spawn": {
            "contract_version": "1.0",
            "count": 1,
            "effort": "xhigh",
            "parallel": False,
            "invocations": [{
                "worker_id": "architect-0",
                "role": "architect",
                "prompt_ref": ".ae-state/effects/architect.txt",
                "prompt_sha256": "a" * 64,
                "requested_effort": "xhigh",
                "isolation": "fresh_context",
                "capabilities": {
                    "may_drive_loop": False,
                    "may_spawn_workers": False,
                },
                "receipt_path": ".ae-state/spawn-proofs/architect.json",
            }],
        },
    }
    expected = {
        "schema_version": "1.1",
        "message_type": "result",
        "message_id": "existing-result",
        "causation_id": "recovery-action",
        "thread_id": "recovery-thread",
        "tick": 7,
        "stage": "architect",
        "plan": "existing",
    }
    journal = tmp_path / ".ae-state/host-runtime/outcomes/recovery-action.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({
        "schema_version": "1.0",
        "status": "committed",
        "action_message_id": "recovery-action",
        "result": expected,
    }))

    mapped = _prepare_action_for_host(action, tmp_path)

    recovery = mapped["host_execution"]["recovery"]
    assert recovery["status"] == "worker_outcomes_committed"
    assert recovery["spawn_permitted"] is False
    assert recovery["required_operation"] == "validate_then_submit_or_repair"
    assert "spawn" not in mapped
    assert "workers" not in mapped["host_execution"]
    assert "native_worker_tools" not in mapped["host_execution"]
    result_path = tmp_path / recovery["result_ref"]
    assert json.loads(result_path.read_text()) == expected
    outcomes_path = tmp_path / recovery["outcomes_ref"]
    assert json.loads(outcomes_path.read_text()) == {"outcomes": []}


def test_cli_recovery_finalizes_complete_native_files_before_respawn(
    tmp_path,
    monkeypatch,
) -> None:
    from auto_engineering.cli.dev_loop import _prepare_action_for_host

    monkeypatch.setenv("CODEX_THREAD_ID", "native-ready-session")
    action = {
        "schema_version": "1.1",
        "action": "component_verifier",
        "stage": "component_verifier",
        "message_id": "native-ready-action",
        "thread_id": "native-ready-thread",
        "tick": 5,
        "extensions": {"ae": {"execution_control": ExecutionControl(
            schema_version="1.0",
            disposition=ExecutionDisposition.CONTINUE,
            continuation_required=True,
            yield_allowed=False,
            allowed_stop_reasons=(),
        ).to_dict()}},
        "spawn": {
            "contract_version": "1.0",
            "count": 1,
            "effort": "high",
            "parallel": False,
            "invocations": [{
                "worker_id": "component_verifier-0",
                "role": "component_verifier",
                "prompt_ref": ".ae-state/effects/component.txt",
                "prompt_sha256": "b" * 64,
                "requested_effort": "high",
                "isolation": "fresh_context",
                "capabilities": {
                    "may_drive_loop": False,
                    "may_spawn_workers": False,
                },
                "receipt_path": ".ae-state/spawn-proofs/component.json",
            }],
        },
    }
    action_key = hashlib.sha256(
        action["message_id"].encode("utf-8")
    ).hexdigest()[:24]
    work = tmp_path / ".ae-state/host-runtime/work" / action_key
    work.mkdir(parents=True)
    (work / "outcomes.json").write_text(json.dumps({"outcomes": [{
        "worker_id": "component_verifier-0",
        "native_worker_handle": "agent-complete",
        "status": "completed",
        "payload": {"missing_count": 0, "diverged_count": 0},
        "summary": "核验完成",
        "actual_model": "unknown",
        "isolation_evidence": "fork_turns=none",
    }]}), encoding="utf-8")
    (work / "coordinator-result.json").write_text(json.dumps({
        "component": "Counter",
        "coverage_map": [],
        "missing_count": 0,
        "diverged_count": 0,
        "recheck_log": [],
    }), encoding="utf-8")

    mapped = _prepare_action_for_host(action, tmp_path)

    assert "spawn" not in mapped
    recovery = mapped["host_execution"]["recovery"]
    assert recovery["status"] == "native_outcomes_ready"
    assert recovery["spawn_permitted"] is False
    assert recovery["required_operation"] == "finalize_current_native_outcomes"
