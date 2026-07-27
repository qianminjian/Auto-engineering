"""Protocol v1.0 Result 到 v1.1 Envelope 的受限兼容适配。"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from auto_engineering.loop.protocol import (
    SCHEMA_VERSION,
    ProtocolErrorCode,
    ProtocolValidationError,
    validate_result_envelope,
)

_logger = logging.getLogger("ae.loop.protocol_compat")


def upgrade_legacy_result(
    result: Mapping[str, Any],
    active_action: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """在可唯一对齐当前 Action 时，把 v1.0 Result 升级为 v1.1。

    不查询已完成 stage，也不使用 stage 名猜测历史 Action。原生 v1.1 Result 只校验
    后原样返回。
    """

    if result.get("schema_version") is not None:
        validate_result_envelope(result)
        return dict(result)
    if active_action is None:
        raise ProtocolValidationError(
            ProtocolErrorCode.ACTION_NOT_ACTIVE,
            "旧版 Result 无法对齐：当前没有唯一 active action",
        )

    action_stage = active_action.get("stage")
    result_stage = result.get("stage")
    is_gate_resolution = isinstance(result.get("gate_resolution"), Mapping)
    is_control_result = is_gate_resolution or result.get("escalate") is True
    if (
        not is_control_result
        and (not isinstance(result_stage, str) or result_stage != action_stage)
    ):
        raise ProtocolValidationError(
            ProtocolErrorCode.ACTION_NOT_ACTIVE,
            "旧版 Result stage 与当前 active action 不一致，禁止猜测历史 Action",
        )

    thread_id = active_action.get("thread_id")
    action_id = active_action.get("message_id")
    tick = active_action.get("tick")
    if (
        not isinstance(thread_id, str)
        or not isinstance(action_id, str)
        or not isinstance(tick, int)
    ):
        raise ProtocolValidationError(
            ProtocolErrorCode.INVALID_ENVELOPE,
            "active action 缺少 v1.1 身份字段",
        )

    extensions = dict(result.get("extensions") or {})
    extensions["compat"] = {"source_schema_version": "1.0"}
    upgraded = {
        **result,
        "schema_version": SCHEMA_VERSION,
        "message_type": "result",
        "message_id": str(uuid4()),
        "thread_id": thread_id,
        "tick": tick,
        "stage": action_stage,
        "causation_id": action_id,
        "correlation_id": active_action.get("correlation_id") or thread_id,
        "extensions": extensions,
    }
    validate_result_envelope(upgraded)
    _logger.warning(
        "legacy_result_upgraded",
        extra={
            "thread_id": thread_id,
            "causation_id": action_id,
            "source_schema_version": "1.0",
        },
    )
    return upgraded
