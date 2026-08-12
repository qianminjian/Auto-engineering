"""Phase 82 T436：宿主 Worker Invocation 与角色违规。"""

from __future__ import annotations

import pytest

from auto_engineering.host import HostPlatform
from auto_engineering.host.worker_invocation import (
    WorkerOutcomeError,
    compile_worker_invocation,
    validate_worker_outcome,
)


def _architect_action() -> dict[str, object]:
    return {
        "action": "architect",
        "stage": "architect",
        "message_id": "action-1",
        "subagent_prompt": "只输出架构计划",
        "spawn": {"count": 1, "effort": "xhigh", "parallel": False},
    }


def test_codex_worker_invocation_isolated_from_coordinator_history() -> None:
    invocation = compile_worker_invocation(
        _architect_action(), platform=HostPlatform.CODEX,
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
        "subagent_prompt": "Coordinator 合并 Prompt",
        "spawn": {
            "count": 2,
            "effort": "high",
            "parallel": True,
            "agents": [
                {"prompt_ref": "artifact://worker-0", "prompt_hash": digest},
                {"prompt_ref": "artifact://worker-1", "prompt_hash": "b" * 64},
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
