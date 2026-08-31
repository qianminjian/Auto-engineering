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


def legacy_worker_outcome_path(message_id: str, worker_id: str) -> str:
    """返回 v5.8.0-rc.5 早期宿主使用的可验证迁移路径。

    这不是通配搜索：只允许当前 Action/Worker 对应的确定性路径，并且
    Collector 仍会校验 outcome 身份、generation 和 fencing。
    """

    if not message_id or not worker_id:
        raise ValueError("WORKER_OUTCOME_PATH_INPUT_INVALID")
    safe_worker = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in worker_id
    )
    return (
        ".ae-state/host-runtime/worker-outcomes/"
        f"{action_key_for(message_id)}/outcome-{safe_worker}.json"
    )
