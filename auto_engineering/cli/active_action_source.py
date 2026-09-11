"""CLI 活动 thread 与 active Action 的唯一运行事实读取边界。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class ActionEventSource(Protocol):
    """读取 active Action 所需的最小 EventStore 接口。"""

    def load_action_snapshot(self, thread_id: str) -> Mapping[str, Any] | None: ...


def active_thread(events: object) -> str | None:
    """从 EventStore 定位当前 thread；不读取其他状态快照。"""
    getter = getattr(events, "current_thread", None)
    return getter() if callable(getter) else None


def unfinished_thread(events: object) -> str | None:
    """返回唯一未终态 thread；多个候选必须拒绝猜测。"""
    getter = getattr(events, "unfinished_threads", None)
    if not callable(getter):
        return None
    candidates = [str(thread_id) for thread_id in getter()]
    if len(candidates) > 1:
        raise ValueError(
            "PROJECT_THREAD_AMBIGUOUS: EventStore 检测到多个未终态 thread: "
            + ", ".join(candidates)
        )
    return candidates[0] if candidates else None


def load_active_action(thread_id: str, events: ActionEventSource) -> dict | None:
    """从 EventStore 读取当前 active Action；不消费其他状态快照。"""

    event_action = events.load_action_snapshot(thread_id)
    if isinstance(event_action, Mapping):
        return dict(event_action)
    return None
