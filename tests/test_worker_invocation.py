"""Phase 82 T436：宿主 Worker Invocation 与角色违规。"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

import pytest

from auto_engineering.host import HostPlatform
from auto_engineering.host.worker_invocation import (
    WorkerInvocationError,
    WorkerOutcomeError,
    compile_worker_invocation,
    validate_worker_outcome,
)


def _architect_action() -> dict[str, object]:
    prompt = "只输出架构计划"
    return {
        "action": "architect",
        "stage": "architect",
        "message_id": "action-1",
        "spawn": {
            "count": 1,
            "effort": "xhigh",
            "parallel": False,
            "contract_version": "1.0",
            "invocations": [{
                "worker_id": "architect-0",
                "role": "architect",
                "prompt_ref": ".ae-state/prompt-artifacts/architect.md",
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "requested_effort": "xhigh",
                "isolation": "fresh_context",
                "capabilities": {
                    "may_drive_loop": False,
                    "may_spawn_workers": False,
                },
                "receipt_path": ".ae-state/spawn-proofs/architect.json",
                "outcome_path": ".ae-state/host-runtime/worker-outcomes/architect.json",
            }],
        },
    }


def test_codex_worker_invocation_isolated_from_coordinator_history() -> None:
    invocation = compile_worker_invocation(
        _architect_action(),
        platform=HostPlatform.CODEX,
        prompt_loader=lambda _: "只输出架构计划",
    )

    assert invocation.action_message_id == "action-1"
    assert invocation.prompt == "只输出架构计划"
    assert invocation.reasoning_effort == "xhigh"
    assert invocation.fork_turns == "none"
    assert invocation.execution_identity["role"] == "worker"
    assert invocation.execution_identity["may_drive_loop"] is False
    assert invocation.execution_identity["may_spawn_workers"] is False


def test_worker_cannot_report_missing_coordinator_spawn_capability() -> None:
    with pytest.raises(WorkerOutcomeError, match="WORKER_ROLE_VIOLATION"):
        validate_worker_outcome({
            "spawned": False,
            "spawn_error_code": "HOST_CAPABILITY_UNAVAILABLE",
            "spawn_error": "collaboration.spawn_agent 未暴露",
        }, stage="architect")


def test_worker_preserves_real_task_capability_failure() -> None:
    outcome = validate_worker_outcome({
        "spawned": False,
        "spawn_error_code": "HOST_CAPABILITY_UNAVAILABLE",
        "spawn_error": "web_search 未暴露",
    }, stage="research")

    assert outcome["spawn_error"] == "web_search 未暴露"


def test_multi_worker_resolves_its_own_prompt_ref_and_hash() -> None:
    import hashlib

    prompt = "只审计架构边界"
    digest = hashlib.sha256(prompt.encode()).hexdigest()
    action = {
        "action": "plate_deep_audit",
        "stage": "plate_deep_audit",
        "message_id": "action-multi",
        "spawn": {
            "count": 2,
            "effort": "high",
            "parallel": True,
            "contract_version": "1.0",
            "invocations": [
                {
                    "worker_id": "plate_deep_audit-0",
                    "role": "architecture",
                    "prompt_ref": "artifact://worker-0",
                    "prompt_sha256": digest,
                    "requested_effort": "high",
                    "isolation": "fresh_context",
                    "capabilities": {
                        "may_drive_loop": False,
                        "may_spawn_workers": False,
                    },
                    "receipt_path": ".ae-state/spawn-proofs/worker-0.json",
                    "outcome_path": ".ae-state/host-runtime/worker-outcomes/worker-0.json",
                },
                {
                    "worker_id": "plate_deep_audit-1",
                    "role": "security",
                    "prompt_ref": "artifact://worker-1",
                    "prompt_sha256": "b" * 64,
                    "requested_effort": "high",
                    "isolation": "fresh_context",
                    "capabilities": {
                        "may_drive_loop": False,
                        "may_spawn_workers": False,
                    },
                    "receipt_path": ".ae-state/spawn-proofs/worker-1.json",
                    "outcome_path": ".ae-state/host-runtime/worker-outcomes/worker-1.json",
                },
            ],
        },
    }

    invocation = compile_worker_invocation(
        action,
        platform=HostPlatform.CODEX,
        worker_index=0,
        prompt_loader=lambda ref: prompt if ref == "artifact://worker-0" else "",
    )

    assert invocation.prompt == prompt
    assert invocation.worker_index == 0


def test_current_worker_compiler_rejects_legacy_agents_fallback() -> None:
    action = {
        "action": "architect",
        "stage": "architect",
        "message_id": "legacy-action",
        "spawn": {
            "count": 1,
            "effort": "high",
            "parallel": False,
            "agents": [{
                "prompt_ref": "artifact://legacy-worker",
                "prompt_hash": "a" * 64,
            }],
        },
    }

    with pytest.raises(
        WorkerInvocationError, match="WORKER_INVOCATION_CONTRACT_REQUIRED"
    ):
        compile_worker_invocation(
            action,
            platform=HostPlatform.CODEX,
            prompt_loader=lambda _: "旧 Worker 提示词",
        )


def test_current_worker_compiler_requires_prompt_artifact_loader() -> None:
    with pytest.raises(
        WorkerInvocationError, match="WORKER_PROMPT_LOADER_REQUIRED"
    ):
        compile_worker_invocation(
            _architect_action(),
            platform=HostPlatform.CODEX,
        )


def test_worker_prompt_reference_cannot_escape_project_root_via_symlink(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "prompt.md").write_text("只输出架构计划", encoding="utf-8")
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    action = deepcopy(_architect_action())
    action["project_root"] = str(tmp_path)
    action["spawn"]["invocations"][0]["prompt_ref"] = "link/prompt.md"  # type: ignore[index]

    with pytest.raises(WorkerInvocationError, match="WORKER_PROMPT_PATH_OUTSIDE_ROOT"):
        compile_worker_invocation(
            action,
            platform=HostPlatform.CODEX,
            project_root=tmp_path,
            prompt_loader=lambda _: "只输出架构计划",
        )


def test_worker_business_result_cannot_override_runtime_identity() -> None:
    with pytest.raises(WorkerOutcomeError, match="WORKER_RUNTIME_IDENTITY_FORBIDDEN"):
        validate_worker_outcome({
            "execution_identity": {
                "role": "coordinator",
                "stage": "architect",
                "may_drive_loop": True,
                "may_spawn_workers": True,
                "inherit_parent_context": True,
            },
            "plan": "bad",
        }, stage="architect")


def test_worker_business_result_cannot_drive_loop_or_spawn_agents() -> None:
    for forbidden in ({"may_drive_loop": True}, {"may_spawn_workers": True}, {"agents": []}):
        with pytest.raises(WorkerOutcomeError, match="WORKER_ROLE_VIOLATION"):
            validate_worker_outcome(forbidden, stage="developer")
