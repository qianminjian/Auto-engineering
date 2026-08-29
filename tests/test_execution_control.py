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
from auto_engineering.loop.design_authority import DesignChangeRequest
from auto_engineering.loop.execution_control import (
    ExecutionControl,
    ExecutionControlError,
    ExecutionDisposition,
    control_for_action,
    project_execution_control,
)
from auto_engineering.loop.protocol import (
    ProtocolValidationError,
    action_envelope,
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


@pytest.mark.parametrize("gate_id,gate_type", [
    ("gate-1", "decision"),
    ("gate-1", "agent_escalation"),
    ("state_reconciliation", "decision"),
    ("gate-1", "stage_checkpoint"),
    ("gate-1", "manual"),
    ("gate-1", "user"),
])
def test_all_user_interactive_gate_types_wait_for_user(
    gate_id: str,
    gate_type: str,
) -> None:
    """任何真实用户 Gate 都不能被宿主误当作可自动执行 Action。"""
    action = {"action": "gate", "gate": {"id": gate_id, "type": gate_type}}

    control = control_for_action(action)

    assert control.disposition is ExecutionDisposition.WAIT_USER
    assert control.reason_code


def test_design_change_gate_envelope_waits_before_host_compilation() -> None:
    request = DesignChangeRequest.from_dict({
        "source": "research",
        "source_ref": "gap-001",
        "requested_authority": "binding",
        "change_summary": "补充一项需要用户批准的设计约束",
        "affected_design_refs": ["§10.1"],
    })

    action = action_envelope(
        {
            "action": "gate",
            "thread_id": "thread-1",
            "tick": 1,
            "stage": "architect",
            "gate": request.to_gate(),
        }
    )

    control = action["extensions"]["ae"]["execution_control"]
    assert control["disposition"] == "WAIT_USER"
    assert control["reason_code"] == "DESIGN_CHANGE_APPROVAL_REQUIRED"


def test_legacy_gate_snapshot_is_safely_projected_as_wait_user() -> None:
    legacy = {
        "action": "gate",
        "gate": {
            "id": "design_change:change-1",
            "type": "decision",
            "reason_code": "DESIGN_CHANGE_APPROVAL_REQUIRED",
        },
        "extensions": {
            "ae": {
                "execution_control": {
                    "schema_version": "1.0",
                    "disposition": "CONTINUE",
                    "continuation_required": True,
                    "yield_allowed": False,
                    "allowed_stop_reasons": [],
                }
            }
        },
    }

    projected = project_execution_control(legacy)

    assert (
        projected["extensions"]["ae"]["execution_control"]["disposition"]
        == "WAIT_USER"
    )
    assert projected["extensions"]["ae"]["execution_control"]["reason_code"] == (
        "DESIGN_CHANGE_APPROVAL_REQUIRED"
    )
    # Safety projection must not mutate the persisted legacy object.
    assert legacy["extensions"]["ae"]["execution_control"]["disposition"] == (
        "CONTINUE"
    )


def test_new_action_rejects_execution_control_semantic_drift() -> None:
    with pytest.raises(ProtocolValidationError, match="execution_control"):
        action_envelope({
            "action": "gate",
            "thread_id": "thread-1",
            "tick": 1,
            "stage": "architect",
            "gate": {"id": "gate-1", "type": "decision"},
            "extensions": {
                "ae": {
                    "execution_control": {
                        "schema_version": "1.0",
                        "disposition": "CONTINUE",
                        "continuation_required": True,
                        "yield_allowed": False,
                        "allowed_stop_reasons": [],
                    }
                }
            },
        })


def test_unknown_gate_type_fails_closed_instead_of_continuing() -> None:
    control = control_for_action({
        "action": "gate",
        "gate": {"id": "future-gate", "type": "future_interaction"},
    })

    assert control.disposition is ExecutionDisposition.ERROR
    assert control.reason_code == "UNKNOWN_GATE_TYPE"


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


def test_compact_host_view_uses_prompt_ref_without_inlining_action_context(
    tmp_path,
    monkeypatch,
) -> None:
    from auto_engineering.cli.dev_loop import _prepare_action_for_host

    monkeypatch.setenv("CODEX_THREAD_ID", "compact-session")
    monkeypatch.setenv("AE_HOST_ACTION_VIEW", "compact")
    instruction = "developer instruction with bounded current context"
    action = {
        "schema_version": "1.1",
        "message_type": "action",
        "action": "developer",
        "stage": "developer",
        "message_id": "compact-action",
        "thread_id": "compact-thread",
        "tick": 3,
        "project_root": str(tmp_path),
        "instruction": instruction,
        "subagent_prompt": "duplicated worker prompt body",
        "context": {"large": "context body must not reach stdout"},
        "tasks": [{"id": "T1", "description": "large task body"}],
        "expected_format": {"files_changed": "[string]"},
        "result_contract": {
            "schema_version": "1.0",
            "required": ["files_changed"],
            "properties": {"files_changed": {"type": "array"}},
            "additionalProperties": False,
        },
        "extensions": {
            "ae": {
                "execution_control": ExecutionControl(
                    schema_version="1.0",
                    disposition=ExecutionDisposition.CONTINUE,
                    continuation_required=True,
                    yield_allowed=False,
                    allowed_stop_reasons=(),
                ).to_dict(),
                "runtime_revision": {"engine_build_id": "build-1"},
            }
        },
    }

    compact = _prepare_action_for_host(action, tmp_path)

    assert compact["view"] == "compact"
    assert compact["action"] == "developer"
    assert compact["message_id"] == "compact-action"
    assert compact["extensions"] == action["extensions"]
    assert compact["expected_format"] == action["expected_format"]
    assert compact["result_contract"] == action["result_contract"]
    assert "instruction" not in compact
    assert "subagent_prompt" not in compact
    assert "context" not in compact
    assert "tasks" not in compact
    prompt_ref = compact["coordinator_prompt_ref"]
    prompt_path = tmp_path / prompt_ref["path"]
    assert prompt_path.read_text(encoding="utf-8") == instruction
    assert prompt_ref["sha256"] == hashlib.sha256(
        instruction.encode("utf-8")
    ).hexdigest()
    assert action["instruction"] == instruction
    assert action["context"] == {"large": "context body must not reach stdout"}


@pytest.mark.parametrize(
    ("action_name", "control_fields"),
    [
        (
            "gap_review",
            {
                "current_gap_index": 1,
                "total_gaps": 2,
                "auto_decision": {"gap_id": "gap-2", "resolution": "Fill"},
                "gap_scan_summary": {
                    "design_doc_digest": "sha256:" + "a" * 64,
                    "scanned_sections": 14,
                    "gap_count": 2,
                    "has_blocking": True,
                    "outcome": "user_decision_required",
                },
            },
        ),
        (
            "project_setup_required",
            {
                "reason_code": "PROJECT_SETUP_REQUIRED",
                "missing_capabilities": ["source_roots"],
                "constraints": {"source_roots": ["src"]},
            },
        ),
        (
            "resource_wait",
            {
                "resource": "native_worker",
                "retry_stage": "architect",
                "reason_code": "HOST_AGENT_CAPACITY",
                "retry_attempt": 1,
                "retry_limit": 2,
            },
        ),
        (
            "session_rollover",
            {
                "reason": "context_compaction_failed",
                "current_session_id": "session-old",
                "capsule": {"artifact_id": "capsule-1", "sha256": "a" * 64},
                "claim_token": "claim-1",
                "expires_at": None,
            },
        ),
    ],
)
def test_compact_host_view_preserves_action_specific_control_fields(
    tmp_path,
    action_name,
    control_fields,
) -> None:
    from auto_engineering.cli.dev_loop import _compact_host_action

    action = {
        "action": action_name,
        "message_id": f"{action_name}-action",
        "thread_id": "thread-1",
        **control_fields,
    }

    compact = _compact_host_action(action, tmp_path)

    for key, value in control_fields.items():
        assert compact[key] == value


def test_compact_host_view_projects_only_runtime_control_and_native_launcher(
    tmp_path,
) -> None:
    from auto_engineering.cli.dev_loop import _compact_host_action

    action = {
        "action": "architect",
        "message_id": "compact-spawn-action",
        "thread_id": "thread-1",
        "valid_plate_keys": ["counter"],
        "extensions": {
            "context_manifest": {"blocks": [{"id": "large-context"}]},
            "policy_snapshot": {"max_workers_per_thread": 50},
            "ae": {
                "execution_control": {"disposition": "CONTINUE"},
                "runtime_revision": {"engine_build_id": "build-1"},
                "issued_at": "not-required-by-host",
            },
        },
        "host_execution": {
            "schema_version": "1.0",
            "platform": "codex",
            "action_message_id": "compact-spawn-action",
            "work_files": {"outcomes": "outcomes.json"},
            "native_worker_tools": {"selection": "first"},
            "workers": [{
                "worker_id": "architect-0",
                "native_launch_prompt": "bounded-launcher",
                "expected_isolation_evidence": "fork_turns=none",
                "receipt": {"large": "duplicate"},
                    "attestation": {"large": "duplicate"},
                    "prompt_ref": "prompt.txt",
                    "prompt_sha256": "a" * 64,
            }],
        },
    }

    compact = _compact_host_action(action, tmp_path)

    assert compact["extensions"] == {"ae": {
        "execution_control": {"disposition": "CONTINUE"},
        "runtime_revision": {"engine_build_id": "build-1"},
    }}
    assert compact["host_execution"]["workers"] == [{
            "worker_id": "architect-0",
            "prompt_ref": "prompt.txt",
            "prompt_sha256": "a" * 64,
            "native_launch_prompt": "bounded-launcher",
        "expected_isolation_evidence": "fork_turns=none",
    }]
    assert compact["host_execution"]["work_files"] == {"outcomes": "outcomes.json"}
    assert compact["valid_plate_keys"] == ["counter"]


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
        "project_root": str(tmp_path),
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


def test_cli_result_repair_restores_rejected_outcomes_and_keeps_repair_mode(
    tmp_path,
    monkeypatch,
) -> None:
    from auto_engineering.cli.dev_loop import _prepare_action_for_host

    monkeypatch.setenv("CODEX_THREAD_ID", "result-repair-session")
    action = {
        "schema_version": "1.1",
        "action": "architect",
        "stage": "architect",
        "message_id": "result-repair-action",
        "thread_id": "result-repair-thread",
        "tick": 8,
        "project_root": str(tmp_path),
        "result_rejection": {
            "repair_required": True,
            "error_code": "ACTION_EXECUTION_ACTION_INVALID",
            "violations": ["RESULT_FIELD_MISSING"],
        },
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
    action_key = hashlib.sha256(action["message_id"].encode()).hexdigest()[:24]
    work = tmp_path / ".ae-state/host-runtime/work" / action_key
    work.mkdir(parents=True)
    original = {
        "worker_id": "architect-0",
        "native_worker_handle": "agent-original",
        "status": "completed",
        "payload": {"plan": "original"},
        "summary": "完成",
        "actual_model": "gpt-5.6-sol",
        "isolation_evidence": "fork_context=false",
    }
    (work / "coordinator-result.json").write_text(
        json.dumps({"plan": "stale"}), encoding="utf-8"
    )
    journal = tmp_path / ".ae-state/host-runtime/outcomes" / f"{action['message_id']}.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({
        "schema_version": "1.1",
        "status": "rejected",
        "action_message_id": action["message_id"],
        "outcomes": [original],
    }))

    mapped = _prepare_action_for_host(action, tmp_path)

    recovery = mapped["host_execution"]["recovery"]
    assert recovery["status"] == "result_repair_worker_reuse"
    assert "workers" not in mapped["host_execution"]
    assert "只修复 Coordinator" in mapped["instruction"]
    assert json.loads((work / "outcomes.json").read_text()) == {
        "outcomes": [original]
    }


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
        "project_root": str(tmp_path),
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
