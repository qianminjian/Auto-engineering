"""只消费机器契约的可执行宿主测试替身。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
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
        def load_prompt(reference: str) -> str:
            worker_prompt = action.get("worker_prompt")
            if isinstance(worker_prompt, str):
                return worker_prompt
            project_root = action.get("project_root")
            if not isinstance(project_root, str):
                return ""
            try:
                return (Path(project_root) / reference).read_text(encoding="utf-8")
            except OSError:
                return ""

        invocation = compile_worker_invocation(
            action,
            platform=self.platform,
            prompt_loader=load_prompt,
        )
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
        outcome = WorkerOutcome.from_business_payload(validated)
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
