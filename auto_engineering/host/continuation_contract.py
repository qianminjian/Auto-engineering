"""宿主调用返回后的 Core 续驱动合同。

该合同只描述宿主边界行为，不执行状态查询、不推进 Tick，也不启动新的
Coordinator。宿主在原生调用返回后必须先回查 Core，再决定是否让出控制权。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def continuation_contract(
    *,
    action: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """返回所有 Host Action 共用的返回后续驱动合同。"""

    contract: dict[str, Any] = {
        "schema_version": "1.0",
        "after_host_return": "recheck_core_status",
        "status_operation": "ae-run dev-loop --status --format json",
        "resume_operation": "resume_active_action",
        "same_action_rule": "thread_id_and_message_id_equal",
        "must_resume_when": ["CONTINUE"],
        "may_yield_when": [
            "WAIT_USER",
            "WAIT_RESOURCE",
            "TERMINAL",
            "ERROR",
            "HANDOFF_REQUIRED",
        ],
        "forbidden_success_when": ["CONTINUE"],
    }
    if isinstance(action, Mapping):
        # stage/tick are diagnostics only. A new Action may intentionally keep
        # the same stage (for example developer B1 -> developer B2).
        contract["action_identity"] = {
            "message_id": action.get("message_id"),
            "thread_id": action.get("thread_id"),
            "tick": action.get("tick"),
            "stage": action.get("stage"),
        }
    return contract


__all__ = ["continuation_contract"]
