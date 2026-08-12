"""Host Driver 共享状态机；不读取或修改业务状态。"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from auto_engineering.loop.execution_control import (
    ExecutionControl,
    ExecutionDisposition,
)


class HostDriverDecision(StrEnum):
    EXECUTE_NEXT = "execute_next"
    RETRY_RESOURCE = "retry_resource"
    WAIT = "wait"
    FINISH = "finish"
    FAIL = "fail"
    HANDOFF = "handoff"


def decide_host_step(action: Mapping[str, Any]) -> HostDriverDecision:
    """仅按机器处置返回宿主下一步，不从 stage/文本推断。"""

    extensions = action.get("extensions")
    if not isinstance(extensions, Mapping):
        raise ValueError("HOST_ACTION_EXECUTION_CONTROL_MISSING")
    ae = extensions.get("ae")
    if not isinstance(ae, Mapping):
        raise ValueError("HOST_ACTION_EXECUTION_CONTROL_MISSING")
    raw = ae.get("execution_control")
    if not isinstance(raw, Mapping):
        raise ValueError("HOST_ACTION_EXECUTION_CONTROL_MISSING")
    control = ExecutionControl.from_dict(raw)
    return {
        ExecutionDisposition.CONTINUE: HostDriverDecision.EXECUTE_NEXT,
        ExecutionDisposition.WAIT_RESOURCE: HostDriverDecision.RETRY_RESOURCE,
        ExecutionDisposition.WAIT_USER: HostDriverDecision.WAIT,
        ExecutionDisposition.TERMINAL: HostDriverDecision.FINISH,
        ExecutionDisposition.ERROR: HostDriverDecision.FAIL,
        ExecutionDisposition.HANDOFF_REQUIRED: HostDriverDecision.HANDOFF,
    }[control.disposition]


__all__ = ["HostDriverDecision", "decide_host_step"]
