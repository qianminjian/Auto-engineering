"""宿主 Action 映射所需的原生 Worker 合同原语。"""

from __future__ import annotations

import hashlib
import json

CODEX_NATIVE_WORKER_TOOL_FAMILIES = [
    {
        "spawn": "collaboration.spawn_agent",
        "wait": "collaboration.wait_agent",
        "close": "collaboration.interrupt_agent",
    },
    {
        "spawn": "multi_agent_v1__spawn_agent",
        "wait": "multi_agent_v1__wait_agent",
        "close": "multi_agent_v1__close_agent",
    },
]

CLAUDE_NATIVE_WORKER_TOOLS = {
    "selection": "claude_code_native_agent",
    "spawn": "Agent",
    "completion": "TaskOutput",
    "handle_field": "agentId_or_task_id",
    "model_field": "model_or_unreported",
    "isolation_evidence": "fresh_context",
}


def worker_fencing_token(
    action_message_id: str,
    worker_id: str,
    execution_generation: int,
) -> str:
    return hashlib.sha256(
        f"{action_message_id}:{worker_id}:{execution_generation}".encode()
    ).hexdigest()


def native_worker_launch_prompt(
    *,
    project_root: str,
    worker_id: str,
    prompt_ref: str,
    prompt_sha256: str,
    outcome_path: str,
    required_isolation_evidence: str,
    execution_generation: int,
    fencing_token: str,
) -> str:
    """生成不含 Worker 正文的有界原生启动合同。"""

    contract = {
        "schema_version": "1.0",
        "project_root": project_root,
        "worker_id": worker_id,
        "prompt_ref": prompt_ref,
        "prompt_sha256": prompt_sha256,
        "outcome_path": outcome_path,
        "may_drive_loop": False,
        "may_spawn_workers": False,
        "required_isolation_evidence": required_isolation_evidence,
    }
    return (
        "AUTO_ENGINEERING_NATIVE_WORKER_LAUNCH_V1\n"
        "VERBATIM=1;NO_EXTRA\n"
        "outcome_path:{worker_id,status,payload,summary}"
        "private;no_native_result;"
        "private_schema=objectpayload_nested"
        "never write payload directlyno bare payload"
        "stage_fields_only;no_expected_fields"
        "status=completed|failed|cancelled|timed_out"
        "aliases host;no host fields/shared outcomesread prompt_ref exactly"
        "no summary/reconstructionwrite exactly one JSON object; "
        "host metadata is read-only; never write generation/fence to outcome_path;\n"
        + json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


__all__ = [
    "CLAUDE_NATIVE_WORKER_TOOLS",
    "CODEX_NATIVE_WORKER_TOOL_FAMILIES",
    "native_worker_launch_prompt",
    "worker_fencing_token",
]
