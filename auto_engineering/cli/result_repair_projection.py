"""宿主 Result 修复预算耗尽时的统一错误投影。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def result_repair_exhausted_action(
    active_action: Mapping[str, Any],
    journal_record: Mapping[str, Any] | None = None,
    *,
    violations: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """构造统一的宿主结果修复耗尽错误。"""

    action_message_id = active_action.get("message_id")
    action = {
        "action": "error",
        "error_code": "HOST_RESULT_REPAIR_EXHAUSTED",
        "message": (
            "同一 Action 的语义结果连续修复失败，已停止自动重试；"
            "请检查 Coordinator 结构化结果后显式恢复。"
        ),
        "active_action_message_id": action_message_id,
        "repair_attempt": (
            journal_record.get("attempt")
            if isinstance(journal_record, Mapping)
            else None
        ),
        "suggestion": "修复当前 Action 的 coordinator-result 后重新提交",
    }
    if violations is not None:
        action["message"] = (
            "同一 Action 的宿主语义结果连续修复失败，已停止自动重试；"
            "请检查 Coordinator 结构化结果和原生 Worker 证据后显式恢复。"
        )
        action["violations"] = list(violations)
    return action
