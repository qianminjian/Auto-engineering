"""将 Core Action 编译为宿主可执行的机器合同。"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from auto_engineering.host import HostPlatform, MappedHostAction
from auto_engineering.host.action_mapper_contracts import (
    CLAUDE_NATIVE_WORKER_TOOLS,
    CODEX_NATIVE_WORKER_TOOL_FAMILIES,
    native_worker_launch_prompt,
    worker_fencing_token,
)
from auto_engineering.host.continuation_contract import continuation_contract
from auto_engineering.host.path_contract import (
    worker_native_result_path,
    worker_outcome_path,
)
from auto_engineering.host.profile import HostProfile
from auto_engineering.host.recovery_contract import (
    REPAIR_COORDINATOR_THEN_FINALIZE,
    WORKER_OUTCOMES_COMMITTED,
)
from auto_engineering.host.worker_observation import (
    WorkerObservationContract,
    observation_relative_path,
)
from auto_engineering.loop.execution_control import (
    ExecutionDisposition,
    control_for_action,
)

# 旧测试/集成入口仍可读取该纯合同函数；实现只保留在 canonical 合同模块。
_native_worker_launch_prompt = native_worker_launch_prompt


def map_host_action(
    action: Mapping[str, object],
    *,
    platform: HostPlatform,
    profile: HostProfile,
) -> MappedHostAction:
    """把一个 Core Action 映射为指定宿主的唯一执行视图。"""

    if profile.platform is not platform:
        raise ValueError("HOST_PROFILE_PLATFORM_MISMATCH")
    message_id = action.get("message_id")
    if not isinstance(message_id, str) or not message_id:
        raise ValueError("HOST_ACTION_INVALID: 缺少 message_id")
    requirements = action.get("capability_requirements", {})
    if not isinstance(requirements, Mapping):
        raise ValueError("HOST_ACTION_INVALID: 能力需求必须为 object")
    effective = profile.effective
    mapped_payload = dict(action)
    action_key = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:24]
    work_root = f".ae-state/host-runtime/work/{action_key}"
    raw_project_root = action.get("project_root")
    project_root = (
        raw_project_root
        if isinstance(raw_project_root, str) and raw_project_root
        else None
    )
    work_files = {
        "outcomes": f"{work_root}/outcomes.json",
        "coordinator_result": f"{work_root}/coordinator-result.json",
        "result": f"{work_root}/result.json",
    }
    host_execution: dict[str, object] = {
        "schema_version": "1.0",
        "platform": platform.value,
        "action_message_id": message_id,
        "work_files": work_files,
        "continuation": continuation_contract(action=action),
    }
    if project_root is not None:
        finalize_argv = [
            "__AE_BUNDLED_RUNNER__", "dev-loop", "--finalize-result",
            (
                work_files["outcomes"]
                if isinstance(action.get("spawn"), Mapping)
                else work_files["coordinator_result"]
            ),
        ]
        if isinstance(action.get("spawn"), Mapping):
            finalize_argv.extend([
                "--coordinator-result", work_files["coordinator_result"],
            ])
        finalize_argv.extend([
            "--output-result", work_files["result"],
            "--project-root", project_root,
        ])
        host_execution["operations"] = {
            "finalize": {"argv": finalize_argv},
            "validate": {"argv": [
                "__AE_BUNDLED_RUNNER__", "dev-loop", "--validate-result",
                work_files["result"], "--project-root", project_root,
            ]},
            "submit": {"argv": [
                "__AE_BUNDLED_RUNNER__", "dev-loop", "--tick", "--result",
                work_files["result"], "--project-root", project_root,
            ]},
        }
    spawn = action.get("spawn")
    rejection = action.get("result_rejection")
    is_result_repair = (
        isinstance(rejection, Mapping)
        and rejection.get("repair_required") is True
    )
    if (
        not is_result_repair
        and isinstance(spawn, Mapping)
        and isinstance(spawn.get("invocations"), list)
    ):
        from auto_engineering.host.spawn_contract import (
            SpawnPlan,
            WorkerInvocationSpec,
        )
        from auto_engineering.host.worker_attestation import attestation_template

        if project_root is None:
            raise ValueError("HOST_ACTION_PROJECT_ROOT_MISSING")

        plan = SpawnPlan.from_action(action)
        stage = str(action.get("stage") or "")
        raw_generation = action.get("execution_generation", 1)
        if (
            not isinstance(raw_generation, int)
            or isinstance(raw_generation, bool)
            or raw_generation < 1
        ):
            raise ValueError("HOST_ACTION_EXECUTION_GENERATION_INVALID")
        execution_generation = raw_generation
        generation_bound_paths = "execution_generation" in action
        if generation_bound_paths:
            # generation 绑定后，映射视图中的 invocation 也必须改成同一
            # canonical 路径；否则 launch prompt 与 Collector 会各读一处。
            mapped_spawn = dict(spawn)
            mapped_spawn["invocations"] = [
                {
                    **invocation.to_dict(),
                    "outcome_path": worker_outcome_path(
                        message_id,
                        invocation.worker_id,
                        execution_generation,
                    ),
                }
                for invocation in plan.invocations
            ]
            mapped_payload["spawn"] = mapped_spawn
            plan = SpawnPlan.from_action(mapped_payload)

        expected_isolation = {
            HostPlatform.CODEX: "fork_turns=none",
            HostPlatform.CLAUDE_CODE: "fresh_context",
        }[platform]
        host_execution["worker_observation"] = (
            WorkerObservationContract.for_platform(platform).to_dict()
        )
        host_execution["worker_lifecycle"] = {
            "schema_version": "1.0",
            "work_files": dict(work_files),
            "required_order": [
                "spawn",
                "wait",
                "record_worker_outcome",
                "reclaim",
                "finalize",
            ],
            "reclaim_before_finalize": platform is HostPlatform.CODEX,
            "reclaim_tools": (
                [
                    "multi_agent_v1__close_agent",
                    "close_agent",
                    "collaboration.interrupt_agent",
                    "interrupt_agent",
                ]
                if platform is HostPlatform.CODEX
                else []
            ),
            "completed_handle_must_not_survive_action": True,
        }

        def resolved_outcome_path(invocation: WorkerInvocationSpec) -> str:
            return invocation.outcome_path

        def resolved_native_result_path(invocation: WorkerInvocationSpec) -> str:
            return worker_native_result_path(
                message_id, invocation.worker_id, execution_generation
            )

        def record_worker_outcome_argv(invocation: WorkerInvocationSpec) -> list[str]:
            argv = [
                "__AE_BUNDLED_RUNNER__", "dev-loop", "--record-worker-outcome",
                "--worker-id", invocation.worker_id, "--worker-status",
                "__WORKER_STATUS__", "--native-worker-handle",
                "__NATIVE_WORKER_HANDLE__", "--native-result-file",
                resolved_native_result_path(invocation),
            ]
            # Codex 的 wait_agent 正文通过 stdin 原样转交；Claude 的
            # PostToolUse 已将 Agent/TaskOutput 原生 envelope 原子写入文件。
            if platform is HostPlatform.CODEX:
                # Codex 原生 wait 可能只返回 target 的 completed 状态，正文
                # 为 null；此时必须依赖同一 Action 的 completed observation
                # 与 Worker 私有 outcome，而不能把 wait 外层包装当业务结果。
                argv.extend(["--native-result-stdin", "--native-status-only"])
            argv.extend([
                "--actual-model", "__ACTUAL_MODEL__", "--isolation-evidence",
                "__ISOLATION_EVIDENCE__", "--project-root", project_root,
            ])
            return argv

        host_execution["workers"] = [
            {
                "worker_id": invocation.worker_id,
                "native_worker_handle": None,
                "prompt_ref": invocation.prompt_ref,
                "prompt_sha256": invocation.prompt_sha256,
                "outcome_path": resolved_outcome_path(invocation),
                "native_result_path": resolved_native_result_path(invocation),
                "observation_path": str(observation_relative_path(
                    message_id, invocation.worker_id, execution_generation
                )),
                "execution_generation": execution_generation,
                "fencing_token": worker_fencing_token(
                    message_id, invocation.worker_id, execution_generation
                ),
                "native_launch_prompt": native_worker_launch_prompt(
                    project_root=project_root,
                    worker_id=invocation.worker_id,
                    prompt_ref=invocation.prompt_ref,
                    prompt_sha256=invocation.prompt_sha256,
                    outcome_path=resolved_outcome_path(invocation),
                    required_isolation_evidence=expected_isolation,
                    execution_generation=execution_generation,
                    fencing_token=worker_fencing_token(
                        message_id, invocation.worker_id, execution_generation
                    ),
                ),
                "expected_isolation_evidence": expected_isolation,
                "host_fact_mapping": {
                    "native_worker_handle": (
                        "native_agent_id_or_task_id"
                        if platform is HostPlatform.CLAUDE_CODE
                        else "native_agent_or_thread_id"
                    ),
                    "actual_model": "native_model_or_unreported",
                    "isolation_evidence": expected_isolation,
                },
                "action_work_files": dict(work_files),
                "receipt_path": invocation.receipt_path,
                "receipt": {
                    "status": "pending",
                    "stage": stage,
                    "worker": invocation.worker_id,
                    "requested_effort": invocation.requested_effort,
                    "actual_model": "unknown",
                },
                "attestation": attestation_template(
                    platform=platform,
                    action_message_id=message_id,
                    invocation=invocation,
                ),
                "record_worker_outcome": {
                    "schema_version": "1.0",
                    "argv_template": record_worker_outcome_argv(invocation),
                    "runtime_arguments": {
                        "worker_status": "--worker-status",
                        "native_worker_handle": "--native-worker-handle",
                        "actual_model": "--actual-model",
                        "isolation_evidence": "--isolation-evidence",
                        "native_result_file": "--native-result-file",
                        **(
                            {"native_status_only": "--native-status-only"}
                            if platform is HostPlatform.CODEX
                            else {}
                        ),
                    },
                    "required_runtime_fields": [
                        "worker_status",
                        "native_worker_handle",
                        "actual_model",
                        "isolation_evidence",
                    ],
                    "required_when_completed": [
                        "native_worker_handle",
                        "isolation_evidence",
                    ],
                    "optional_when_failed": [
                        "native_worker_handle",
                        "isolation_evidence",
                    ],
            },
        }

            for invocation in plan.invocations
        ]
        if platform is HostPlatform.CODEX:
            host_execution["native_worker_tools"] = {
                "selection": "first_complete_exposed_family",
                "families": [dict(family) for family in CODEX_NATIVE_WORKER_TOOL_FAMILIES],
            }
        else:
            host_execution["native_worker_tools"] = dict(CLAUDE_NATIVE_WORKER_TOOLS)
    elif (
        is_result_repair
        and isinstance(spawn, Mapping)
        and isinstance(spawn.get("invocations"), list)
    ):
        # Core 已拒绝同一 Action 的候选 Result；修复上下文只重做
        # Coordinator，Worker 事实由 outcome journal 恢复，不再暴露 spawn。
        semantic_context_refs = [
            str(item["prompt_ref"])
            for item in spawn["invocations"]
            if isinstance(item, Mapping)
            and isinstance(item.get("prompt_ref"), str)
        ]
        host_execution["recovery"] = {
            "schema_version": "1.0",
            "status": WORKER_OUTCOMES_COMMITTED,
            "spawn_permitted": False,
            "forbidden_operations": ["spawn_worker", "record_worker_outcome"],
            "required_operation": REPAIR_COORDINATOR_THEN_FINALIZE,
            "result_ref": work_files["result"],
            "outcomes_ref": work_files["outcomes"],
            "coordinator_result_ref": work_files["coordinator_result"],
            "semantic_context_refs": semantic_context_refs,
        }
        mapped_payload.pop("spawn", None)
        mapped_payload.pop("spawn_proof_token", None)
        mapped_payload["instruction"] = (
            "当前是 Result repair：只修复 Coordinator 业务产物；"
            "不得重新启动 Worker，必须复用 outcomes_ref 中的权威 Worker outcomes，"
            "完成后再调用 Finalizer、validate 和 submit。"
        )

    # Developer 的环境故障是 D73 的可恢复资源边界。仅投影
    # ``WAIT_RESOURCE`` 不足以驱动真实宿主：主 Agent 可能完成手工检查后直接
    # 停止，或把等待当成用户 Gate。把“恢复同一 active Action”固化为机器合同；
    # 这不是第二个 Loop，也不推进 Tick，恢复后的业务验证仍必须回到原 Action
    # 的 Worker/Finalizer/Validate/Submit 链路。
    execution_control = control_for_action(action)
    if (
        execution_control.disposition is ExecutionDisposition.WAIT_RESOURCE
        and execution_control.reason_code == "environment_failure"
    ):
        host_execution["resource_recovery"] = {
            "schema_version": "1.0",
            "status": "WAIT_RESOURCE",
            "reason_code": "environment_failure",
            "resume_operation": "resume_active_action",
            "retry_mode": "reexecute_active_action",
            "spawn_permitted": isinstance(action.get("spawn"), Mapping),
            "forbidden_operations": ["submit_resource_wait", "advance_stage"],
            "required_operation": "recover_resource_then_resume",
        }
        mapped_payload["instruction"] = (
            str(mapped_payload.get("instruction") or "")
            + " 当前 Core Action 因项目工具链或依赖缺失进入 WAIT_RESOURCE；"
            "不要询问用户或提交 resource_wait。请在项目根修复环境后，"
            "只执行一次 resume_active_action，并重新执行该 active Action 的完整机器合同；"
            "不得仅运行检查后停止，也不得重复 resume。"
        ).strip()
    mapped_payload["host_execution"] = host_execution
    if action.get("action") == "session_rollover":
        if not effective.session_handoff:
            raise ValueError("HOST_SESSION_HANDOFF_UNAVAILABLE")
        claim_token = action.get("claim_token")
        capsule = action.get("capsule")
        if not isinstance(claim_token, str) or not isinstance(capsule, Mapping):
            raise ValueError("HOST_ACTION_INVALID: rollover 契约不完整")
        mapped_payload["host_control"] = {
            "operation": "create_fresh_session",
            "load_capsule": dict(capsule),
            "submit_result": {
                "stage": "session_claimed",
                "claim_token": claim_token,
            },
            "fail_closed": True,
        }
    for name, required in requirements.items():
        if not required:
            continue
        capability_name = "git_mutation" if name == "git_operations" else name
        available = getattr(effective, capability_name, None)
        if available is not True:
            raise ValueError(f"HOST_CAPABILITY_UNAVAILABLE: {name}")
    return MappedHostAction(
        platform=platform,
        message_id=message_id,
        payload=mapped_payload,
    )


__all__ = ["map_host_action"]
