"""Worker 私有产物的唯一路径合同。"""

from __future__ import annotations

import hashlib


def action_key_for(message_id: str) -> str:
    """返回 Action message identity 的稳定短摘要。"""

    return hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:24]


def worker_outcome_path(
    message_id: str,
    worker_id: str,
    execution_generation: int,
) -> str:
    """返回当前 Action/generation/Worker 唯一的私有产物路径。"""

    if not message_id or not worker_id or execution_generation < 1:
        raise ValueError("WORKER_OUTCOME_PATH_INPUT_INVALID")
    safe_worker = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in worker_id
    )
    return (
        ".ae-state/host-runtime/worker-outcomes/"
        f"{action_key_for(message_id)}-{safe_worker}-g{execution_generation}.json"
    )


def worker_native_result_path(
    message_id: str,
    worker_id: str,
    execution_generation: int,
) -> str:
    """返回当前 Action 的原生返回暂存路径（不属于 Core 事实）。"""

    if not message_id or not worker_id or execution_generation < 1:
        raise ValueError("WORKER_NATIVE_RESULT_PATH_INPUT_INVALID")
    safe_worker = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in worker_id
    )
    return (
        ".ae-state/host-runtime/native-results/"
        f"{action_key_for(message_id)}-{safe_worker}-g{execution_generation}.json"
    )
