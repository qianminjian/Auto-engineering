"""使用生产 SpawnPlan 的完整 Host 生命周期测试运行器。"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from auto_engineering.host import HostPlatform
from auto_engineering.host.adapters import adapter_for
from auto_engineering.host.execution_assembler import (
    HostExecutionAssembler,
    NativeWorkerOutcome,
)
from auto_engineering.host.outcome_journal import OutcomeJournal
from auto_engineering.host.spawn_contract import SpawnPlan, WorkerOutcome
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
        extra: Mapping[str, Any] | None = None,
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
            **dict(extra or {}),
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
        adapter = adapter_for(self.platform)
        profile = adapter.profile(
            detected=adapter.capabilities,
            authorized=adapter.capabilities,
        )
        mapped = adapter.map_action(action, profile=profile).payload
        host_workers = mapped.get("host_execution", {}).get("workers", [])
        if not isinstance(host_workers, list) or len(host_workers) != len(workers):
            raise HostTrajectoryError("HOST_EVIDENCE_TEMPLATE_MISSING")

        events = ["action_received", "evidence_templates_materialized"]
        outcomes: list[WorkerOutcome] = []
        native_outcomes: list[NativeWorkerOutcome] = []
        for index, (spec, worker) in enumerate(zip(plan.invocations, workers, strict=True)):
            host_worker = host_workers[index]
            if not isinstance(host_worker, Mapping):
                raise HostTrajectoryError("HOST_EVIDENCE_TEMPLATE_INVALID")
            invocation = compile_worker_invocation(
                action,
                platform=self.platform,
                worker_index=index,
                prompt_loader=self._load_prompt,
            )
            events.append("worker_invoked")
            outcome = WorkerOutcome.from_dict(worker(invocation))
            outcomes.append(outcome)
            native_outcomes.append(NativeWorkerOutcome(
                worker_id=spec.worker_id,
                native_worker_handle=f"{self.platform.value}-worker-{index}",
                status="completed",
                payload=dict(outcome.payload),
                summary=f"{spec.worker_id} completed",
                actual_model="fake-host-model",
                isolation_evidence=(
                    "fork_context=false"
                    if self.platform is HostPlatform.CODEX
                    else "fresh_context"
                ),
            ))
            events.append("native_outcome_recorded")

        if fail_after_receipt:
            raise HostTrajectoryError("FAULT_AFTER_RECEIPT")

        merged: dict[str, Any] = {}
        for outcome in outcomes:
            merged.update(outcome.payload)
        result = HostExecutionAssembler(self.project_root).finalize(
            action=mapped,
            outcomes=native_outcomes,
            coordinator_payload=merged,
        )
        events.append("evidence_transaction_committed")
        next_action = self.core.tick_dict(result)
        repair_required = OutcomeJournal(self.project_root).complete_from_core(
            result, next_action
        )
        if repair_required:
            raise HostTrajectoryError("CORE_RESULT_REPAIR_REQUIRED")
        stream = self.event_store.load_stream(str(action.get("thread_id")))
        event_names = tuple(event.event_type.value for event in stream)
        if "ResultAccepted" not in event_names or "ActionIssued" not in event_names:
            raise HostTrajectoryError(
                "CORE_CAUSAL_CHAIN_INCOMPLETE: " + str(dict(next_action))
            )
        events.extend((
            "result_submitted",
            "outcome_journal_accepted",
            *event_names,
            "next_action_received",
        ))
        return HostTrajectory(result, dict(next_action), tuple(events))


__all__ = ["HostTrajectory", "HostTrajectoryError", "HostTrajectoryRunner"]
