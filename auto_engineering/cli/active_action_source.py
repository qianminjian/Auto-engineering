"""CLI 活动 thread 与 active Action 的唯一运行事实读取边界。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class ActionEventSource(Protocol):
    """读取 active Action 所需的最小 EventStore 接口。"""

    def load_action_snapshot(self, thread_id: str) -> Mapping[str, Any] | None: ...


def active_thread(store: object) -> str | None:
    """读取项目占用租约；它只用于定位 thread，不承载运行事实。"""
    getter = getattr(store, "active_project_thread", None)
    return getter() if callable(getter) else None


def load_active_action(
    thread_id: str,
    store: object,
    events: ActionEventSource,
) -> dict | None:
    """从 EventStore 读取 active Action，并检测兼容 checkpoint 分叉。"""
    event_action = events.load_action_snapshot(thread_id)
    checkpoint_loader = getattr(store, "load_active_protocol_action", None)
    checkpoint_action = (
        checkpoint_loader(thread_id) if callable(checkpoint_loader) else None
    )
    if isinstance(event_action, Mapping) and isinstance(checkpoint_action, Mapping):
        event_id = event_action.get("message_id")
        checkpoint_id = checkpoint_action.get("message_id")
        if (
            isinstance(event_id, str)
            and isinstance(checkpoint_id, str)
            and event_id
            and checkpoint_id
            and event_id != checkpoint_id
        ):
            raise ValueError("STATE_SOURCE_CONFLICT")
    if isinstance(event_action, Mapping):
        return dict(event_action)
    return None
