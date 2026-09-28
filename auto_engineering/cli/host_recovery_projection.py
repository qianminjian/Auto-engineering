"""宿主 Worker 交接分类到 Action 恢复视图的唯一投影边界。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from auto_engineering.host.recovery_contract import HOST_PROTOCOL_RECOVERY


def project_host_attestation_repair_action(
    mapped_action: Mapping[str, Any],
    *,
    worker_id: str,
    detail: str,
    repair_kind: str = "attestation",
    project_result_repair_action_fn: Callable,
) -> dict[str, Any]:
    """把唯一 Worker 交接分类投影成禁止重复 spawn 的宿主 Action。"""

    is_artifact_repair = repair_kind == "worker_artifact"
    is_protocol_failure = repair_kind == "protocol_failure"
    projected = (
        dict(mapped_action)
        if is_protocol_failure
        else project_result_repair_action_fn(
            mapped_action,
            {
                "error_code": (
                    "HOST_WORKER_ARTIFACT_REPAIRABLE"
                    if is_artifact_repair
                    else "HOST_WORKER_ATTESTATION_MISSING"
                ),
                "message": (
                    "Worker 私有产物格式无效，但同一 Action 的绑定原生结果可修复。"
                    if is_artifact_repair
                    else "Worker 业务产物已存在，但宿主原生事实尚未回写。"
                ),
                "violations": [f"{worker_id}:{detail}"],
            },
        )
    )
    host_execution = projected.get("host_execution")
    if not isinstance(host_execution, Mapping):
        return projected
    host = dict(host_execution)
    work_files = host.get("work_files")
    spawn = mapped_action.get("spawn")
    recovery: dict[str, Any] = {
        "schema_version": "1.0",
        "status": (
            HOST_PROTOCOL_RECOVERY
            if is_protocol_failure
            else "worker_artifact_repair"
            if is_artifact_repair
            else "worker_attestation_pending"
        ),
        "spawn_permitted": False,
        "forbidden_operations": ["spawn_worker"],
        "required_operation": (
            "record_worker_protocol_failure_then_finalize"
            if is_protocol_failure
            else "repair_worker_artifact_then_finalize"
            if is_artifact_repair
            else "record_worker_outcome_then_finalize"
        ),
        "worker_id": worker_id,
        "detail": detail,
        "repair_kind": repair_kind,
    }
    if is_protocol_failure:
        recovery["error_code"] = "HOST_PROTOCOL_FAILURE"
    if isinstance(spawn, Mapping):
        recovery["record_plan"] = {
            key: (
                [dict(item) for item in value]
                if key == "invocations" and isinstance(value, list)
                else value
            )
            for key, value in spawn.items()
        }
    if isinstance(work_files, Mapping):
        for key in ("outcomes", "coordinator_result", "result"):
            value = work_files.get(key)
            if isinstance(value, str) and value:
                recovery[f"{key}_ref"] = value
    host["recovery"] = recovery
    projected["host_execution"] = host
    projected.pop("spawn", None)
    projected["instruction"] = (
        (
            "当前 Worker 私有/native 交接无法证明业务结果，属于宿主协议失败。"
            "禁止重新启动 Worker，也不得消费 Worker 业务失败预算；保留原始证据，"
            "按固定 record_worker_outcome 合同记录 HOST_PROTOCOL_FAILURE，"
            "随后按当前 Action 的 finalize、validate、submit 顺序继续。"
        )
        if is_protocol_failure
        else (
            "当前 Worker 私有业务 outcome 格式无效，但同一 Action 的绑定原生结果有效。"
            "禁止重新启动 Worker；使用该绑定结果按固定 record_worker_outcome 合同"
            "重建 canonical business envelope。宿主会隔离原私有文件并保持幂等，"
            "随后按当前 Action 的 finalize、validate、submit 顺序继续。"
        )
        if is_artifact_repair
        else (
            "当前 Worker 已写入私有业务 outcome，但宿主事实回写缺失。"
            "禁止重新启动或等待新的 Worker；使用仍然有效的原生 Worker 返回值，"
            "按 host_execution.workers[].record_worker_outcome 固定模板补交 handle、"
            "actual_model 和实际 isolation_evidence，随后按当前 Action 的 finalize、"
            "validate、submit 顺序继续。若宿主已丢失原生 handle，必须保留该错误并停止，"
            "不得用 unreported 句柄伪造 completed。"
        )
    )
    return projected


__all__ = ["project_host_attestation_repair_action"]
