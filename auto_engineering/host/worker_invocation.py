"""把 Core spawn Action 编译为隔离的宿主 Worker 调用。"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from auto_engineering.host import HostPlatform
from auto_engineering.host.runtime_identity import ExecutionIdentity


class WorkerInvocationError(ValueError):
    """Action 无法安全映射为 Worker 调用。"""


class WorkerOutcomeError(ValueError):
    """Worker 输出违反运行身份或结果契约。"""


@dataclass(frozen=True, slots=True)
class WorkerInvocation:
    platform: HostPlatform
    action_message_id: str
    worker_index: int
    prompt: str
    reasoning_effort: str
    fork_turns: str | None
    execution_identity: dict[str, Any]


def compile_worker_invocation(
    action: Mapping[str, Any],
    *,
    platform: HostPlatform,
    worker_index: int = 0,
    prompt_loader: Callable[[str], str] | None = None,
) -> WorkerInvocation:
    """只从机器 Action 构建一次 Worker 调用，不继承协调器会话。"""

    message_id = action.get("message_id")
    stage = action.get("stage")
    spawn = action.get("spawn")
    if (
        not isinstance(message_id, str)
        or not message_id
        or not isinstance(stage, str)
        or not stage
        or not isinstance(spawn, Mapping)
    ):
        raise WorkerInvocationError("WORKER_INVOCATION_INVALID")
    count = spawn.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or not 0 <= worker_index < count:
        raise WorkerInvocationError("WORKER_INDEX_INVALID")

    prompt = action.get("subagent_prompt")
    agents = spawn.get("agents")
    if isinstance(agents, list):
        try:
            worker = agents[worker_index]
        except IndexError as exc:
            raise WorkerInvocationError("WORKER_INDEX_INVALID") from exc
        if not isinstance(worker, Mapping):
            raise WorkerInvocationError("WORKER_INVOCATION_INVALID")
        inline_prompt = worker.get("prompt")
        if isinstance(inline_prompt, str) and inline_prompt:
            prompt = inline_prompt
        else:
            prompt_ref = worker.get("prompt_ref")
            prompt_hash = worker.get("prompt_hash")
            if (
                not isinstance(prompt_ref, str)
                or not prompt_ref
                or not isinstance(prompt_hash, str)
                or prompt_loader is None
            ):
                raise WorkerInvocationError("WORKER_PROMPT_REFERENCE_INVALID")
            prompt = prompt_loader(prompt_ref)
            if hashlib.sha256(prompt.encode("utf-8")).hexdigest() != prompt_hash:
                raise WorkerInvocationError("WORKER_PROMPT_HASH_MISMATCH")
    if not isinstance(prompt, str) or not prompt:
        raise WorkerInvocationError("WORKER_PROMPT_MISSING")

    effort = spawn.get("effort", "high")
    if not isinstance(effort, str) or not effort:
        raise WorkerInvocationError("WORKER_EFFORT_INVALID")
    identity = ExecutionIdentity.worker(stage=stage)
    return WorkerInvocation(
        platform=platform,
        action_message_id=message_id,
        worker_index=worker_index,
        prompt=prompt,
        reasoning_effort=effort,
        fork_turns="none" if platform is HostPlatform.CODEX else None,
        execution_identity=identity.to_dict(),
    )


def validate_worker_outcome(
    outcome: Mapping[str, Any],
    *,
    stage: str,
) -> dict[str, Any]:
    """拒绝 Worker 把协调器专属能力当作自身前置条件。"""

    del stage
    error = outcome.get("spawn_error")
    if (
        outcome.get("spawned") is False
        and outcome.get("spawn_error_code") == "HOST_CAPABILITY_UNAVAILABLE"
        and isinstance(error, str)
        and "spawn_agent" in error
    ):
        raise WorkerOutcomeError(
            "WORKER_ROLE_VIOLATION: Worker 不得检查或调用协调器 spawn 能力"
        )
    return dict(outcome)


__all__ = [
    "WorkerInvocation",
    "WorkerInvocationError",
    "WorkerOutcomeError",
    "compile_worker_invocation",
    "validate_worker_outcome",
]
