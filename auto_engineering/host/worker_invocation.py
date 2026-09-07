"""把 Core spawn Action 编译为隔离的宿主 Worker 调用。"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from auto_engineering.host import HostPlatform, capabilities_for
from auto_engineering.host.runtime_identity import ExecutionIdentity
from auto_engineering.host.spawn_contract import SpawnPlan


class WorkerInvocationError(ValueError):
    """Action 无法安全映射为 Worker 调用。"""


class WorkerOutcomeError(ValueError):
    """Worker 输出违反运行身份或结果契约。"""


@dataclass(frozen=True, slots=True)
class WorkerInvocation:
    platform: HostPlatform
    action_message_id: str
    worker_index: int
    worker_id: str
    prompt: str
    prompt_sha256: str
    reasoning_effort: str
    fork_turns: str | None
    execution_identity: dict[str, Any]


def compile_worker_invocation(
    action: Mapping[str, Any],
    *,
    platform: HostPlatform,
    worker_index: int = 0,
    prompt_loader: Callable[[str], str] | None = None,
    project_root: str | Path | None = None,
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

    worker_id = f"{stage}-{worker_index}"
    prompt_sha256 = ""
    strict_invocations = spawn.get("invocations")
    if not isinstance(strict_invocations, list):
        raise WorkerInvocationError("WORKER_INVOCATION_CONTRACT_REQUIRED")
    capabilities_for(platform).require_spawn()
    plan = SpawnPlan.from_action(action)
    spec = plan.invocations[worker_index]
    if prompt_loader is None:
        raise WorkerInvocationError("WORKER_PROMPT_LOADER_REQUIRED")
    raw_root = project_root if project_root is not None else action.get("project_root")
    if raw_root is not None:
        if not isinstance(raw_root, (str, Path)) or not str(raw_root):
            raise WorkerInvocationError("WORKER_PROJECT_ROOT_INVALID")
        root = Path(raw_root).resolve()
        def ensure_root_bound(reference: str, error_code: str) -> None:
            parts = PurePosixPath(reference).parts
            candidate = (root / Path(*parts)).resolve()
            if candidate == root or root not in candidate.parents:
                raise WorkerInvocationError(error_code)

        ensure_root_bound(spec.prompt_ref, "WORKER_PROMPT_PATH_OUTSIDE_ROOT")
        ensure_root_bound(spec.outcome_path, "WORKER_OUTCOME_PATH_OUTSIDE_ROOT")
        ensure_root_bound(spec.receipt_path, "WORKER_RECEIPT_PATH_OUTSIDE_ROOT")
    prompt = prompt_loader(spec.prompt_ref)
    if not isinstance(prompt, str) or not prompt:
        raise WorkerInvocationError("WORKER_PROMPT_MISSING")
    if hashlib.sha256(prompt.encode("utf-8")).hexdigest() != spec.prompt_sha256:
        raise WorkerInvocationError("WORKER_PROMPT_HASH_MISMATCH")
    worker_id = spec.worker_id
    prompt_sha256 = spec.prompt_sha256
    if not prompt_sha256:
        prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    effort = spawn.get("effort", "high")
    if not isinstance(effort, str) or not effort:
        raise WorkerInvocationError("WORKER_EFFORT_INVALID")
    identity = ExecutionIdentity.worker(stage=stage)
    return WorkerInvocation(
        platform=platform,
        action_message_id=message_id,
        worker_index=worker_index,
        worker_id=worker_id,
        prompt=prompt,
        prompt_sha256=prompt_sha256,
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
    if not isinstance(outcome, Mapping):
        raise WorkerOutcomeError("WORKER_OUTCOME_INVALID")
    if "execution_identity" in outcome:
        raise WorkerOutcomeError("WORKER_RUNTIME_IDENTITY_FORBIDDEN")
    if any(key in outcome for key in (
        "may_drive_loop", "may_spawn_workers", "inherit_parent_context",
        "agents", "subagent", "subagent_prompt",
    )):
        raise WorkerOutcomeError("WORKER_ROLE_VIOLATION: Worker 不得驱动 Loop 或 spawn agents")
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
    if any(key in outcome for key in (
        "native_worker_handle", "actual_model", "isolation_evidence",
        "attestation", "worker_attestations", "receipt", "outcomes",
    )):
        raise WorkerOutcomeError("WORKER_OUTCOME_BOUNDARY_VIOLATION")
    return dict(outcome)


__all__ = [
    "WorkerInvocation",
    "WorkerInvocationError",
    "WorkerOutcomeError",
    "compile_worker_invocation",
    "validate_worker_outcome",
]
