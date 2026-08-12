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


class HostTrajectoryError(RuntimeError):
    """宿主轨迹未完成必要生命周期。"""


@dataclass(frozen=True, slots=True)
class HostTrajectory:
    result: dict[str, Any]
    next_action: dict[str, Any]
    events: tuple[str, ...]


class HostTrajectoryRunner:
    """执行 Action→Invocation→Proof→Result→下一 Action 的合同轨迹。"""

    def __init__(self, project_root: Path, platform: HostPlatform) -> None:
        self.project_root = project_root
        self.platform = platform

    def _load_prompt(self, ref: str) -> str:
        return (self.project_root / ref).read_text(encoding="utf-8")

    def run(
        self,
        action: Mapping[str, Any],
        *,
        workers: Sequence[Callable[[WorkerInvocation], Mapping[str, Any]]],
        submit_result: Callable[[dict[str, Any]], Mapping[str, Any]] | None,
    ) -> HostTrajectory:
        if submit_result is None:
            raise HostTrajectoryError("CORE_RESULT_SUBMITTER_REQUIRED")
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
            "stage": action.get("stage"),
            "spawned": True,
            "spawn_proof_token": total_token,
            "worker_attestations": [item.to_dict() for item in attestations],
        }
        next_action = dict(submit_result(result))
        events.extend(("result_submitted", "next_action_received"))
        return HostTrajectory(result, next_action, tuple(events))


__all__ = ["HostTrajectory", "HostTrajectoryError", "HostTrajectoryRunner"]
