"""宿主 Compact Action 视图的 canonical compiler。"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from auto_engineering.cli.host_action_runtime import root_bound_path


def compact_host_action(action: Mapping[str, Any], root: Path) -> dict[str, Any]:
    """为产品宿主生成有界控制视图；Canonical Action 保持不变。"""

    compact_keys = (
        "schema_version",
        "message_type",
        "message_id",
        "correlation_id",
        "causation_id",
        "thread_id",
        "tick",
        "stage",
        "action",
        "active_action_message_id",
        "project_root",
        "extensions",
        "host_execution",
        "spawn",
        "expected_format",
        "result_contract",
        "valid_plate_keys",
        "gate",
        "current_gap",
        "current_gap_index",
        "total_gaps",
        "gap_review_contract",
        "auto_decision",
        "mode",
        "has_blocking",
        "gap_scan_summary",
        "audit_execution_profile",
        "required_capabilities",
        "missing_capabilities",
        "constraints",
        "resource",
        "retry_stage",
        "reason_code",
        "retry_attempt",
        "retry_limit",
        "reason",
        "result_rejection",
        "repair_operation",
        "next_transition",
        "current_session_id",
        "capsule",
        "claim_token",
        "expires_at",
        "verdict",
        "verdict_level",
        "verdict_reason",
        "error_code",
        "message",
        "suggestion",
        "next_operation",
    )
    compact = {
        key: action[key]
        for key in compact_keys
        if key in action
    }
    # 反馈是恢复当前 Action 所需的控制面事实，但不能把宿主历史或大段
    # 工具输出重新塞回 compact stdout。Core 侧的 setup/repair 反馈已经是
    # 有界摘要，这里再做一道展示层上限保护。
    feedback = action.get("feedback")
    if isinstance(feedback, str) and feedback:
        compact["feedback"] = feedback[:2000]
    # gap_scan 的 section_ref 是 Core 规范值，不是文档标题。compact 视图直接
    # 携带有界映射，Coordinator 无需再读取完整 Action 才能生成合法结果。
    if action.get("stage") == "gap_scan":
        context = action.get("context")
        sections = context.get("host_design_sections") if isinstance(context, Mapping) else None
        if isinstance(sections, list):
            compact["gap_scan_section_refs"] = [
                {
                    "section_id": item.get("section_id") or item.get("id"),
                    "section_ref": item.get("design_section") or item.get("section_ref"),
                }
                for item in sections
                if isinstance(item, Mapping)
            ]
    extensions = action.get("extensions")
    if isinstance(extensions, Mapping):
        raw_ae = extensions.get("ae")
        if isinstance(raw_ae, Mapping):
            ae = {
                key: raw_ae[key]
                for key in ("execution_control", "runtime_revision", "runtime")
                if key in raw_ae
            }
            compact["extensions"] = {"ae": ae}
        else:
            compact.pop("extensions", None)
    host_execution = action.get("host_execution")
    if isinstance(host_execution, Mapping):
        projected_host = {
            key: host_execution[key]
            for key in (
                "schema_version",
                "platform",
                "action_message_id",
                "action_identity",
                "work_files",
                "continuation",
                "operations",
                "recovery",
                "native_worker_tools",
                "worker_observation",
            )
            if key in host_execution
        }
        workers = host_execution.get("workers")
        if isinstance(workers, list):
            projected_workers = []
            required_worker_contract = (
                "worker_id",
                "prompt_ref",
                "prompt_sha256",
                "native_launch_prompt",
                "expected_isolation_evidence",
                "host_fact_mapping",
                "outcome_path",
                "native_result_path",
                "observation_path",
                "execution_generation",
                "fencing_token",
                "receipt_path",
                "record_worker_outcome",
            )
            for worker in workers:
                if not isinstance(worker, Mapping):
                    continue
                if "native_launch_prompt" in worker:
                    missing = [
                        key for key in required_worker_contract if key not in worker
                    ]
                    if missing:
                        raise ValueError(
                            "HOST_ACTION_WORKER_CONTRACT_INVALID: "
                            + ",".join(missing)
                        )
                projected_workers.append({
                    key: worker[key]
                    for key in required_worker_contract
                    if key in worker
                })
            projected_host["workers"] = projected_workers
        compact["host_execution"] = projected_host
    compact["view"] = "compact"
    coordinator_reference = action.get("coordinator_prompt_ref")
    if isinstance(coordinator_reference, Mapping):
        reference = dict(coordinator_reference)
        raw_path = reference.get("path")
        raw_hash = reference.get("sha256")
        raw_size = reference.get("size_bytes")
        if (
            not isinstance(raw_path, str)
            or not raw_path
            or Path(raw_path).is_absolute()
            or ".." in Path(raw_path).parts
            or not isinstance(raw_hash, str)
            or not isinstance(raw_size, int)
            or raw_size < 1
        ):
            raise ValueError("HOST_PROMPT_REF_INVALID")
        prompt_path = root_bound_path(Path(raw_path), root)
        if not prompt_path.is_relative_to(root.resolve()):
            raise ValueError("HOST_PROMPT_PATH_ESCAPE")
        if not prompt_path.is_file():
            raise ValueError("HOST_PROMPT_REF_MISSING")
        encoded = prompt_path.read_bytes()
        if (
            hashlib.sha256(encoded).hexdigest() != raw_hash
            or len(encoded) != raw_size
        ):
            raise ValueError("HOST_PROMPT_REF_HASH_MISMATCH")
        compact["coordinator_prompt_ref"] = reference
    instruction = action.get("instruction")
    if (
        "coordinator_prompt_ref" not in compact
        and not isinstance(action.get("spawn"), Mapping)
        and isinstance(instruction, str)
        and instruction
    ):
        encoded = instruction.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        relative = Path(".ae-state/effects/prompt") / f"coordinator-{digest}.txt"
        prompt_path = (root.resolve() / relative).resolve()
        if not prompt_path.is_relative_to(root.resolve()):
            raise ValueError("HOST_PROMPT_PATH_ESCAPE")
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        if prompt_path.exists():
            if prompt_path.read_bytes() != encoded:
                raise ValueError("HOST_PROMPT_CONTENT_ADDRESS_CONFLICT")
        else:
            try:
                with prompt_path.open("xb") as handle:
                    handle.write(encoded)
            except FileExistsError:
                if prompt_path.read_bytes() != encoded:
                    raise ValueError(
                        "HOST_PROMPT_CONTENT_ADDRESS_CONFLICT"
                    ) from None
        compact["coordinator_prompt_ref"] = {
            "path": relative.as_posix(),
            "sha256": digest,
            "size_bytes": len(encoded),
            "media_type": "text/plain; charset=utf-8",
        }
    return compact
