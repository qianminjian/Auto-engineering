"""Stage 决策到不可变 LoopEvent 的纯编译边界。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from auto_engineering.loop.events import LoopEvent, LoopEventType


@dataclass(frozen=True, slots=True)
class DomainEventSpec:
    event_type: LoopEventType
    payload: Mapping[str, Any]
    causation_id: str | None = None


def compile_domain_event(
    spec: DomainEventSpec,
    *,
    thread_id: str,
    sequence: int,
    correlation_id: str,
) -> LoopEvent:
    """以显式 identity 编译事件；不读取存储或全局状态。"""

    return LoopEvent.create(
        thread_id=thread_id,
        sequence=sequence,
        event_type=spec.event_type,
        payload=dict(spec.payload),
        causation_id=spec.causation_id,
        correlation_id=correlation_id,
    )


def state_channels_changed(
    changes: Mapping[str, Any],
    *,
    thread_id: str,
    sequence: int,
) -> LoopEvent:
    """编译迁移期有界 Projection delta，避免 Handler 返回命令式 patch。"""

    return compile_domain_event(
        DomainEventSpec(
            event_type=LoopEventType.STATE_CHANNELS_CHANGED,
            payload={"changes": dict(changes), "writer": "stage_handler"},
        ),
        thread_id=thread_id,
        sequence=sequence,
        correlation_id=thread_id,
    )


def transition_event(
    event_type: LoopEventType,
    *,
    thread_id: str,
    sequence: int,
    payload: Mapping[str, Any] | None = None,
) -> LoopEvent:
    """编译不携带命令式 ActionContext 的显式转换事实。"""

    return compile_domain_event(
        DomainEventSpec(event_type=event_type, payload=dict(payload or {})),
        thread_id=thread_id,
        sequence=sequence,
        correlation_id=thread_id,
    )


def channels_updated(
    event_type: LoopEventType,
    changes: Mapping[str, Any],
    *,
    thread_id: str,
    sequence: int,
) -> LoopEvent:
    """编译由特定领域事件拥有的 Projection channels。"""

    return transition_event(
        event_type,
        thread_id=thread_id,
        sequence=sequence,
        payload={"changes": dict(changes)},
    )


__all__ = [
    "DomainEventSpec",
    "channels_updated",
    "compile_domain_event",
    "state_channels_changed",
    "transition_event",
]
