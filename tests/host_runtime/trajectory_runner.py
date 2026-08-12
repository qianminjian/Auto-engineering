"""使用生产 SpawnPlan 的完整 Host 生命周期测试运行器。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from auto_engineering.host import HostPlatform
from auto_engineering.host.spawn_contract import SpawnPlan, WorkerOutcome
from auto_engineering.host.worker_attestation import WorkerAttestation
from auto_engineering.host.worker_invocation import (
    WorkerInvocation,
    compile_worker_invocation,
)
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.tick_orchestrator import TickOrchestrator


class HostTrajectoryError(RuntimeError):
    """宿主轨迹未完成必要生命周期。"""


@dataclass(frozen=True, slots=True)
class HostTrajectory:
    result: dict[str, Any]
    next_action: dict[str, Any]
    events: tuple[str, ...]


class HostTrajectoryRunner:
    """经生产 Core/EventStore 执行完整因果轨迹。"""

    def __init__(
        self,
        project_root: Path,
        platform: HostPlatform,
        *,
        core: TickOrchestrator,
        event_store: SQLiteEventStore,
    ) -> None:
        self.project_root = project_root
        self.platform = platform
        self.core = core
        self.event_store = event_store

    def _load_prompt(self, ref: str) -> str:
        return (self.project_root / ref).read_text(encoding="utf-8")

    def submit_host_failure(
        self,
        action: Mapping[str, Any],
        *,
        error_code: str,
        message: str,
    ) -> dict[str, Any]:
        active = self.event_store.load_action_snapshot(str(action.get("thread_id", "")))
        if active is None or active.get("message_id") != action.get("message_id"):
            raise HostTrajectoryError("CORE_ACTIVE_ACTION_REQUIRED")
        result = {
            "schema_version": "1.1", "message_type": "result",
            "message_id": f"failure-{error_code}-{action.get('message_id')}",
            "thread_id": action.get("thread_id"), "tick": action.get("tick"),
            "stage": action.get("stage"), "causation_id": action.get("message_id"),
            "correlation_id": action.get("correlation_id"), "extensions": {},
            "spawned": False, "spawn_error_code": error_code,
            "spawn_error": message,
        }
        return dict(self.core.tick_dict(result))

    def run(
        self,
        action: Mapping[str, Any],
        *,
        workers: Sequence[Callable[[WorkerInvocation], Mapping[str, Any]]],
        fail_after_receipt: bool = False,
    ) -> HostTrajectory:
        active = self.event_store.load_action_snapshot(str(action.get("thread_id", "")))
        if active is None or active.get("message_id") != action.get("message_id"):
            raise HostTrajectoryError("CORE_ACTIVE_ACTION_REQUIRED")
        plan = SpawnPlan.from_action(action)
        if len(workers) != len(plan.invocations):
            raise HostTrajectoryError("WORKER_COUNT_MISMATCH")

        events = ["action_received"]
        outcomes: list[WorkerOutcome] = []
        attestations: list[WorkerAttestation] = []
        for index, (spec, worker) in enumerate(zip(plan.invocations, workers, strict=True)):
            invocation = compile_worker_invocation(
                action,
                platform=self.platform,
                worker_index=index,
                prompt_loader=self._load_prompt,
            )
            events.append("worker_invoked")
            outcome = WorkerOutcome.from_dict(worker(invocation))
            outcomes.append(outcome)
            isolation = (
                "fork_turns=none"
                if self.platform is HostPlatform.CODEX
                else "fresh_context"
            )
            attestation = WorkerAttestation.completed(
                platform=self.platform,
                action_message_id=invocation.action_message_id,
                invocation=spec,
                effective_effort=spec.requested_effort,
                isolation_evidence=isolation,
                visible_capabilities=tuple(sorted(spec.capabilities)),
                actual_model="fake-host-model",
            )
            attestation.validate(
                action_message_id=invocation.action_message_id,
                invocation=spec,
            )
            attestations.append(attestation)
            receipt_path = self.project_root / spec.receipt_path
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(json.dumps({
                "status": "completed",
                "stage": action.get("stage"),
                "completed_at": datetime.now(UTC).isoformat(),
                "requested_effort": spec.requested_effort,
                "actual_model": attestation.actual_model,
                "attestation": attestation.to_dict(),
            }, ensure_ascii=False), encoding="utf-8")
            events.append("attestation_recorded")

        if fail_after_receipt:
            raise HostTrajectoryError("FAULT_AFTER_RECEIPT")

        merged: dict[str, Any] = {}
        for outcome in outcomes:
            merged.update(outcome.payload)
        total_token = action.get("spawn_proof_token")
        if not isinstance(total_token, str) or not total_token:
            raise HostTrajectoryError("TOTAL_PROOF_TOKEN_MISSING")
        total_path = self.project_root / ".ae-state" / "spawn-proofs" / f"{total_token}.json"
        total_path.write_text(json.dumps({
            "status": "completed",
            "token": total_token,
            "stage": action.get("stage"),
            "completed_at": datetime.now(UTC).isoformat(),
        }), encoding="utf-8")
        events.append("proof_completed")

        result = {
            **merged,
            "schema_version": "1.1",
            "message_type": "result",
            "message_id": f"result-{action.get('message_id')}",
            "thread_id": action.get("thread_id"),
            "tick": action.get("tick"),
            "stage": action.get("stage"),
            "causation_id": action.get("message_id"),
            "correlation_id": action.get("correlation_id"),
            "extensions": {},
            "spawned": True,
            "spawn_proof_token": total_token,
            "worker_attestations": [item.to_dict() for item in attestations],
        }
        next_action = self.core.tick_dict(result)
        stream = self.event_store.load_stream(str(action.get("thread_id")))
        event_names = tuple(event.event_type.value for event in stream)
        if "ResultAccepted" not in event_names or "ActionIssued" not in event_names:
            raise HostTrajectoryError("CORE_CAUSAL_CHAIN_INCOMPLETE")
        events.extend(("result_submitted", *event_names, "next_action_received"))
        return HostTrajectory(result, dict(next_action), tuple(events))


__all__ = ["HostTrajectory", "HostTrajectoryError", "HostTrajectoryRunner"]
