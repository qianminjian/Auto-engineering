"""宿主 Worker 等待/所有权观察合同的 TDD 回归。"""

from __future__ import annotations

from pathlib import Path

import pytest


def _spawn_action(tmp_path: Path) -> dict[str, object]:
    return {
        "action": "critic",
        "stage": "critic",
        "message_id": "observation-action",
        "thread_id": "observation-thread",
        "tick": 1,
        "project_root": str(tmp_path),
        "spawn": {
            "contract_version": "1.0",
            "count": 1,
            "effort": "high",
            "parallel": False,
            "invocations": [{
                "worker_id": "critic-0",
                "role": "critic",
                "prompt_ref": ".ae-state/effects/prompt/critic.txt",
                "prompt_sha256": "a" * 64,
                "requested_effort": "high",
                "isolation": "fresh_context",
                "capabilities": {
                    "may_drive_loop": False,
                    "may_spawn_workers": False,
                },
                "receipt_path": ".ae-state/spawn-proofs/critic.json",
                "outcome_path": (
                    ".ae-state/host-runtime/worker-outcomes/critic.json"
                ),
            }],
        },
    }


@pytest.mark.parametrize(
    ("platform_name", "mode", "wait_timeout_ms", "max_waits", "heartbeat"),
    [
        ("CODEX", "native_wait", 300_000, 3, [300_000, 600_000, 900_000]),
        ("CLAUDE_CODE", "synchronous_return", 0, 0, []),
    ],
)
def test_spawn_action_exposes_one_machine_observation_policy(
    tmp_path: Path,
    platform_name: str,
    mode: str,
    wait_timeout_ms: int,
    max_waits: int,
    heartbeat: list[int],
) -> None:
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.adapters import adapter_for

    adapter = adapter_for(HostPlatform[platform_name])
    profile = adapter.profile(
        detected=adapter.capabilities,
        authorized=adapter.capabilities,
    )

    mapped = adapter.map_action(_spawn_action(tmp_path), profile=profile).payload
    assert mapped["host_execution"]["worker_observation"] == {
        "schema_version": "1.0",
        "mode": mode,
        "wait_timeout_ms": wait_timeout_ms,
        "max_waits": max_waits,
        "heartbeat_intervals_ms": heartbeat,
        "after_waits": (
            "probe_owner_then_interrupt" if mode == "native_wait"
            else "native_return"
        ),
        "unknown_owner_disposition": (
            "WAIT_RESOURCE/WORKER_OWNERSHIP_UNCERTAIN"
        ),
        "terminal_statuses": ["completed", "failed", "cancelled", "timed_out"],
    }


def test_observation_policy_rejects_changed_wait_budget() -> None:
    from auto_engineering.host.worker_observation import (
        WorkerObservationContract,
        WorkerObservationContractError,
    )

    with pytest.raises(
        WorkerObservationContractError,
        match="WORKER_OBSERVATION_CONTRACT_INVALID",
    ):
        WorkerObservationContract.from_dict({
            "schema_version": "1.0",
            "mode": "native_wait",
            "wait_timeout_ms": 30_000,
            "max_waits": 3,
            "heartbeat_intervals_ms": [30_000, 60_000, 90_000],
            "after_waits": "probe_owner_then_interrupt",
            "unknown_owner_disposition": (
                "WAIT_RESOURCE/WORKER_OWNERSHIP_UNCERTAIN"
            ),
            "terminal_statuses": [
                "completed", "failed", "cancelled", "timed_out"
            ],
        })


def test_compact_action_keeps_observation_policy(tmp_path: Path) -> None:
    from auto_engineering.cli.dev_loop import _compact_host_action
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.adapters import adapter_for

    adapter = adapter_for(HostPlatform.CODEX)
    profile = adapter.profile(
        detected=adapter.capabilities,
        authorized=adapter.capabilities,
    )
    mapped = adapter.map_action(_spawn_action(tmp_path), profile=profile).payload

    compact = _compact_host_action(mapped, tmp_path)
    assert compact["host_execution"]["worker_observation"] == (
        mapped["host_execution"]["worker_observation"]
    )


def test_observation_record_is_bound_to_worker_generation_and_fence(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.worker_observation import (
        WorkerObservationRecord,
        observation_path_for,
    )
    from auto_engineering.host.worker_observation_store import WorkerObservationStore

    record = WorkerObservationRecord(
        schema_version="1.0",
        action_message_id="observation-action",
        worker_id="critic-0",
        execution_generation=2,
        fencing_token="b" * 64,
        observed_at="2026-09-02T09:00:00+00:00",
        native_status="unknown",
        wait_attempt=3,
        owner_known=False,
        native_worker_handle="native-critic-0",
    )
    path = observation_path_for(tmp_path, record)
    WorkerObservationStore(tmp_path).save(record)

    assert path == (
        tmp_path / ".ae-state/host-runtime/worker-observations"
        / "observation-action-critic-0-g2.json"
    )
    assert WorkerObservationStore(tmp_path).load(record) == record


def test_observation_record_rejects_unknown_owner_with_completed_status() -> None:
    from auto_engineering.host.worker_observation import (
        WorkerObservationContractError,
        WorkerObservationRecord,
    )

    record = WorkerObservationRecord(
        schema_version="1.0",
        action_message_id="observation-action",
        worker_id="critic-0",
        execution_generation=1,
        fencing_token="c" * 64,
        observed_at="2026-09-02T09:00:00+00:00",
        native_status="completed",
        wait_attempt=0,
        owner_known=False,
        native_worker_handle=None,
    )
    with pytest.raises(
        WorkerObservationContractError,
        match="WORKER_OBSERVATION_RECORD_INVALID",
    ):
        record.validate()
