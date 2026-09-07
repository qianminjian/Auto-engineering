"""Phase 82 T438：可执行 Host Runtime 仿真。"""

from __future__ import annotations

import hashlib

import pytest

from auto_engineering.host import HostPlatform
from auto_engineering.host.worker_invocation import WorkerOutcomeError
from tests.host_runtime.fake_host import AgentCapacityError, FakeHostRuntime


def _action() -> dict[str, object]:
    prompt = "输出 batch_plan"
    return {
        "action": "architect",
        "stage": "architect",
        "message_id": "architect-action-1",
        "worker_prompt": prompt,
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


def test_fake_host_executes_isolated_worker_without_loop_reentry() -> None:
    host = FakeHostRuntime(HostPlatform.CODEX)

    def worker(invocation):
        assert invocation.fork_turns == "none"
        assert invocation.execution_identity["may_drive_loop"] is False
        assert invocation.execution_identity["may_spawn_workers"] is False
        return {"plan": "按原设计实现", "batch_plan": []}

    execution = host.execute(_action(), worker)

    assert execution.result["spawned"] is True
    assert execution.receipt["status"] == "completed"
    assert execution.receipt["action_message_id"] == "architect-action-1"
    assert execution.attempts == 1


def test_fake_host_reclaims_capacity_and_retries_same_action_once() -> None:
    host = FakeHostRuntime(HostPlatform.CODEX)
    calls = 0

    def worker(invocation):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AgentCapacityError("agent thread limit reached")
        return {"plan": "恢复后完成", "batch_plan": []}

    execution = host.execute(_action(), worker)

    assert execution.attempts == 2
    assert host.reclaimed_count == 1
    assert execution.receipt["action_message_id"] == "architect-action-1"


def test_fake_host_rejects_worker_that_checks_coordinator_capability() -> None:
    host = FakeHostRuntime(HostPlatform.CODEX)

    with pytest.raises(WorkerOutcomeError, match="WORKER_ROLE_VIOLATION"):
        host.execute(_action(), lambda invocation: {
            "spawned": False,
            "spawn_error_code": "HOST_CAPABILITY_UNAVAILABLE",
            "spawn_error": "collaboration.spawn_agent 未暴露",
        })

    assert host.receipts == []
