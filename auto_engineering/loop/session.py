"""v5.8 ExecutionSession 模型与事件投影。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum

from auto_engineering.loop.events import LoopEvent, LoopEventType


class SessionStatus(StrEnum):
    ACTIVE = "active"
    HANDOFF_PENDING = "handoff_pending"
    CLOSED = "closed"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class ExecutionSession:
    session_id: str
    thread_id: str
    host: str
    started_by: str
    status: SessionStatus = SessionStatus.ACTIVE
    predecessor_session_id: str | None = None
    successor_session_id: str | None = None
    host_session_ref: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("session_id", "thread_id", "host", "started_by"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} 必须为非空字符串")


class SessionProjectionError(ValueError):
    """Session 事件流违反生命周期不变量。"""


@dataclass(slots=True)
class SessionProjection:
    sessions: dict[str, ExecutionSession] = None  # type: ignore[assignment]
    active_session_id: str | None = None

    def __post_init__(self) -> None:
        if self.sessions is None:
            self.sessions = {}

    def replay(self, events: Iterable[LoopEvent]) -> SessionProjection:
        projected = SessionProjection()
        for event in events:
            payload = event.to_dict()["payload"]
            event_type = event.event_type
            if event_type is LoopEventType.EXECUTION_SESSION_STARTED:
                session_id = _required(payload, "session_id")
                if projected.active_session_id is not None:
                    raise SessionProjectionError("同一 thread 只能有一个 active session")
                session = ExecutionSession(
                    session_id=session_id,
                    thread_id=event.thread_id,
                    host=_required(payload, "host"),
                    started_by=_required(payload, "started_by"),
                    predecessor_session_id=payload.get("predecessor_session_id"),
                    host_session_ref=payload.get("host_session_ref"),
                )
                projected.sessions[session_id] = session
                projected.active_session_id = session_id
            elif event_type is LoopEventType.SESSION_ROLLOVER_REQUESTED:
                session = projected._active(_required(payload, "session_id"))
                projected.sessions[session.session_id] = replace(
                    session, status=SessionStatus.HANDOFF_PENDING
                )
            elif event_type is LoopEventType.EXECUTION_SESSION_CLOSED:
                session = projected._known(_required(payload, "session_id"))
                projected.sessions[session.session_id] = replace(
                    session,
                    status=SessionStatus.CLOSED,
                    successor_session_id=payload.get("successor_session_id"),
                )
                if projected.active_session_id == session.session_id:
                    projected.active_session_id = None
            elif event_type is LoopEventType.EXECUTION_SESSION_ABANDONED:
                session = projected._known(_required(payload, "session_id"))
                projected.sessions[session.session_id] = replace(
                    session, status=SessionStatus.ABANDONED
                )
                if projected.active_session_id == session.session_id:
                    projected.active_session_id = None
        self.sessions = projected.sessions
        self.active_session_id = projected.active_session_id
        return self

    def _known(self, session_id: str) -> ExecutionSession:
        try:
            return self.sessions[session_id]
        except KeyError as exc:
            raise SessionProjectionError(f"未知 session: {session_id}") from exc

    def _active(self, session_id: str) -> ExecutionSession:
        session = self._known(session_id)
        if self.active_session_id != session_id:
            raise SessionProjectionError(f"session 不是 active: {session_id}")
        return session


def _required(payload: dict, field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise SessionProjectionError(f"{field} 必须为非空字符串")
    return value


__all__ = [
    "ExecutionSession",
    "SessionProjection",
    "SessionProjectionError",
    "SessionStatus",
]
