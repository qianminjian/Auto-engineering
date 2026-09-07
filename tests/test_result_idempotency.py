"""Protocol Envelope v1.1 Result 因果与幂等契约。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from auto_engineering.engine.state import EngineState
from auto_engineering.host import HostPlatform
from auto_engineering.host.spawn_contract import SpawnPlan
from auto_engineering.host.worker_attestation import WorkerAttestation
from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.protocol import payload_digest
from auto_engineering.loop.tick_orchestrator import TickOrchestrator

_VALID_PLAN = (
    "实现组件，包含完整的 TDD Red-Green-Refactor 循环和 Gate 验证，"
    "确保协议身份、状态推进与恢复路径均可验证。"
)


def _pass_gate_runner(gate_names, project_root):
    return {name: MagicMock(passed=True, message="ok") for name in gate_names}


def _pass_guardrail():
    guardrail = MagicMock()
    guardrail.check.return_value = MagicMock(action="pass")
    return guardrail


def _orchestrator() -> TickOrchestrator:
    return TickOrchestrator(
        gate_runner=_pass_gate_runner,
        guardrail=_pass_guardrail(),
        checkpoint_store=None,
    )


def _architect_result(action: dict, **overrides) -> dict:
    plan = SpawnPlan.from_action(action)
    attestations = [
        WorkerAttestation.completed(
            platform=HostPlatform.CODEX,
            action_message_id=action["message_id"],
            invocation=invocation,
            effective_effort=invocation.requested_effort,
            isolation_evidence="fork_turns=none",
            visible_capabilities=tuple(sorted(invocation.capabilities)),
            actual_model="test-model",
        ).to_dict()
        for invocation in plan.invocations
    ]
    result = {
        "schema_version": "1.1",
        "message_type": "result",
        "message_id": "result-architect-1",
        "thread_id": action["thread_id"],
        "tick": action["tick"],
        "stage": "architect",
        "causation_id": action["message_id"],
        "correlation_id": action["correlation_id"],
        "extensions": {},
        "spawned": True,
        "spawn_proof_token": action["spawn_proof_token"],
        "worker_attestations": attestations,
        "plan": _VALID_PLAN,
        "batch_plan": [
            {
                "batch_id": "b1",
                "component": "protocol",
                "tasks": [
                    {
                        "id": "T1",
                        "description": "实现协议",
                        "file_targets": ["auto_engineering/loop/protocol.py"],
                    }
                ],
            }
        ],
        "file_list": ["auto_engineering/loop/protocol.py"],
        "contracts": {},
    }
    result.update(overrides)
    return result


def _complete_spawn_proof(orchestrator: TickOrchestrator, action: dict) -> None:
    proof_path = (
        orchestrator.project_root / ".ae-state" / "spawn-proofs"
        / f"{action['spawn_proof_token']}.json"
    )
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["status"] = "completed"
    proof["completed_at"] = "2026-08-01T00:00:00Z"
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    for spec in SpawnPlan.from_action(action).invocations:
        receipt_path = orchestrator.project_root / spec.receipt_path
        receipt_path.write_text(json.dumps({
            "status": "completed", "stage": action["stage"],
            "worker": spec.worker_id,
            "native_worker_handle": f"test-{spec.worker_id}",
            "requested_effort": spec.requested_effort,
            "actual_model": "test-model",
        }), encoding="utf-8")


def test_duplicate_result_returns_same_action_without_advancing_state() -> None:
    orchestrator = _orchestrator()
    action = orchestrator.init("实现协议")
    _complete_spawn_proof(orchestrator, action)
    result = _architect_result(action)

    first = orchestrator.tick_dict(result)
    state_after_first = orchestrator._state.to_dict()
    second = orchestrator.tick_dict(result)

    assert second == first
    assert orchestrator._state.to_dict() == state_after_first


def test_same_causation_with_different_payload_is_conflict() -> None:
    orchestrator = _orchestrator()
    action = orchestrator.init("实现协议")
    _complete_spawn_proof(orchestrator, action)
    result = _architect_result(action)
    orchestrator.tick_dict(result)

    conflict = orchestrator.tick_dict(
        _architect_result(action, plan=f"{_VALID_PLAN} 不同内容")
    )

    assert conflict["action"] == "error"
    assert conflict["error_code"] == "RESULT_CONFLICT"


def test_unknown_causation_is_not_active() -> None:
    orchestrator = _orchestrator()
    action = orchestrator.init("实现协议")

    response = orchestrator.tick_dict(
        _architect_result(action, causation_id="unknown-action")
    )

    assert response["action"] == "error"
    assert response["error_code"] == "ACTION_NOT_ACTIVE"


def test_result_for_different_thread_is_not_active() -> None:
    orchestrator = _orchestrator()
    action = orchestrator.init("实现协议")

    response = orchestrator.tick_dict(
        _architect_result(action, thread_id="different-thread")
    )

    assert response["action"] == "error"
    assert response["error_code"] == "ACTION_NOT_ACTIVE"


def test_duplicate_result_replays_across_process_restore(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    (tmp_path / "demo").mkdir()
    db_path = tmp_path / "checkpoints.db"
    first_store = SQLiteCheckpointStore[EngineState](db_path)
    first = TickOrchestrator(
        tmp_path,
        gate_runner=_pass_gate_runner,
        guardrail=_pass_guardrail(),
        checkpoint_store=first_store,
    )
    action = first.init("实现协议")
    _complete_spawn_proof(first, action)
    result = _architect_result(action)
    expected = first.tick_dict(result)
    first_store.close()

    second_store = SQLiteCheckpointStore[EngineState](db_path)
    try:
        restored = TickOrchestrator.restore_from_checkpoint(
            tmp_path,
            second_store,
            gate_runner=_pass_gate_runner,
            guardrail=_pass_guardrail(),
        )
        state_before = restored._state.to_dict()

        replay = restored.tick_dict(result)

        assert replay == expected
        assert restored._state.to_dict() == state_before
    finally:
        second_store.close()


def test_event_store_does_not_replay_checkpoint_only_result(tmp_path) -> None:
    """EventStore 运行中不能从 checkpoint 的旧 replay 表偷偷恢复。"""

    (tmp_path / "pyproject.toml").write_text("[project]\nname='event-only'\n")
    (tmp_path / "src").mkdir()
    checkpoints = SQLiteCheckpointStore[EngineState](tmp_path / "checkpoints.db")
    with SQLiteEventStore(tmp_path / "events.db") as events:
        orchestrator = TickOrchestrator(
            tmp_path,
            gate_runner=_pass_gate_runner,
            guardrail=_pass_guardrail(),
            checkpoint_store=checkpoints,
            event_store=events,
        )
        action = orchestrator.init("验证 EventStore 事实源")
        _complete_spawn_proof(orchestrator, action)
        result = _architect_result(action)
        checkpoints.record_protocol_action(action)
        checkpoints.record_protocol_result(
            action["thread_id"],
            action["message_id"],
            payload_digest(result),
            {"action": "checkpoint-only-replay"},
        )

        response = orchestrator.tick_dict(result)

        assert response["action"] != "checkpoint-only-replay"
        assert response["action"] == "developer"
        assert events.load_protocol_result(
            action["thread_id"], action["message_id"]
        ) is not None
    checkpoints.close()
