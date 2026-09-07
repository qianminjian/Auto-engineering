"""CLI 宿主 Action 运行时投影的 canonical service。

这里承载 generation/fencing、Worker outcome 恢复和宿主 lease 绑定。
dev_loop.py 只保留协议入口与兼容包装，不复制这套运行时决策。
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from auto_engineering.cli.host_action_work_files import (
    ensure_action_work_file_parents,
    root_bound_path,
)
from auto_engineering.host.path_contract import (
    worker_native_result_path,
    worker_outcome_path,
)
from auto_engineering.host.recovery_contract import (
    NATIVE_OUTCOMES_READY,
    REPAIR_COORDINATOR_THEN_FINALIZE,
    WORKER_OUTCOMES_COMMITTED,
)
from auto_engineering.host.worker_evidence import native_outcomes_are_ready

_logger = logging.getLogger("ae.cli.host_action_runtime")


def resume_host_platform(root: Path, action: Mapping[str, object]) -> str | None:
    """恢复 active Action 时复用上一次宿主平台，避免合同跨宿主漂移。"""

    from auto_engineering.host import HostPlatform
    from auto_engineering.host.runtime_driver import HostRunLeaseStore

    thread_id = action.get("thread_id")
    message_id = action.get("message_id")
    if not isinstance(thread_id, str) or not isinstance(message_id, str):
        return None

    lease = HostRunLeaseStore(root).load()
    if (
        lease is not None
        and lease.thread_id == thread_id
        and lease.action_message_id == message_id
    ):
        try:
            return HostPlatform(lease.platform).value
        except ValueError:
            return None

    report_root = root.resolve() / ".ae-state" / "host-runtime" / "stop-reports"
    candidates: list[tuple[float, str]] = []
    for path in report_root.glob("*.json"):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if not isinstance(report, Mapping):
            continue
        if (
            report.get("thread_id") != thread_id
            or report.get("action_message_id") != message_id
            or report.get("disposition") != "CONTINUE"
            or report.get("lease_cleared") is not True
        ):
            continue
        platform = report.get("platform")
        if not isinstance(platform, str):
            continue
        try:
            normalized = HostPlatform(platform).value
        except ValueError:
            continue
        try:
            modified = path.stat().st_mtime
        except OSError:
            modified = 0.0
        candidates.append((modified, normalized))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    return None


@contextmanager
def resume_platform_scope(platform: str | None) -> Iterator[None]:
    """把恢复平台作为一次 CLI 操作的显式边界传入宿主映射。"""

    if platform is None:
        yield
        return
    previous = os.environ.get("AE_HOST_PLATFORM")
    os.environ["AE_HOST_PLATFORM"] = platform
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("AE_HOST_PLATFORM", None)
        else:
            os.environ["AE_HOST_PLATFORM"] = previous


def map_action_for_host(action: dict) -> dict:
    """已识别宿主必须经过 Adapter 2.0 能力映射；未知 shell 保持核心协议。"""
    from auto_engineering.host import HostPlatform, detect_host
    from auto_engineering.loop.execution_control import project_execution_control

    # Canonical Action 保持不可变；宿主投影仍需修复完整 Gate 分类落地前生成的旧快照，
    # 否则旧人工 Gate 会被误判为 CONTINUE 并送入执行请求编译。
    action = project_execution_control(action)

    if not isinstance(action.get("message_id"), str):
        return action
    detection = detect_host()
    if detection.platform is HostPlatform.UNKNOWN:
        return action
    from auto_engineering.host.adapters import adapter_for

    adapter = adapter_for(detection.platform)
    profile = adapter.probe(
        detected=detection.capabilities,
        authorized=detection.capabilities,
    )
    return adapter.map_action(action, profile=profile).payload


def bind_worker_execution_identity(
    action: dict,
    root: Path,
    *,
    include_failure_journal: bool = True,
) -> dict:
    """为当前宿主会话绑定 Action generation；普通重读保持幂等。

    前置恢复检查必须使用当前 lease 的 generation；只有确认 Worker 失败后
    的正常重试映射，才允许读取 failure journal 推进下一代。
    """

    if not isinstance(action.get("spawn"), Mapping):
        return action
    message_id = action.get("message_id")
    if not isinstance(message_id, str) or not message_id:
        return action
    from auto_engineering.host import HostPlatform, detect_host
    from auto_engineering.host.runtime_driver import (
        HostRunLeaseStore,
        fencing_token_for,
        host_session_id_from_environ,
    )

    detection = detect_host()
    if detection.platform is HostPlatform.UNKNOWN:
        return action
    session_id = host_session_id_from_environ(detection.platform)
    if not session_id:
        return action
    previous = HostRunLeaseStore(root).load()
    recovered_generation: int | None = None
    if previous is not None and previous.action_message_id == message_id:
        generation = previous.execution_generation
        # 宿主会话切换不应让已经由 PostToolUse/Worker 写入的旧代事实
        # 失去 canonical 路径。只在当前 Action、当前 Worker 的旧代
        # artifact 确实存在时复用该代；没有事实时才升代，保持 fail-closed。
        for candidate in range(previous.execution_generation, 0, -1):
            if _has_worker_generation_artifact(action, root, candidate):
                recovered_generation = candidate
                generation = candidate
                break
        if (
            previous.host_session_id != session_id
            and recovered_generation is None
        ):
            generation = previous.execution_generation + 1
    else:
        generation = 1
    # Worker 失败后仍保留同一个 Core Action，但下一次执行必须是新的
    # generation。以 Outcome Journal 的已提交失败次数作为稳定提示，避免
    # 每次 status/read 都无界递增，同时阻止重试复用旧 artifact/handle。
    failure_journal = (
        root / ".ae-state/host-runtime/outcomes" / f"{message_id}.json"
    )
    try:
        journal = json.loads(failure_journal.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        journal = None
    if (
        include_failure_journal
        and recovered_generation is None
        and isinstance(journal, Mapping)
        and journal.get("status") == "worker_failed"
    ):
        failure_attempt = journal.get("failure_attempt")
        if isinstance(failure_attempt, int) and not isinstance(failure_attempt, bool):
            generation = max(generation, failure_attempt + 1)
    bound = dict(action)
    bound["execution_generation"] = generation
    bound["fencing_token"] = fencing_token_for(
        message_id, session_id, generation
    )
    return bound


def _has_worker_generation_artifact(
    action: Mapping[str, object], root: Path, generation: int
) -> bool:
    """判断当前 Action 的某一代是否已有宿主/Worker 事实。"""

    if generation < 1:
        return False
    message_id = action.get("message_id")
    spawn = action.get("spawn")
    invocations = spawn.get("invocations") if isinstance(spawn, Mapping) else None
    if not isinstance(message_id, str) or not message_id or not isinstance(invocations, list):
        return False
    root = root.resolve()
    for invocation in invocations:
        if not isinstance(invocation, Mapping):
            continue
        worker_id = invocation.get("worker_id")
        if not isinstance(worker_id, str) or not worker_id:
            continue
        for relative in (
            worker_native_result_path(message_id, worker_id, generation),
            worker_outcome_path(message_id, worker_id, generation),
        ):
            candidate = (root / relative).resolve()
            if root in candidate.parents and candidate.is_file():
                return True
    return False


def prepare_action_for_host(
    action: dict,
    root: Path,
    *,
    compact_view: bool | None = None,
    include_failure_journal: bool = True,
    bind_worker_execution_identity_fn: Callable = bind_worker_execution_identity,
    map_action_fn: Callable = map_action_for_host,
    project_host_attestation_repair_action: Callable,
    compact_action: Callable,
) -> dict:
    """映射 Action，并为当前原生宿主会话原子记录执行义务。"""

    action = bind_worker_execution_identity_fn(
        action,
        root,
        include_failure_journal=include_failure_journal,
    )
    mapped = map_action_fn(action)
    ensure_action_work_file_parents(mapped, root)
    host_execution = mapped.get("host_execution")
    if isinstance(action.get("spawn"), Mapping) and isinstance(
        host_execution, dict
    ):
        from auto_engineering.host.execution_assembler import (
            HostEvidenceValidationError,
            HostExecutionAssembler,
            WorkerOutcomeCollectionError,
        )

        work_files = host_execution.get("work_files")
        result_ref = (
            work_files.get("result")
            if isinstance(work_files, Mapping)
            else None
        )
        outcomes_ref = (
            work_files.get("outcomes")
            if isinstance(work_files, Mapping)
            else None
        )
        coordinator_ref = (
            work_files.get("coordinator_result")
            if isinstance(work_files, Mapping)
            else None
        )
        if all(
            isinstance(value, str) and value
            for value in (result_ref, outcomes_ref, coordinator_ref)
        ):
            raw_workers = host_execution.get("workers")
            rejection = action.get("result_rejection")
            is_result_repair = (
                isinstance(rejection, Mapping)
                and rejection.get("repair_required") is True
            )
            semantic_context_refs = [
                str(worker["prompt_ref"])
                for worker in raw_workers
                if isinstance(worker, Mapping)
                and isinstance(worker.get("prompt_ref"), str)
            ] if isinstance(raw_workers, list) else []
            try:
                committed = HostExecutionAssembler(root).restore_committed_result_to_file(
                    action=action,
                    result_path=Path(str(result_ref)),
                    outcomes_path=Path(str(outcomes_ref)),
                )
            except HostEvidenceValidationError as exc:
                import click

                raise click.ClickException(str(exc)) from exc
            if committed is not None:
                # Core Action 快照保持不变；宿主投影只暴露唯一合法恢复动作。
                mapped.pop("spawn", None)
                host_execution.pop("workers", None)
                host_execution.pop("native_worker_tools", None)
                host_execution["recovery"] = {
                    "schema_version": "1.0",
                    "status": WORKER_OUTCOMES_COMMITTED,
                    "spawn_permitted": False,
                    "forbidden_operations": [
                        "spawn_worker",
                        "record_worker_outcome",
                    ],
                    "required_operation": REPAIR_COORDINATOR_THEN_FINALIZE,
                    "result_ref": result_ref,
                    "outcomes_ref": outcomes_ref,
                    "coordinator_result_ref": coordinator_ref,
                    "semantic_context_refs": semantic_context_refs,
                }
                mapped["instruction"] = (
                    "当前 Action 已有 Core 绑定的 Worker outcomes。"
                    "禁止启动 Worker；先验证并提交已固化 Result。"
                    "若业务预检失败，只修复 coordinator payload，"
                    "并使用已恢复 outcomes 重新 finalize。"
                )
            else:
                # Worker 已完成、原生事实已落盘，但进程可能在 Finalizer 提交前
                # 中断。此时重新 spawn 会重复付费且改变事实；只投影 finalize 恢复。
                import json

                outcomes_path = root_bound_path(Path(str(outcomes_ref)), root)
                coordinator_path = root_bound_path(
                    Path(str(coordinator_ref)), root
                )
                native_ready = False
                coordinator_ready = False
                try:
                    raw_outcomes = json.loads(
                        outcomes_path.read_text(encoding="utf-8")
                    )
                    try:
                        raw_coordinator = json.loads(
                            coordinator_path.read_text(encoding="utf-8")
                        )
                    except (OSError, json.JSONDecodeError):
                        raw_coordinator = None
                    coordinator_ready = isinstance(raw_coordinator, dict)
                    outcome_items = (
                        raw_outcomes.get("outcomes")
                        if isinstance(raw_outcomes, dict)
                        else None
                    )
                    native_ready = native_outcomes_are_ready(
                        action=mapped,
                        outcome_items=outcome_items,
                    )
                except (KeyError, OSError, json.JSONDecodeError, TypeError):
                    native_ready = False
                if native_ready:
                    mapped.pop("spawn", None)
                    host_execution.pop("workers", None)
                    host_execution.pop("native_worker_tools", None)
                    host_execution["recovery"] = {
                        "schema_version": "1.0",
                        "status": (
                            WORKER_OUTCOMES_COMMITTED
                            if is_result_repair
                            else NATIVE_OUTCOMES_READY
                        ),
                        "spawn_permitted": False,
                        "forbidden_operations": (
                            ["spawn_worker", "record_worker_outcome"]
                            if is_result_repair
                            else ["spawn_worker"]
                        ),
                        "required_operation": (
                            REPAIR_COORDINATOR_THEN_FINALIZE
                            if is_result_repair
                            else (
                                "finalize_current_native_outcomes"
                                if coordinator_ready
                                else "produce_coordinator_then_finalize"
                            )
                        ),
                        "coordinator_result_ready": coordinator_ready,
                        "result_ref": result_ref,
                        "outcomes_ref": outcomes_ref,
                        "coordinator_result_ref": coordinator_ref,
                        "semantic_context_refs": semantic_context_refs,
                    }
                    mapped["instruction"] = (
                        "当前 Action 的 Worker outcomes 已提交，但上一份 Coordinator "
                        "Result 未通过 Core 校验。禁止重新启动 Worker；只修复 Coordinator "
                        "payload；不得再次调用 record-worker-outcome，再调用 Finalizer、"
                        "validate 和 tick。"
                        if is_result_repair
                        else (
                            "当前 Action 的原生 Worker outcomes 与 Coordinator payload "
                            "已经完整落盘但尚未提交。"
                            "禁止重新启动 Worker；立即使用当前 outcomes 和 "
                            "coordinator_result 调用 Finalizer，再 validate/tick。"
                            if coordinator_ready
                            else
                            "当前 Action 的原生 Worker outcomes 已完整落盘，但宿主进程在 "
                            "Coordinator payload 写入前中断。禁止重新启动 Worker；先根据 "
                            "outcomes_ref 生成当前 Coordinator payload，再调用 Finalizer、"
                            "validate 和 tick。"
                        )
                    )
                elif not native_ready:
                    # 宿主进程可能在 Worker 写入私有业务 outcome、但尚未
                    # 回写原生事实时退出。跨进程恢复必须识别这个中间态，
                    # 否则 canonical Action 仍含 spawn 就会重复启动 Worker。
                    try:
                        HostExecutionAssembler(root).collect_worker_outcomes_from_artifacts(
                            action=mapped,
                            outcomes_path=outcomes_path,
                        )
                    except WorkerOutcomeCollectionError as exc:
                        if exc.code == "HOST_WORKER_ATTESTATION_MISSING":
                            mapped = project_host_attestation_repair_action(
                                mapped,
                                worker_id=exc.worker_id,
                                detail=exc.detail or "private_business_artifact_only",
                            )
    from auto_engineering.host import HostPlatform, detect_host
    from auto_engineering.host.runtime_driver import (
        HostRunLease,
        HostRunLeaseError,
        HostRunLeaseStore,
        host_session_id_from_environ,
    )

    detection = detect_host()
    session_id = host_session_id_from_environ(detection.platform)
    extensions = mapped.get("extensions")
    ae = extensions.get("ae") if isinstance(extensions, Mapping) else None
    control = ae.get("execution_control") if isinstance(ae, Mapping) else None
    requires_continuous_lease = (
        isinstance(control, Mapping)
        and control.get("disposition") == "CONTINUE"
    )
    requires_terminal_lease = (
        isinstance(control, Mapping)
        and control.get("disposition") == "TERMINAL"
    )
    if (
        detection.platform is not HostPlatform.UNKNOWN
        and session_id is None
        and requires_continuous_lease
        and isinstance(mapped.get("message_id"), str)
    ):
        raise HostRunLeaseError("HOST_SESSION_ID_UNAVAILABLE")
    if (
        detection.platform is not HostPlatform.UNKNOWN
        and session_id is not None
        and (requires_continuous_lease or requires_terminal_lease)
        and isinstance(mapped.get("message_id"), str)
    ):
        lease = HostRunLease.from_action(
            mapped,
            platform=detection.platform.value,
            host_session_id=session_id,
        )
        HostRunLeaseStore(root).save(lease)
    elif (
        detection.platform is not HostPlatform.UNKNOWN
        and session_id is not None
        and isinstance(mapped.get("message_id"), str)
    ):
        # WAIT_USER/WAIT_RESOURCE/ERROR/HANDOFF 已允许宿主让出控制权；清掉
        # 同一会话上一 Action 的 CONTINUE 租约，避免 Stop Hook 把正常等待
        # 误报成“仍有必须继续执行的 Action”。不触碰其他会话的租约。
        lease_store = HostRunLeaseStore(root)
        previous_lease = lease_store.load()
        if previous_lease is None or previous_lease.host_session_id == session_id:
            lease_store.clear()
    use_compact = (
        os.environ.get("AE_HOST_ACTION_VIEW", "").strip().lower() == "compact"
        if compact_view is None
        else compact_view
    )
    if use_compact:
        return compact_action(mapped, root)
    return mapped
