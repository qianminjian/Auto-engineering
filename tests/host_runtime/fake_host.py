"""只消费机器契约的可执行宿主测试替身。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from auto_engineering.host import HostPlatform
from auto_engineering.host.spawn_contract import WorkerOutcome
from auto_engineering.host.worker_invocation import (
    WorkerInvocation,
    compile_worker_invocation,
    validate_worker_outcome,
)


class AgentCapacityError(RuntimeError):
    """宿主原生 Worker 容量暂时耗尽。"""


@dataclass(frozen=True, slots=True)
class FakeHostExecution:
    result: dict[str, Any]
    receipt: dict[str, Any]
    attempts: int


class FakeHostRuntime:
    """执行单 Worker Action 的最小宿主生命周期。"""

    def __init__(self, platform: HostPlatform) -> None:
        self.platform = platform
        self.reclaimed_count = 0
        self.receipts: list[dict[str, Any]] = []

    def execute(
        self,
        action: Mapping[str, Any],
        worker: Callable[[WorkerInvocation], Mapping[str, Any]],
    ) -> FakeHostExecution:
        invocation = compile_worker_invocation(action, platform=self.platform)
        attempts = 0
        while True:
            attempts += 1
            try:
                raw = worker(invocation)
                break
            except AgentCapacityError:
                if attempts >= 2:
                    raise
                self.reclaimed_count += 1

        validated = validate_worker_outcome(raw, stage=str(action.get("stage", "")))
        outcome = WorkerOutcome.from_dict(validated)
        result = {**outcome.payload, "spawned": True}
        receipt = {
            "status": "completed",
            "action_message_id": invocation.action_message_id,
            "worker_index": invocation.worker_index,
            "execution_identity": invocation.execution_identity,
        }
        self.receipts.append(receipt)
        return FakeHostExecution(result=result, receipt=receipt, attempts=attempts)


__all__ = ["AgentCapacityError", "FakeHostExecution", "FakeHostRuntime"]
